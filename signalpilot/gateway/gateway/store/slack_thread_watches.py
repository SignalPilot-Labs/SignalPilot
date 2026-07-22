"""Store operations for durable Slack thread watch state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewaySlackThreadWatch


@dataclass(frozen=True)
class SlackThreadWatchInfo:
    id: str
    org_id: str
    team_id: str
    channel_id: str
    thread_ts: str
    source_thread_id: str
    status: str
    invited_by_user_id: str | None
    latest_user_id: str | None
    first_event_ts: str | None
    latest_event_ts: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


async def upsert_thread_watch(
    session: AsyncSession,
    *,
    org_id: str,
    team_id: str,
    channel_id: str,
    thread_ts: str,
    source_thread_id: str,
    user_id: str | None = None,
    event_ts: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SlackThreadWatchInfo:
    row = await _get_thread_watch_row(
        session,
        org_id=org_id,
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )
    if row is None:
        row = GatewaySlackThreadWatch(
            org_id=org_id,
            team_id=team_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            source_thread_id=source_thread_id,
            status="active",
            invited_by_user_id=user_id,
            latest_user_id=user_id,
            first_event_ts=event_ts,
            latest_event_ts=event_ts,
            metadata_json=metadata,
        )
        session.add(row)
    else:
        _update_watch_row(row, source_thread_id=source_thread_id, user_id=user_id, event_ts=event_ts, metadata=metadata)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        row = await _get_thread_watch_row(
            session,
            org_id=org_id,
            team_id=team_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
        if row is None:
            raise
        _update_watch_row(row, source_thread_id=source_thread_id, user_id=user_id, event_ts=event_ts, metadata=metadata)
        await session.commit()

    await session.refresh(row)
    return _to_info(row)


async def active_thread_watch_exists(
    session: AsyncSession,
    *,
    org_id: str,
    team_id: str,
    channel_id: str,
    thread_ts: str,
) -> bool:
    row_id = (
        await session.execute(
            select(GatewaySlackThreadWatch.id)
            .where(
                GatewaySlackThreadWatch.org_id == org_id,
                GatewaySlackThreadWatch.team_id == team_id,
                GatewaySlackThreadWatch.channel_id == channel_id,
                GatewaySlackThreadWatch.thread_ts == thread_ts,
                GatewaySlackThreadWatch.status == "active",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row_id is not None


async def _get_thread_watch_row(
    session: AsyncSession,
    *,
    org_id: str,
    team_id: str,
    channel_id: str,
    thread_ts: str,
) -> GatewaySlackThreadWatch | None:
    return (
        await session.execute(
            select(GatewaySlackThreadWatch).where(
                GatewaySlackThreadWatch.org_id == org_id,
                GatewaySlackThreadWatch.team_id == team_id,
                GatewaySlackThreadWatch.channel_id == channel_id,
                GatewaySlackThreadWatch.thread_ts == thread_ts,
            )
        )
    ).scalar_one_or_none()


def _update_watch_row(
    row: GatewaySlackThreadWatch,
    *,
    source_thread_id: str,
    user_id: str | None,
    event_ts: str | None,
    metadata: dict[str, Any] | None,
) -> None:
    row.source_thread_id = source_thread_id
    row.status = "active"
    if row.invited_by_user_id is None:
        row.invited_by_user_id = user_id
    row.latest_user_id = user_id
    if row.first_event_ts is None:
        row.first_event_ts = event_ts
    row.latest_event_ts = event_ts
    if metadata is not None:
        row.metadata_json = {**(row.metadata_json or {}), **metadata}
    row.updated_at = datetime.now(UTC)


def _to_info(row: GatewaySlackThreadWatch) -> SlackThreadWatchInfo:
    return SlackThreadWatchInfo(
        id=row.id,
        org_id=row.org_id,
        team_id=row.team_id,
        channel_id=row.channel_id,
        thread_ts=row.thread_ts,
        source_thread_id=row.source_thread_id,
        status=row.status,
        invited_by_user_id=row.invited_by_user_id,
        latest_user_id=row.latest_user_id,
        first_event_ts=row.first_event_ts,
        latest_event_ts=row.latest_event_ts,
        metadata=row.metadata_json or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
