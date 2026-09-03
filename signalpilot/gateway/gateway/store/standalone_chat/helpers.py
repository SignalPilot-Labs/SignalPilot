"""Shared row loaders, info mappers, and event staging helpers."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayChatConversation,
    GatewayChatMessage,
    GatewayChatRun,
    GatewayChatRunEvent,
    GatewayRuntimeDataset,
)
from gateway.models.standalone_chat import (
    ChatRunEventInfo,
    ChatRunInfo,
    StandaloneMessageInfo,
)
from gateway.standalone_chat.domain import redact_public_payload


def _now() -> datetime:
    return datetime.now(UTC)


async def _retain_runtime_datasets_after_terminal_run(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
) -> None:
    if run.terminal_at is None:
        return
    await db.execute(
        update(GatewayRuntimeDataset)
        .where(GatewayRuntimeDataset.run_id == run.id)
        .values(expires_at=run.terminal_at + timedelta(hours=24))
    )


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


async def get_owned_conversation(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
) -> GatewayChatConversation | None:
    """Load a conversation row the caller owns, or None."""
    return await _owned_conversation_row(
        db,
        org_id=org_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )


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
        runtime_archive_available=bool(row.runtime_archive_id),
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


async def _append_status_message(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
    status: str,
    content: str,
) -> GatewayChatMessage:
    idempotency_key = f"chat-run:{run.id}:{status}"
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


def _stage_run_event(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
    event_type: str,
    payload: dict[str, Any],
) -> GatewayChatRunEvent:
    """Add an event to the run's current transaction without committing it."""
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
    return event
