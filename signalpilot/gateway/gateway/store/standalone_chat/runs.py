"""Run creation, cancellation, steering, retry, and run events."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayChatConversation,
    GatewayChatMessage,
    GatewayChatRun,
    GatewayChatRunEvent,
)
from gateway.models.standalone_chat import ChatRunEventInfo
from gateway.standalone_chat import config as chat_config
from gateway.standalone_chat.domain import (
    NONTERMINAL_RUN_STATUSES,
    RunStatus,
    assert_run_transition,
)
from gateway.store.standalone_chat.helpers import (
    _append_status_message,
    _event_info,
    _now,
    _owned_conversation_row,
    _owned_run_row,
    _retain_runtime_datasets_after_terminal_run,
    _stage_run_event,
)
from gateway.store.standalone_chat.worker import get_worker_run


async def create_run(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    message: str,
    message_metadata: dict[str, Any] | None = None,
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
        metadata_json={"surface": "standalone", **(message_metadata or {})},
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
        runtime_env=chat_config.runtime_env(),
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
    if run.status in {
        RunStatus.queued.value,
        RunStatus.waiting_for_user.value,
        RunStatus.waiting_for_query_approval.value,
    }:
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


async def queue_steering_message(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    run_id: str,
    message: str,
) -> GatewayChatMessage | None:
    """Persist a follow-up for delivery to the currently running SDK client."""
    run = await _owned_run_row(
        db, org_id=org_id, user_id=user_id, run_id=run_id, lock=True
    )
    if run is None:
        return None
    if run.status != RunStatus.running.value or run.cancellation_requested_at:
        raise RuntimeError("This run is not accepting queued messages")
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
    queued = GatewayChatMessage(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        role="user",
        content=message.strip(),
        metadata_json={
            "surface": "standalone",
            "steering_for_run_id": run.id,
            "steering_status": "queued",
        },
        sequence=sequence,
        created_at=now,
    )
    db.add(queued)
    conversation.message_count = sequence
    conversation.updated_at = now
    _stage_run_event(
        db,
        run=run,
        event_type="steering_queued",
        payload={"message_id": queued.id, "status": "queued"},
    )
    await db.commit()
    await db.refresh(queued)
    return queued


async def pending_steering_messages(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
) -> list[GatewayChatMessage]:
    """Return this worker's undelivered steering messages in transcript order."""
    run = await get_worker_run(db, run_id=run_id, worker_id=worker_id)
    if run is None:
        return []
    rows = list(
        (
            await db.execute(
                select(GatewayChatMessage)
                .where(
                    GatewayChatMessage.conversation_id == run.conversation_id,
                    GatewayChatMessage.role == "user",
                )
                .order_by(GatewayChatMessage.sequence)
            )
        ).scalars()
    )
    return [
        row
        for row in rows
        if (row.metadata_json or {}).get("steering_for_run_id") == run.id
        and (row.metadata_json or {}).get("steering_status") == "queued"
    ]


async def mark_steering_message_picked_up(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    message_id: str,
) -> bool:
    run = await get_worker_run(db, run_id=run_id, worker_id=worker_id)
    if run is None:
        return False
    message = (
        await db.execute(
            select(GatewayChatMessage)
            .where(
                GatewayChatMessage.id == message_id,
                GatewayChatMessage.conversation_id == run.conversation_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if message is None:
        return False
    metadata = dict(message.metadata_json or {})
    if (
        metadata.get("steering_for_run_id") != run.id
        or metadata.get("steering_status") != "queued"
    ):
        return False
    metadata["steering_status"] = "picked_up"
    message.metadata_json = metadata
    _stage_run_event(
        db,
        run=run,
        event_type="steering_picked_up",
        payload={"message_id": message.id, "status": "picked_up"},
    )
    await db.commit()
    return True


async def finalize_undelivered_steering(
    db: AsyncSession,
    *,
    run_id: str,
) -> int:
    """Resolve queued transcript labels after a run can no longer accept them."""
    run = await db.get(GatewayChatRun, run_id)
    if run is None:
        return 0
    messages = list(
        (
            await db.execute(
                select(GatewayChatMessage).where(
                    GatewayChatMessage.conversation_id == run.conversation_id,
                    GatewayChatMessage.role == "user",
                )
            )
        ).scalars()
    )
    unresolved = [
        message
        for message in messages
        if (message.metadata_json or {}).get("steering_for_run_id") == run.id
        and (message.metadata_json or {}).get("steering_status") == "queued"
    ]
    for message in unresolved:
        metadata = dict(message.metadata_json or {})
        metadata["steering_status"] = "not_delivered"
        message.metadata_json = metadata
        _stage_run_event(
            db,
            run=run,
            event_type="steering_not_delivered",
            payload={"message_id": message.id, "status": "not_delivered"},
        )
    if unresolved:
        await db.commit()
    return len(unresolved)


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
        runtime_env=chat_config.runtime_env(),
    )
    db.add(retry)
    from gateway.store.chat_reports import rebind_refresh_retry

    await rebind_refresh_retry(db, failed_run_id=failed.id, retry_run_id=retry.id)
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
            select(GatewayChatRun)
            .where(GatewayChatRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    event = _stage_run_event(
        db,
        run=run,
        event_type=event_type,
        payload=payload,
    )
    await db.execute(
        update(GatewayChatConversation)
        .where(GatewayChatConversation.id == run.conversation_id)
        .values(updated_at=time.time())
    )
    await db.commit()
    await db.refresh(event)
    return event


async def set_conversation_notebook_for_run(
    db: AsyncSession,
    *,
    run_id: str,
    gateway_session_id: str,
    kernel_session_id: str,
    notebook_path: str,
) -> None:
    """Record where the run's conversation notebook lives.

    The conversation is the owner of the notebook. Later runs adopt the same
    kernel and notebook, so the newest write always wins.
    """
    conversation_id = (
        await db.execute(
            select(GatewayChatRun.conversation_id).where(GatewayChatRun.id == run_id)
        )
    ).scalar_one_or_none()
    if conversation_id is None:
        return
    await db.execute(
        update(GatewayChatConversation)
        .where(GatewayChatConversation.id == conversation_id)
        .values(
            notebook_session_id=gateway_session_id,
            notebook_kernel_session_id=kernel_session_id,
            notebook_path=notebook_path,
        )
    )
    await db.commit()


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
        (
            await db.execute(
                select(GatewayChatRunEvent)
                .where(
                    GatewayChatRunEvent.run_id == run_id,
                    GatewayChatRunEvent.sequence > after,
                )
                .order_by(GatewayChatRunEvent.sequence)
            )
        )
        .scalars()
        .all()
    )
    return [_event_info(row) for row in events]
