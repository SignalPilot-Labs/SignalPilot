"""All database access for published dashboards.

Every function takes an ``AsyncSession`` and commits what it changes, so a
caller sees a consistent row after each call. The one exception is
``create_version``: it only flushes, so the caller can commit the version,
the ``current_version_id`` swap, and its own bookkeeping as one transaction.
Visibility and edit rules live here too; the API and the scheduler both
apply them through this module.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayDashboardRefresh,
    GatewayPublishedDashboard,
    GatewayPublishedDashboardVersion,
)

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# A refresh is in progress from its creation until finish_refresh or
# fail_refresh writes a terminal status. ``finalizing`` is the agent-mode
# window between the chat run ending and the version being written; the
# scheduler claims it with ``claim_refresh_status`` so only one replica
# finalizes a run.
ACTIVE_REFRESH_STATUSES = ("queued", "running", "finalizing")
VERSION_LIST_LIMIT = 50
REFRESH_LIST_LIMIT = 20


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime | None) -> datetime | None:
    """Normalize a stored timestamp to aware UTC (SQLite drops the offset)."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# ── Access rules ────────────────────────────────────────────────────────────


def is_visible(dashboard: GatewayPublishedDashboard, user_id: str) -> bool:
    return dashboard.visibility in ("org", "link") or dashboard.created_by_user_id == user_id


def can_edit(dashboard: GatewayPublishedDashboard, user_id: str, *, is_admin: bool) -> bool:
    return is_admin or dashboard.created_by_user_id == user_id


def new_share_token() -> str:
    """32 url-safe characters."""
    return secrets.token_urlsafe(24)


# ── Slugs ───────────────────────────────────────────────────────────────────


