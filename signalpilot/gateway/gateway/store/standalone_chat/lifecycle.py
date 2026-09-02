"""Terminal run transitions: complete, wait for clarification, and fail."""

from __future__ import annotations

import time
import uuid
from contextlib import suppress
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayChatArtifact,
    GatewayChatConversation,
    GatewayChatMessage,
    GatewayChatRun,
)
from gateway.standalone_chat.domain import (
    RunStatus,
    assert_run_transition,
    fallback_conversation_title,
    redact_error_text,
)
from gateway.store.standalone_chat.helpers import (
    _append_status_message,
    _now,
    _retain_runtime_datasets_after_terminal_run,
    _stage_run_event,
)


def _object_storage():
    """Resolve the storage factory through the package namespace at call time.

    Tests patch chat_object_storage on the package module. Read the name late
    so the patch takes effect."""
    from gateway.store import standalone_chat as chat_store

    return chat_store.chat_object_storage()

async def complete_run(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    content: str,
    report_proposal: dict[str, Any] | None = None,
    report_action_outcome: dict[str, Any] | None = None,
    dashboard_preview: dict[str, Any] | None = None,
) -> GatewayChatMessage | None:
    run = (
        await db.execute(
            select(GatewayChatRun)
            .where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.lease_owner == worker_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        return None
    existing = (
        await db.execute(
            select(GatewayChatMessage).where(GatewayChatMessage.idempotency_key == f"chat-run:{run.id}:final")
        )
    ).scalar_one_or_none()
    if existing:
        if run.status == RunStatus.running.value:
            run.status = RunStatus.completed.value
            run.terminal_at = run.terminal_at or _now()
            run.lease_owner = None
            run.lease_expires_at = None
            _stage_run_event(
                db,
                run=run,
                event_type="status",
                payload={"status": RunStatus.completed.value},
            )
            await _retain_runtime_datasets_after_terminal_run(db, run=run)
            from gateway.store.chat_reports import finalize_refresh_for_run

            await finalize_refresh_for_run(db, run=run, succeeded=True)
            await db.commit()
        return existing

    if run.cancellation_requested_at:
        assert_run_transition(run.status, RunStatus.cancelled.value)
        run.status = RunStatus.cancelled.value
        run.terminal_at = _now()
        run.lease_owner = None
        run.lease_expires_at = None
        await _append_status_message(
            db,
            run=run,
            status=RunStatus.cancelled.value,
            content="This run was stopped.",
        )
        _stage_run_event(
            db,
            run=run,
            event_type="status",
            payload={"status": RunStatus.cancelled.value},
        )
        await _retain_runtime_datasets_after_terminal_run(db, run=run)
        from gateway.store.chat_reports import finalize_refresh_for_run

        await finalize_refresh_for_run(db, run=run, succeeded=False)
        await db.commit()
        return None
    conversation = (
        await db.execute(
            select(GatewayChatConversation).where(GatewayChatConversation.id == run.conversation_id).with_for_update()
        )
    ).scalar_one()
    report_suggestion = None
    if report_proposal:
        from gateway.store.chat_reports import validate_report_proposal_for_run

        try:
            validated = await validate_report_proposal_for_run(
                db,
                run=run,
                proposal=report_proposal,
            )
            report_suggestion = validated.model_dump(mode="json") if validated else None
        except (LookupError, RuntimeError, ValueError):
            report_suggestion = None
    no_suggestion_outcome = None
    if isinstance(report_action_outcome, dict) and report_action_outcome.get("action") == "no_suggestion":
        no_suggestion_outcome = {
            "action": "no_suggestion",
            "artifact_kind": report_action_outcome.get("artifact_kind"),
            "artifact_filename": report_action_outcome.get("artifact_filename"),
            "reason": str(report_action_outcome.get("reason") or "")[:2000],
            "source": report_action_outcome.get("source") or "agent",
            "catalog_scan_complete": bool(report_action_outcome.get("catalog_scan_complete")),
        }
    safe_dashboard_preview = None
    if isinstance(dashboard_preview, dict):
        session_id = str(dashboard_preview.get("authoring_session_id") or "").strip()
        if session_id:
            safe_dashboard_preview = {
                "authoring_session_id": session_id,
                "dashboard_name": str(
                    dashboard_preview.get("dashboard_name") or "Dashboard preview"
                )[:200],
                "summary": str(dashboard_preview.get("summary") or "")[:2000],
                "chart_count": max(0, int(dashboard_preview.get("chart_count") or 0)),
                "requires_review": True,
                "apply_required": True,
            }
    sequence = conversation.message_count + 1
    message = GatewayChatMessage(
        id=str(uuid.uuid4()),
        org_id=run.org_id,
        user_id=run.user_id,
        project_id=run.project_id,
        conversation_id=run.conversation_id,
        role="assistant",
        content=content.strip(),
        metadata_json={
            "surface": "standalone",
            "run_id": run.id,
            "status": "completed",
            "runtime_archive_available": bool(run.runtime_archive_id),
            **({"report_suggestion": report_suggestion} if report_suggestion else {}),
            **({"report_action_outcome": no_suggestion_outcome} if no_suggestion_outcome else {}),
            **({"dashboard_preview": safe_dashboard_preview} if safe_dashboard_preview else {}),
        },
        idempotency_key=f"chat-run:{run.id}:final",
        sequence=sequence,
        created_at=time.time(),
    )
    db.add(message)
    conversation.message_count = sequence
    conversation.updated_at = time.time()
    if not conversation.title or conversation.title == "New chat":
        first_question = (
            await db.execute(
                select(GatewayChatMessage)
                .where(
                    GatewayChatMessage.conversation_id == run.conversation_id,
                    GatewayChatMessage.role == "user",
                )
                .order_by(GatewayChatMessage.sequence)
                .limit(1)
            )
        ).scalar_one_or_none()
        conversation.title = fallback_conversation_title(first_question.content if first_question else content)
    assert_run_transition(run.status, RunStatus.completed.value)
    run.status = RunStatus.completed.value
    run.terminal_at = _now()
    run.lease_owner = None
    run.lease_expires_at = None
    _stage_run_event(
        db,
        run=run,
        event_type="status",
        payload={"status": RunStatus.completed.value},
    )
    await _retain_runtime_datasets_after_terminal_run(db, run=run)
    await db.flush()
    artifacts = (
        (
            await db.execute(
                select(GatewayChatArtifact).where(
                    GatewayChatArtifact.run_id == run.id,
                    GatewayChatArtifact.assistant_message_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for artifact in artifacts:
        artifact.assistant_message_id = message.id
    from gateway.store.chat_reports import finalize_refresh_for_run

    await finalize_refresh_for_run(db, run=run, succeeded=True)
    await db.commit()
    return message


async def wait_for_clarification(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    question: str,
) -> GatewayChatMessage | None:
    run = (
        await db.execute(
            select(GatewayChatRun)
            .where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.lease_owner == worker_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        return None
    idempotency_key = f"chat-run:{run.id}:clarification:{run.execution_attempt}"
    existing = (
        await db.execute(select(GatewayChatMessage).where(GatewayChatMessage.idempotency_key == idempotency_key))
    ).scalar_one_or_none()
    if existing:
        return existing
    conversation = (
        await db.execute(
            select(GatewayChatConversation).where(GatewayChatConversation.id == run.conversation_id).with_for_update()
        )
    ).scalar_one()
    sequence = conversation.message_count + 1
    message = GatewayChatMessage(
        id=str(uuid.uuid4()),
        org_id=run.org_id,
        user_id=run.user_id,
        project_id=run.project_id,
        conversation_id=run.conversation_id,
        role="assistant",
        content=question.strip(),
        metadata_json={
            "surface": "standalone",
            "run_id": run.id,
            "status": "waiting_for_user",
            "clarification": True,
        },
        idempotency_key=idempotency_key,
        sequence=sequence,
        created_at=time.time(),
    )
    db.add(message)
    conversation.message_count = sequence
    conversation.updated_at = time.time()
    assert_run_transition(run.status, RunStatus.waiting_for_user.value)
    run.status = RunStatus.waiting_for_user.value
    run.lease_owner = None
    run.lease_expires_at = None
    _stage_run_event(
        db,
        run=run,
        event_type="status",
        payload={"status": RunStatus.waiting_for_user.value},
    )
    await db.commit()
    return message


async def fail_run(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    code: str,
    message: str,
) -> bool:
    run = (
        await db.execute(
            select(GatewayChatRun)
            .where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.lease_owner == worker_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        return False
    target = RunStatus.cancelled.value if run.cancellation_requested_at else RunStatus.failed.value
    assert_run_transition(run.status, target)
    run.status = target
    run.public_error_code = str(code)[:100]
    run.public_error_message = redact_error_text(message)
    run.terminal_at = _now()
    run.lease_owner = None
    run.lease_expires_at = None
    await _append_status_message(
        db,
        run=run,
        status=target,
        content=run.public_error_message,
    )
    _stage_run_event(
        db,
        run=run,
        event_type="status",
        payload={"status": target},
    )
    await _retain_runtime_datasets_after_terminal_run(db, run=run)
    from gateway.store.chat_reports import finalize_refresh_for_run

    await finalize_refresh_for_run(db, run=run, succeeded=False)
    artifact_object_keys = list(
        (
            await db.execute(
                select(
                    GatewayChatArtifact.object_key,
                    GatewayChatArtifact.source_object_key,
                ).where(GatewayChatArtifact.run_id == run.id)
            )
        ).all()
    )
    await db.execute(delete(GatewayChatArtifact).where(GatewayChatArtifact.run_id == run.id))
    await db.commit()
    if artifact_object_keys:
        storage = _object_storage()
        for object_key, source_object_key in artifact_object_keys:
            for key in (object_key, source_object_key):
                if key:
                    with suppress(Exception):
                        await storage.delete(key)
    return True
