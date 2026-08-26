"""Gateway-owned durable notebook chat trace storage."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayChatTraceEvent, GatewayChatTraceThread
from ..models.workspace import (
    ChatTraceEventCreate,
    ChatTraceEventInfo,
    ChatTraceThreadInfo,
    ChatTraceThreadUpsert,
)
from ..trace_markers import redact_trace_control_markers


def _thread_scope(org_id: str, thread_id: str):
    return (
        GatewayChatTraceThread.org_id == org_id,
        GatewayChatTraceThread.thread_id == thread_id,
    )


def _event_scope(org_id: str, thread_id: str):
    return (
        GatewayChatTraceEvent.org_id == org_id,
        GatewayChatTraceEvent.thread_id == thread_id,
    )


async def upsert_thread(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    thread: ChatTraceThreadUpsert,
) -> ChatTraceThreadInfo:
    now = time.time()
    row = (
        await session.execute(
            select(GatewayChatTraceThread)
            .where(*_thread_scope(org_id, thread.thread_id))
            .order_by(GatewayChatTraceThread.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if row is None:
        row = GatewayChatTraceThread(
            id=str(uuid.uuid4()),
            org_id=org_id,
            user_id=user_id,
            thread_id=thread.thread_id,
            session_id=thread.session_id,
            source=thread.source,
            title=thread.title,
            status=thread.status,
            notebook_path=thread.notebook_path,
            notion_request_page_id=thread.notion_request_page_id,
            notion_discussion_id=thread.notion_discussion_id,
            metadata_json=thread.metadata,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.session_id = thread.session_id
        row.source = thread.source
        if thread.title:
            row.title = thread.title
        row.status = thread.status
        if thread.notebook_path:
            row.notebook_path = thread.notebook_path
        if thread.notion_request_page_id is not None:
            row.notion_request_page_id = thread.notion_request_page_id
        if thread.notion_discussion_id is not None:
            row.notion_discussion_id = thread.notion_discussion_id
        if thread.metadata is not None:
            row.metadata_json = thread.metadata
        row.updated_at = now

    await session.commit()
    return _thread_info(row)


async def clear_events(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    thread_id: str,
) -> bool:
    row = (
        await session.execute(
            select(GatewayChatTraceThread)
            .where(*_thread_scope(org_id, thread_id))
            .order_by(GatewayChatTraceThread.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return False

    await session.execute(
        sa_delete(GatewayChatTraceEvent).where(
            *_event_scope(org_id, thread_id)
        )
    )
    row.updated_at = time.time()
    await session.commit()
    return True


async def append_event(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    thread_id: str,
    event: ChatTraceEventCreate,
) -> int:
    thread = (
        await session.execute(
            select(GatewayChatTraceThread)
            .where(*_thread_scope(org_id, thread_id))
            .order_by(GatewayChatTraceThread.updated_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if thread is None:
        raise ValueError(f"Trace thread {thread_id} not found")

    next_idx = (
        await session.execute(
            select(sa_func.coalesce(sa_func.max(GatewayChatTraceEvent.idx), -1) + 1).where(
                *_event_scope(org_id, thread_id)
            )
        )
    ).scalar_one()
    idx = int(next_idx)
    now = time.time()
    content, metadata = redact_trace_control_markers(event.content or "", event.metadata)
    row = GatewayChatTraceEvent(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        thread_id=thread_id,
        idx=idx,
        event_type=event.type,
        role=event.role,
        content=content,
        tool_name=event.tool_name or "",
        tool_input_json=event.tool_input,
        tool_call_id=event.tool_call_id or "",
        is_error=bool(event.is_error),
        cost_usd=event.cost_usd,
        turn=int(event.turn or 0),
        metadata_json=metadata,
        created_at=now,
    )
    session.add(row)
    thread.updated_at = now
    await session.commit()
    return idx


async def list_threads(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    session_id: str | None = None,
    source: str | None = None,
    limit: int = 100,
) -> list[ChatTraceThreadInfo]:
    q = select(GatewayChatTraceThread).where(
        GatewayChatTraceThread.org_id == org_id,
    )
    if session_id:
        q = q.where(GatewayChatTraceThread.session_id == session_id)
    if source:
        q = q.where(GatewayChatTraceThread.source == source)
    q = q.order_by(GatewayChatTraceThread.updated_at.desc()).limit(limit)
    result = await session.execute(q)
    return [_thread_info(row) for row in result.scalars()]


async def get_thread(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    thread_id: str,
) -> ChatTraceThreadInfo | None:
    row = (
        await session.execute(
            select(GatewayChatTraceThread)
            .where(*_thread_scope(org_id, thread_id))
            .order_by(GatewayChatTraceThread.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _thread_info(row) if row else None


async def get_events(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    thread_id: str,
    after_index: int = -1,
    require_thread: bool = True,
) -> list[ChatTraceEventInfo]:
    if require_thread:
        thread = await get_thread(
            session, org_id=org_id, user_id=user_id, thread_id=thread_id
        )
        if thread is None:
            raise ValueError(f"Trace thread {thread_id} not found")

    result = await session.execute(
        select(GatewayChatTraceEvent)
        .where(
            *_event_scope(org_id, thread_id),
            GatewayChatTraceEvent.idx > after_index,
        )
        .order_by(GatewayChatTraceEvent.idx.asc())
    )
    return [_event_info(row) for row in result.scalars()]


def _thread_info(row: GatewayChatTraceThread) -> ChatTraceThreadInfo:
    return ChatTraceThreadInfo(
        thread_id=row.thread_id,
        session_id=row.session_id,
        source=row.source,
        title=row.title or "",
        status=row.status,
        notebook_path=row.notebook_path or "",
        notion_request_page_id=row.notion_request_page_id,
        notion_discussion_id=row.notion_discussion_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata=row.metadata_json or {},
    )


def _event_info(row: GatewayChatTraceEvent) -> ChatTraceEventInfo:
    return ChatTraceEventInfo(
        idx=row.idx,
        type=row.event_type,
        role=row.role,
        content=row.content or "",
        tool_name=row.tool_name or "",
        tool_input=row.tool_input_json,
        tool_call_id=row.tool_call_id or "",
        is_error=bool(row.is_error),
        cost_usd=row.cost_usd,
        turn=row.turn,
        created_at=row.created_at,
        metadata=row.metadata_json,
    )
