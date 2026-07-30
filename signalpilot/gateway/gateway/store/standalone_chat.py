"""Persistence authority for author-private standalone data chat."""

from __future__ import annotations

import base64
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayChatArtifact,
    GatewayChatConversation,
    GatewayChatMessage,
    GatewayChatRun,
    GatewayChatRunEvent,
    GatewayWorkspaceProject,
)
from gateway.models.standalone_chat import (
    ChatArtifactInfo,
    ChatRunEventInfo,
    ChatRunInfo,
    StandaloneConversationDetail,
    StandaloneConversationInfo,
    StandaloneMessageInfo,
)
from gateway.standalone_chat.artifacts import (
    normalize_table_snapshot,
    safe_filename,
    sanitize_chart_snapshot,
    sanitize_report_html,
    validate_artifact_size,
)
from gateway.standalone_chat.domain import (
    NONTERMINAL_RUN_STATUSES,
    RunStatus,
    assert_run_transition,
    fallback_conversation_title,
    redact_public_payload,
)


def _now() -> datetime:
    return datetime.now(UTC)


async def _owned_conversation_row(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    active_only: bool = True,
    lock: bool = False,
) -> GatewayChatConversation | None:
    query = select(GatewayChatConversation).where(
        GatewayChatConversation.id == conversation_id,
        GatewayChatConversation.org_id == org_id,
        GatewayChatConversation.user_id == user_id,
        GatewayChatConversation.surface == "standalone",
    )
    if active_only:
        query = query.where(GatewayChatConversation.status == "active")
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def _owned_run_row(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    run_id: str,
    lock: bool = False,
) -> GatewayChatRun | None:
    query = (
        select(GatewayChatRun)
        .join(
            GatewayChatConversation,
            GatewayChatConversation.id == GatewayChatRun.conversation_id,
        )
        .where(
            GatewayChatRun.id == run_id,
            GatewayChatRun.org_id == org_id,
            GatewayChatRun.user_id == user_id,
            GatewayChatConversation.surface == "standalone",
            GatewayChatConversation.status == "active",
        )
    )
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


def _run_info(row: GatewayChatRun) -> ChatRunInfo:
    return ChatRunInfo(
        id=row.id,
        conversation_id=row.conversation_id,
        status=row.status,
        retry_of_run_id=row.retry_of_run_id,
        public_error_code=row.public_error_code,
        public_error_message=row.public_error_message,
        cancellation_requested_at=row.cancellation_requested_at,
        created_at=row.created_at,
        started_at=row.started_at,
        terminal_at=row.terminal_at,
        last_event_sequence=row.last_event_sequence,
    )


def _message_info(row: GatewayChatMessage) -> StandaloneMessageInfo:
    metadata = dict(row.metadata_json or {})
    metadata.pop("internal", None)
    return StandaloneMessageInfo(
        id=row.id,
        role=row.role,
        content=row.content,
        sequence=row.sequence,
        created_at=row.created_at,
        metadata=metadata,
    )


def _event_info(row: GatewayChatRunEvent) -> ChatRunEventInfo:
    return ChatRunEventInfo(
        run_id=row.run_id,
        sequence=row.sequence,
        type=row.event_type,
        payload=row.payload_json,
        created_at=row.created_at,
    )


def _artifact_info(row: GatewayChatArtifact) -> ChatArtifactInfo:
    formats = {
        "table": ["csv"],
        "chart": ["png", "csv"],
        "report": ["html"],
    }[row.kind]
    return ChatArtifactInfo(
        id=row.id,
        run_id=row.run_id,
        assistant_message_id=row.assistant_message_id,
        kind=row.kind,
        filename=row.filename,
        mime_type=row.mime_type,
        snapshot=row.snapshot_json,
        provenance=row.provenance_json,
        freshness_at=row.freshness_at,
        assumptions=[str(value) for value in row.assumptions or []],
        exclusions=[str(value) for value in row.exclusions or []],
        caveats=[str(value) for value in row.caveats or []],
        parent_artifact_id=row.parent_artifact_id,
        created_at=row.created_at,
        download_formats=formats,
    )


def _bounded_artifact_notes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:500] for item in value[:100]]