def slugify(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    text = re.sub(r"-{2,}", "-", text)[:64].strip("-")
    return text or "dashboard"


async def unique_slug(
    db: AsyncSession,
    *,
    org_id: str,
    base: str,
    exclude_id: str | None = None,
) -> str:
    """``base``, or ``base-2``, ``base-3``... until unused in the org."""
    taken = set(
        (
            await db.execute(
                select(GatewayPublishedDashboard.slug).where(
                    GatewayPublishedDashboard.org_id == org_id,
                    GatewayPublishedDashboard.id != (exclude_id or ""),
                )
            )
        ).scalars()
    )
    if base not in taken:
        return base
    counter = 2
    while True:
        suffix = f"-{counter}"
        candidate = f"{base[: 64 - len(suffix)].rstrip('-')}{suffix}"
        if candidate not in taken:
            return candidate
        counter += 1


# ── Dashboards ──────────────────────────────────────────────────────────────


async def get_dashboard(db: AsyncSession, *, org_id: str, id_or_slug: str) -> GatewayPublishedDashboard | None:
    return (
        await db.execute(
            select(GatewayPublishedDashboard).where(
                GatewayPublishedDashboard.org_id == org_id,
                or_(GatewayPublishedDashboard.id == id_or_slug, GatewayPublishedDashboard.slug == id_or_slug),
            )
        )
    ).scalar_one_or_none()


async def get_dashboard_by_id(db: AsyncSession, dashboard_id: str) -> GatewayPublishedDashboard | None:
    return await db.get(GatewayPublishedDashboard, dashboard_id)


async def get_dashboard_by_share_token(db: AsyncSession, token: str) -> GatewayPublishedDashboard | None:
    if not token:
        return None
    return (
        await db.execute(
            select(GatewayPublishedDashboard).where(
                GatewayPublishedDashboard.share_token == token,
                GatewayPublishedDashboard.visibility == "link",
                GatewayPublishedDashboard.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def list_dashboards(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    include_archived: bool,
) -> list[GatewayPublishedDashboard]:
    """Dashboards the user can see, newest updated first."""
    query = select(GatewayPublishedDashboard).where(
        GatewayPublishedDashboard.org_id == org_id,
        or_(
            GatewayPublishedDashboard.visibility.in_(("org", "link")),
            GatewayPublishedDashboard.created_by_user_id == user_id,
        ),
    )
    if not include_archived:
        query = query.where(GatewayPublishedDashboard.archived_at.is_(None))
    rows = (await db.execute(query.order_by(GatewayPublishedDashboard.updated_at.desc()))).scalars()
    return list(rows)


async def delete_dashboard(db: AsyncSession, dashboard: GatewayPublishedDashboard) -> None:
    """Delete the row. SQLite does not cascade, so drop children explicitly."""
    dashboard.current_version_id = None
    await db.flush()
    for version in await list_versions(db, dashboard.id, limit=None):
        await db.delete(version)
    for refresh in await list_refreshes(db, dashboard.id, limit=None):
        await db.delete(refresh)
    await db.delete(dashboard)
    await db.commit()


# ── Versions ────────────────────────────────────────────────────────────────


async def next_version_no(db: AsyncSession, dashboard_id: str) -> int:
    rows = (
        await db.execute(
            select(GatewayPublishedDashboardVersion.version_no).where(
                GatewayPublishedDashboardVersion.dashboard_id == dashboard_id
            )
        )
    ).scalars()
    return max(list(rows), default=0) + 1


async def create_version(
    db: AsyncSession,
    *,
    dashboard: GatewayPublishedDashboard,
    version_id: str,
    spec_key: str,
    dataset_keys: dict[str, str],
    dataset_meta: dict[str, dict[str, Any]],
    chart_count: int,
    produced_by: str,
    producer_ref: str | None,
    make_current: bool = True,
) -> GatewayPublishedDashboardVersion:
    """Add the version row and point the dashboard at it. Flushes; the caller commits."""
    version = GatewayPublishedDashboardVersion(
        id=version_id,
        dashboard_id=dashboard.id,
        version_no=await next_version_no(db, dashboard.id),
        spec_key=spec_key,
        dataset_keys=dataset_keys,
        dataset_meta=dataset_meta,
        chart_count=chart_count,
        produced_by=produced_by,
        producer_ref=producer_ref,
    )
    db.add(version)
    await db.flush()
    if make_current:
        dashboard.current_version_id = version.id
        dashboard.chart_count = chart_count
        dashboard.updated_at = utcnow()
    await db.flush()
    return version


async def get_version(
    db: AsyncSession, *, dashboard_id: str, version_id: str
) -> GatewayPublishedDashboardVersion | None:
    return (
        await db.execute(
            select(GatewayPublishedDashboardVersion).where(
                GatewayPublishedDashboardVersion.id == version_id,
                GatewayPublishedDashboardVersion.dashboard_id == dashboard_id,
            )
        )
    ).scalar_one_or_none()


async def current_version(
    db: AsyncSession, dashboard: GatewayPublishedDashboard
) -> GatewayPublishedDashboardVersion | None:
    if not dashboard.current_version_id:
        return None
    return await get_version(db, dashboard_id=dashboard.id, version_id=dashboard.current_version_id)


async def list_versions(
    db: AsyncSession, dashboard_id: str, *, limit: int | None = VERSION_LIST_LIMIT
) -> list[GatewayPublishedDashboardVersion]:
    query = (
        select(GatewayPublishedDashboardVersion)
        .where(GatewayPublishedDashboardVersion.dashboard_id == dashboard_id)
        .order_by(GatewayPublishedDashboardVersion.version_no.desc())
    )
    if limit:
        query = query.limit(limit)
    return list((await db.execute(query)).scalars())


async def version_numbers(db: AsyncSession, version_ids: list[str]) -> dict[str, int]:
    """{version id: version_no} for the given ids, in one query."""
    ids = [value for value in version_ids if value]
    if not ids:
        return {}
    rows = await db.execute(
        select(GatewayPublishedDashboardVersion.id, GatewayPublishedDashboardVersion.version_no).where(
            GatewayPublishedDashboardVersion.id.in_(ids)
        )
    )
    return {row[0]: int(row[1]) for row in rows}


# ── Refreshes ───────────────────────────────────────────────────────────────


async def active_refresh(db: AsyncSession, dashboard_id: str) -> GatewayDashboardRefresh | None:
    return (
        await db.execute(
            select(GatewayDashboardRefresh)
            .where(
                GatewayDashboardRefresh.dashboard_id == dashboard_id,
                GatewayDashboardRefresh.status.in_(ACTIVE_REFRESH_STATUSES),
            )
            .order_by(GatewayDashboardRefresh.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def create_refresh(
    db: AsyncSession,
    *,
    dashboard: GatewayPublishedDashboard,
    refresh_id: str,
    mode: str,
    trigger: str,
    status: str = "queued",
    scheduled_for: datetime | None = None,
    error: str | None = None,
    detail: dict[str, Any] | None = None,
) -> GatewayDashboardRefresh:
    refresh = GatewayDashboardRefresh(
        id=refresh_id,
        dashboard_id=dashboard.id,
        org_id=dashboard.org_id,
        mode=mode,
        trigger=trigger,
        status=status,
        scheduled_for=scheduled_for,
        error=error,
        detail=detail,
        finished_at=utcnow() if status in ("skipped", "failed") else None,
    )
    db.add(refresh)
    await db.commit()
    return refresh


async def get_refresh(db: AsyncSession, refresh_id: str) -> GatewayDashboardRefresh | None:
    return await db.get(GatewayDashboardRefresh, refresh_id)


async def list_refreshes(
    db: AsyncSession, dashboard_id: str, *, limit: int | None = REFRESH_LIST_LIMIT
) -> list[GatewayDashboardRefresh]:
    query = (
        select(GatewayDashboardRefresh)
        .where(GatewayDashboardRefresh.dashboard_id == dashboard_id)
        .order_by(GatewayDashboardRefresh.created_at.desc(), GatewayDashboardRefresh.id.desc())
    )
    if limit:
        query = query.limit(limit)
    return list((await db.execute(query)).scalars())


async def list_running_agent_refreshes(db: AsyncSession) -> list[GatewayDashboardRefresh]:
    return list(
        (
            await db.execute(
                select(GatewayDashboardRefresh).where(
                    GatewayDashboardRefresh.mode == "agent",
                    GatewayDashboardRefresh.status == "running",
                    GatewayDashboardRefresh.run_id.is_not(None),
                )
            )
        ).scalars()
    )


async def list_refreshes_with_status(
    db: AsyncSession, status: str, *, mode: str | None = None
) -> list[GatewayDashboardRefresh]:
    """Every refresh in ``status`` (a small set: only in-progress rows are queried)."""
    query = select(GatewayDashboardRefresh).where(GatewayDashboardRefresh.status == status)
    if mode is not None:
        query = query.where(GatewayDashboardRefresh.mode == mode)
    return list((await db.execute(query)).scalars())


async def claim_refresh_status(
    db: AsyncSession,
    *,
    refresh_id: str,
    seen: str,
    new: str,
    detail: dict[str, Any] | None = None,
) -> bool:
    """Move a refresh from ``seen`` to ``new`` only if it is still in ``seen``.

    Exactly one replica wins the row; the others see rowcount 0. Mirrors
    ``claim_due``. ``detail`` replaces the row's detail in the same statement.
    """
    values: dict[str, Any] = {"status": new}
    if detail is not None:
        values["detail"] = detail
    result = await db.execute(
        update(GatewayDashboardRefresh)
        .where(GatewayDashboardRefresh.id == refresh_id, GatewayDashboardRefresh.status == seen)
        .values(**values)
    )
    await db.commit()
    return bool(result.rowcount)


async def settle_refresh(db: AsyncSession, refresh_id: str, status: str) -> bool:
    """Compare-and-set the row from any in-progress status to a terminal one.

    Not committed: the caller commits the terminal status together with the
    rest of the outcome, or rolls everything back when it lost the row.
    """
    result = await db.execute(
        update(GatewayDashboardRefresh)
        .where(
            GatewayDashboardRefresh.id == refresh_id,
            GatewayDashboardRefresh.status.in_(ACTIVE_REFRESH_STATUSES),
        )
        .values(status=status)
    )
    return bool(result.rowcount)


# ── Scheduling ──────────────────────────────────────────────────────────────


async def list_due_dashboards(db: AsyncSession, now: datetime) -> list[GatewayPublishedDashboard]:
    return list(
        (
            await db.execute(
                select(GatewayPublishedDashboard).where(
                    GatewayPublishedDashboard.archived_at.is_(None),
                    GatewayPublishedDashboard.refresh_interval_minutes.is_not(None),
                    GatewayPublishedDashboard.next_refresh_at.is_not(None),
                    GatewayPublishedDashboard.next_refresh_at <= now,
                )
            )
        ).scalars()
    )


async def claim_due(
    db: AsyncSession,
    *,
    dashboard_id: str,
    seen_next: datetime,
    new_next: datetime | None,
) -> bool:
    """Advance next_refresh_at only if it still equals the value we saw.

    Exactly one replica wins the row; the others see rowcount 0.
    """
    result = await db.execute(
        update(GatewayPublishedDashboard)
        .where(
            GatewayPublishedDashboard.id == dashboard_id,
            GatewayPublishedDashboard.next_refresh_at == seen_next,
        )
        .values(next_refresh_at=new_next)
    )
    await db.commit()
    return bool(result.rowcount)