async def _append_status_message(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
    status: str,
    content: str,
) -> GatewayChatMessage:
    idempotency_key = f"chat-run:{run.id}:{status}"
    existing = (
        await db.execute(
            select(GatewayChatMessage).where(
                GatewayChatMessage.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    conversation = (
        await db.execute(
            select(GatewayChatConversation)
            .where(GatewayChatConversation.id == run.conversation_id)
            .with_for_update()
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
        content=content.strip(),
        metadata_json={
            "surface": "standalone",
            "run_id": run.id,
            "status": status,
        },
        idempotency_key=idempotency_key,
        sequence=sequence,
        created_at=time.time(),
    )
    db.add(message)
    conversation.message_count = sequence
    conversation.updated_at = time.time()
    return message


async def create_conversation_with_run(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project: GatewayWorkspaceProject,
    branch: str,
    message: str,
) -> tuple[GatewayChatConversation, GatewayChatRun]:
    """Atomically create the first conversation, message, and queued run."""
    now = time.time()
    conversation = GatewayChatConversation(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=project.id,
        surface="standalone",
        branch=branch,
        status="active",
        title="New chat",
        message_count=1,
        total_tokens=0,
        total_cost_usd=0.0,
        created_at=now,
        updated_at=now,
    )
    user_message = GatewayChatMessage(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=project.id,
        conversation_id=conversation.id,
        role="user",
        content=message.strip(),
        metadata_json={"surface": "standalone"},
        sequence=1,
        created_at=now,
    )
    run = GatewayChatRun(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation.id,
        project_id=project.id,
        user_message_id=user_message.id,
        status=RunStatus.queued.value,
    )
    db.add_all([conversation, user_message, run])
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(run)
    return conversation, run


async def list_conversations(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
) -> list[StandaloneConversationInfo]:
    rows = (
        await db.execute(
            select(GatewayChatConversation, GatewayWorkspaceProject)
            .join(
                GatewayWorkspaceProject,
                and_(
                    GatewayWorkspaceProject.id == GatewayChatConversation.project_id,
                    GatewayWorkspaceProject.org_id == GatewayChatConversation.org_id,
                ),
                isouter=True,
            )
            .where(
                GatewayChatConversation.org_id == org_id,
                GatewayChatConversation.user_id == user_id,
                GatewayChatConversation.surface == "standalone",
                GatewayChatConversation.status == "active",
            )
            .order_by(GatewayChatConversation.updated_at.desc())
        )
    ).all()
    result: list[StandaloneConversationInfo] = []
    for conversation, project in rows:
        latest_run = (
            await db.execute(
                select(GatewayChatRun)
                .where(GatewayChatRun.conversation_id == conversation.id)
                .order_by(GatewayChatRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        result.append(
            StandaloneConversationInfo(
                id=conversation.id,
                project_id=conversation.project_id or "",
                project_name=(project.display_name or project.name) if project else None,
                branch=conversation.branch or "main",
                title=conversation.title or "New chat",
                status=conversation.status,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                run_status=latest_run.status if latest_run else None,
            )
        )
    return result


async def get_conversation_detail(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
) -> StandaloneConversationDetail | None:
    conversation = await _owned_conversation_row(
        db,
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        return None
    project = (
        await db.execute(
            select(GatewayWorkspaceProject).where(
                GatewayWorkspaceProject.id == conversation.project_id,
                GatewayWorkspaceProject.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    messages = (
        await db.execute(
            select(GatewayChatMessage)
            .where(
                GatewayChatMessage.conversation_id == conversation_id,
                GatewayChatMessage.org_id == org_id,
                GatewayChatMessage.user_id == user_id,
            )
            .order_by(GatewayChatMessage.sequence)
        )
    ).scalars().all()
    artifacts = (
        await db.execute(
            select(GatewayChatArtifact)
            .where(
                GatewayChatArtifact.conversation_id == conversation_id,
                GatewayChatArtifact.org_id == org_id,
                GatewayChatArtifact.user_id == user_id,
            )
            .order_by(GatewayChatArtifact.created_at)
        )
    ).scalars().all()
    current_run = (
        await db.execute(
            select(GatewayChatRun)
            .where(GatewayChatRun.conversation_id == conversation_id)
            .order_by(GatewayChatRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    events = list(
        (
            await db.execute(
                select(GatewayChatRunEvent)
                .where(GatewayChatRunEvent.conversation_id == conversation_id)
                .order_by(GatewayChatRunEvent.created_at, GatewayChatRunEvent.sequence)
            )
        ).scalars()
    )
    return StandaloneConversationDetail(
        conversation=StandaloneConversationInfo(
            id=conversation.id,
            project_id=conversation.project_id or "",
            project_name=(project.display_name or project.name) if project else None,
            branch=conversation.branch or "main",
            title=conversation.title or "New chat",
            status=conversation.status,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            run_status=current_run.status if current_run else None,
        ),
        messages=[_message_info(row) for row in messages],
        artifacts=[_artifact_info(row) for row in artifacts],
        current_run=_run_info(current_run) if current_run else None,
        run_events=[_event_info(row) for row in events],
    )


async def rename_conversation(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    title: str,
) -> bool:
    conversation = await _owned_conversation_row(
        db,
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        return False
    conversation.title = title
    conversation.updated_at = time.time()
    await db.commit()
    return True


async def archive_conversation(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
) -> bool:
    conversation = await _owned_conversation_row(
        db,
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation_id,
        active_only=False,
        lock=True,
    )
    if conversation is None:
        return False
    if conversation.status != "archived":
        conversation.status = "archived"
        conversation.archived_at = _now()
        conversation.updated_at = time.time()
        await db.commit()
    return True


async def create_run(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
) -> GatewayChatRun:
    conversation = await _owned_conversation_row(
        db,
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation_id,
        lock=True,
    )
    if conversation is None:
        raise LookupError("Conversation not found")
    existing = (
        await db.execute(
            select(GatewayChatRun.id).where(
                GatewayChatRun.conversation_id == conversation_id,
                GatewayChatRun.status.in_(NONTERMINAL_RUN_STATUSES),
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise RuntimeError("A run is already active for this conversation")

    sequence = conversation.message_count + 1
    now = time.time()
    user_message = GatewayChatMessage(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        role="user",
        content=message.strip(),
        metadata_json={"surface": "standalone"},
        sequence=sequence,
        created_at=now,
    )
    run = GatewayChatRun(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation.id,
        project_id=conversation.project_id or "",
        user_message_id=user_message.id,
        status=RunStatus.queued.value,
    )
    db.add_all([user_message, run])
    conversation.message_count = sequence
    conversation.updated_at = now
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise RuntimeError("A run is already active for this conversation") from exc
    await db.refresh(run)
    return run


async def request_cancellation(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    run_id: str,
) -> GatewayChatRun | None:
    run = await _owned_run_row(db, org_id=org_id, user_id=user_id, run_id=run_id, lock=True)
    if run is None:
        return None
    if run.status in {
        RunStatus.completed.value,
        RunStatus.failed.value,
        RunStatus.cancelled.value,
    }:
        return run
    run.cancellation_requested_at = run.cancellation_requested_at or _now()
    if run.status in {RunStatus.queued.value, RunStatus.waiting_for_user.value}:
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
    await db.commit()
    return run


async def submit_clarification(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    run_id: str,
    message: str,
) -> GatewayChatRun | None:
    run = await _owned_run_row(db, org_id=org_id, user_id=user_id, run_id=run_id, lock=True)
    if run is None:
        return None
    if run.status != RunStatus.waiting_for_user.value:
        raise RuntimeError("This run is not waiting for clarification")
    conversation = await _owned_conversation_row(
        db,
        org_id=org_id,
        user_id=user_id,
        conversation_id=run.conversation_id,
        lock=True,
    )
    if conversation is None:
        return None
    sequence = conversation.message_count + 1
    now = time.time()
    db.add(
        GatewayChatMessage(
            id=str(uuid.uuid4()),
            org_id=org_id,
            user_id=user_id,
            project_id=conversation.project_id,
            conversation_id=conversation.id,
            role="user",
            content=message.strip(),
            metadata_json={"surface": "standalone", "clarification_for_run_id": run.id},
            sequence=sequence,
            created_at=now,
        )
    )
    conversation.message_count = sequence
    conversation.updated_at = now
    assert_run_transition(run.status, RunStatus.queued.value)
    run.status = RunStatus.queued.value
    run.lease_owner = None
    run.lease_expires_at = None
    run.public_error_code = None
    run.public_error_message = None
    await db.commit()
    return run


async def retry_run(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    run_id: str,
) -> GatewayChatRun | None:
    failed = await _owned_run_row(db, org_id=org_id, user_id=user_id, run_id=run_id, lock=True)
    if failed is None:
        return None
    if failed.status != RunStatus.failed.value:
        raise RuntimeError("Only failed runs can be retried")
    conversation = await _owned_conversation_row(
        db,
        org_id=org_id,
        user_id=user_id,
        conversation_id=failed.conversation_id,
        lock=True,
    )
    if conversation is None:
        return None
    existing = (
        await db.execute(
            select(GatewayChatRun.id).where(
                GatewayChatRun.conversation_id == failed.conversation_id,
                GatewayChatRun.status.in_(NONTERMINAL_RUN_STATUSES),
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise RuntimeError("A run is already active for this conversation")
    retry = GatewayChatRun(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        conversation_id=failed.conversation_id,
        project_id=failed.project_id,
        user_message_id=failed.user_message_id,
        status=RunStatus.queued.value,
        retry_of_run_id=failed.id,
    )
    db.add(retry)
    conversation.updated_at = time.time()
    await db.commit()
    await db.refresh(retry)
    return retry


async def append_event(
    db: AsyncSession,
    *,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> GatewayChatRunEvent:
    run = (
        await db.execute(
            select(GatewayChatRun).where(GatewayChatRun.id == run_id).with_for_update()
        )
    ).scalar_one()
    sequence = run.last_event_sequence + 1
    event = GatewayChatRunEvent(
        id=str(uuid.uuid4()),
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        sequence=sequence,
        event_type=event_type,
        payload_json=redact_public_payload(payload),
    )
    db.add(event)
    run.last_event_sequence = sequence
    await db.execute(
        update(GatewayChatConversation)
        .where(GatewayChatConversation.id == run.conversation_id)
        .values(updated_at=time.time())
    )
    await db.commit()
    await db.refresh(event)
    return event


async def list_run_events(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    run_id: str,
    after: int = 0,
) -> list[ChatRunEventInfo] | None:
    run = await _owned_run_row(db, org_id=org_id, user_id=user_id, run_id=run_id)
    if run is None:
        return None
    events = (
        await db.execute(
            select(GatewayChatRunEvent)
            .where(
                GatewayChatRunEvent.run_id == run_id,
                GatewayChatRunEvent.sequence > after,
            )
            .order_by(GatewayChatRunEvent.sequence)
        )
    ).scalars().all()
    return [_event_info(row) for row in events]


async def claim_runs(
    db: AsyncSession,
    *,
    worker_id: str,
    limit: int,
    lease_seconds: int,
) -> list[str]:
    now = _now()
    candidates = (
        await db.execute(
            select(GatewayChatRun)
            .where(
                or_(
                    GatewayChatRun.status == RunStatus.queued.value,
                    and_(
                        GatewayChatRun.status == RunStatus.running.value,
                        GatewayChatRun.lease_expires_at < now,
                    ),
                )
            )
            .order_by(GatewayChatRun.created_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
    ).scalars().all()
    claimed: list[str] = []
    for run in candidates:
        if run.cancellation_requested_at:
            assert_run_transition(run.status, RunStatus.cancelled.value)
            run.status = RunStatus.cancelled.value
            run.terminal_at = now
            run.lease_owner = None
            run.lease_expires_at = None
            await _append_status_message(
                db,
                run=run,
                status=RunStatus.cancelled.value,
                content="This run was stopped.",
            )
            continue
        if run.status == RunStatus.queued.value:
            assert_run_transition(run.status, RunStatus.running.value)
        run.status = RunStatus.running.value
        run.started_at = run.started_at or now
        run.execution_attempt += 1
        run.lease_owner = worker_id
        run.lease_expires_at = now + timedelta(seconds=lease_seconds)
        claimed.append(run.id)
    await db.commit()
    return claimed


async def renew_lease(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    lease_seconds: int,
) -> bool:
    run = (
        await db.execute(
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.status == RunStatus.running.value,
                GatewayChatRun.lease_owner == worker_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        return False
    run.lease_expires_at = _now() + timedelta(seconds=lease_seconds)
    await db.commit()
    return True


async def get_worker_run(db: AsyncSession, *, run_id: str, worker_id: str) -> GatewayChatRun | None:
    return (
        await db.execute(
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.status == RunStatus.running.value,
                GatewayChatRun.lease_owner == worker_id,
            )
        )
    ).scalar_one_or_none()


async def worker_context(db: AsyncSession, *, run: GatewayChatRun) -> dict[str, Any]:
    conversation = (
        await db.execute(
            select(GatewayChatConversation).where(
                GatewayChatConversation.id == run.conversation_id,
                GatewayChatConversation.org_id == run.org_id,
                GatewayChatConversation.user_id == run.user_id,
                GatewayChatConversation.surface == "standalone",
            )
        )
    ).scalar_one()
    project = (
        await db.execute(
            select(GatewayWorkspaceProject).where(
                GatewayWorkspaceProject.id == run.project_id,
                GatewayWorkspaceProject.org_id == run.org_id,
            )
        )
    ).scalar_one()
    messages = (
        await db.execute(
            select(GatewayChatMessage)
            .where(GatewayChatMessage.conversation_id == run.conversation_id)
            .order_by(GatewayChatMessage.sequence)
        )
    ).scalars().all()
    artifacts = (
        await db.execute(
            select(GatewayChatArtifact)
            .where(GatewayChatArtifact.conversation_id == run.conversation_id)
            .order_by(GatewayChatArtifact.created_at)
        )
    ).scalars().all()
    return {
        "conversation": conversation,
        "project": project,
        "messages": messages,
        "artifacts": artifacts,
    }


async def set_execution_session(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    execution_session_id: str,
) -> bool:
    run = (
        await db.execute(
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.lease_owner == worker_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        return False
    run.execution_session_id = execution_session_id
    await db.commit()
    return True


async def persist_artifact(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
    payload: dict[str, Any],
) -> GatewayChatArtifact:
    kind = str(payload.get("kind") or "")
    if kind not in {"table", "chart", "report"}:
        raise ValueError("Unsupported artifact kind")
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("Artifact snapshot must be an object")
    binary_data: bytes | None = None
    encoded = payload.get("binary_base64")
    if encoded:
        if len(str(encoded)) > (14 * 1024 * 1024):
            raise ValueError("Artifact exceeds the 10 MiB limit")
        try:
            binary_data = base64.b64decode(str(encoded), validate=True)
        except Exception as exc:
            raise ValueError("Artifact binary is not valid base64") from exc
    if kind == "report":
        html_value = str(snapshot.get("html") or "")
        snapshot = {**snapshot, "html": sanitize_report_html(html_value)}
    elif kind == "chart":
        if binary_data is None:
            raise ValueError("Chart artifacts require a PNG representation")
        snapshot = sanitize_chart_snapshot(snapshot)
    else:
        snapshot = normalize_table_snapshot(snapshot)
    provenance = redact_public_payload(payload.get("provenance") or {})
    assumptions = _bounded_artifact_notes(payload.get("assumptions"))
    exclusions = _bounded_artifact_notes(payload.get("exclusions"))
    caveats = _bounded_artifact_notes(payload.get("caveats"))
    validate_artifact_size(
        {
            "snapshot": snapshot,
            "provenance": provenance,
            "assumptions": assumptions,
            "exclusions": exclusions,
            "caveats": caveats,
        },
        binary_data,
    )
    default_ext = {"table": ".csv", "chart": ".png", "report": ".html"}[kind]
    filename = safe_filename(str(payload.get("filename") or ""), fallback=f"analysis{default_ext}")
    if not filename.lower().endswith(default_ext):
        filename = f"{filename.rsplit('.', 1)[0]}{default_ext}"
    expected_mime_type = {
        "table": "text/csv",
        "chart": "image/png",
        "report": "text/html",
    }[kind]
    supplied_mime_type = str(payload.get("mime_type") or expected_mime_type).split(";", 1)[0].strip().lower()
    if supplied_mime_type != expected_mime_type:
        raise ValueError("Artifact MIME type does not match its kind")
    mime_type = expected_mime_type
    existing = (
        await db.execute(
            select(GatewayChatArtifact).where(
                GatewayChatArtifact.run_id == run.id,
                GatewayChatArtifact.kind == kind,
                GatewayChatArtifact.filename == filename,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    artifact = GatewayChatArtifact(
        id=str(uuid.uuid4()),
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        kind=kind,
        filename=filename,
        mime_type=mime_type,
        snapshot_json=snapshot,
        binary_data=binary_data,
        provenance_json=provenance,
        freshness_at=_parse_datetime(payload.get("freshness_at")),
        assumptions=assumptions,
        exclusions=exclusions,
        caveats=caveats,
        parent_artifact_id=str(payload.get("parent_artifact_id") or "") or None,
    )
    if artifact.parent_artifact_id:
        parent = (
            await db.execute(
                select(GatewayChatArtifact.id).where(
                    GatewayChatArtifact.id == artifact.parent_artifact_id,
                    GatewayChatArtifact.org_id == run.org_id,
                    GatewayChatArtifact.user_id == run.user_id,
                    GatewayChatArtifact.conversation_id == run.conversation_id,
                )
            )
        ).scalar_one_or_none()
        if parent is None:
            raise ValueError("Parent artifact not found")
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)
    return artifact


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


async def complete_run(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    content: str,
) -> GatewayChatMessage | None:
    run = (
        await db.execute(
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.lease_owner == worker_id,
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        return None
    existing = (
        await db.execute(
            select(GatewayChatMessage).where(
                GatewayChatMessage.idempotency_key == f"chat-run:{run.id}:final"
            )
        )
    ).scalar_one_or_none()
    if existing:
        if run.status == RunStatus.running.value:
            run.status = RunStatus.completed.value
            run.terminal_at = run.terminal_at or _now()
            run.lease_owner = None
            run.lease_expires_at = None
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
        await db.commit()
        return None
    conversation = (
        await db.execute(
            select(GatewayChatConversation).where(
                GatewayChatConversation.id == run.conversation_id
            ).with_for_update()
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
        content=content.strip(),
        metadata_json={"surface": "standalone", "run_id": run.id, "status": "completed"},
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
        conversation.title = fallback_conversation_title(
            first_question.content if first_question else content
        )
    assert_run_transition(run.status, RunStatus.completed.value)
    run.status = RunStatus.completed.value
    run.terminal_at = _now()
    run.lease_owner = None
    run.lease_expires_at = None
    await db.flush()
    artifacts = (
        await db.execute(
            select(GatewayChatArtifact).where(
                GatewayChatArtifact.run_id == run.id,
                GatewayChatArtifact.assistant_message_id.is_(None),
            )
        )
    ).scalars().all()
    for artifact in artifacts:
        artifact.assistant_message_id = message.id
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
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.lease_owner == worker_id,
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        return None
    idempotency_key = f"chat-run:{run.id}:clarification:{run.execution_attempt}"
    existing = (
        await db.execute(
            select(GatewayChatMessage).where(
                GatewayChatMessage.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    conversation = (
        await db.execute(
            select(GatewayChatConversation).where(
                GatewayChatConversation.id == run.conversation_id
            ).with_for_update()
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
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.lease_owner == worker_id,
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        return False
    target = (
        RunStatus.cancelled.value
        if run.cancellation_requested_at
        else RunStatus.failed.value
    )
    assert_run_transition(run.status, target)
    run.status = target
    run.public_error_code = str(code)[:100]
    run.public_error_message = str(redact_public_payload(message))[:1000]
    run.terminal_at = _now()
    run.lease_owner = None
    run.lease_expires_at = None
    await _append_status_message(
        db,
        run=run,
        status=target,
        content=run.public_error_message or "The run could not be completed.",
    )
    await db.commit()
    return True


async def get_artifact(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    artifact_id: str,
) -> GatewayChatArtifact | None:
    return (
        await db.execute(
            select(GatewayChatArtifact)
            .join(
                GatewayChatConversation,
                GatewayChatConversation.id == GatewayChatArtifact.conversation_id,
            )
            .where(
                GatewayChatArtifact.id == artifact_id,
                GatewayChatArtifact.org_id == org_id,
                GatewayChatArtifact.user_id == user_id,
                GatewayChatConversation.surface == "standalone",
                GatewayChatConversation.status == "active",
            )
        )
    ).scalar_one_or_none()


async def update_internal_summary(
    db: AsyncSession,
    *,
    conversation_id: str,
    summary: str,
) -> None:
    conversation = (
        await db.execute(
            select(GatewayChatConversation).where(
                GatewayChatConversation.id == conversation_id
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        return
    conversation.internal_summary = summary[:100_000]
    await db.commit()
