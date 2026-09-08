"""Scheduled refreshes, agent-run polling, and stale-row cleanup.

``run_due_dashboard_refreshes`` claims each due dashboard with a compare-and-
set on ``next_refresh_at``; exactly one replica wins a row. The winners run
concurrently, at most ``MAX_CONCURRENT_REFRESHES`` at a time, and one failure
never stops the others. ``poll_agent_refreshes`` claims each ended agent run
by moving its refresh from ``running`` to ``finalizing`` (again a compare-and-
set) and turns it into a version or a failure. ``fail_stale_refreshes`` fails
rows that a crashed or restarted replica left behind.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayChatRun, GatewayDashboardRefresh, GatewayPublishedDashboard
from gateway.db.models.dashboards import new_refresh_id
from gateway.standalone_chat.domain import TERMINAL_RUN_STATUSES

from . import store
from .refresh import SQL_TIMEOUT_SECONDS, QueryExecutor, fail_refresh, finalize_agent_refresh, run_refresh
from .schedule import compute_next_refresh_at
from .storage import DashboardStorage

logger = logging.getLogger(__name__)

# ── Limits, in one place ────────────────────────────────────────────────────
MAX_CONCURRENT_REFRESHES = 3
# An agent run that has not ended by this point is abandoned.
AGENT_REFRESH_TIMEOUT = timedelta(hours=2)
# A sql-mode refresh runs its datasets one after another, each under the
# query timeout; the sweep budget is that per-dataset time times the dataset
# count (recorded on the row at start) plus a margin.
SQL_DATASET_TIMEOUT = timedelta(seconds=SQL_TIMEOUT_SECONDS)
STALE_MARGIN = timedelta(minutes=5)
# A queued row is picked up within seconds; older than this, nobody will.
QUEUED_REFRESH_TIMEOUT = timedelta(minutes=10)
# Finalizing an agent run is a few object reads and one commit.
FINALIZING_REFRESH_TIMEOUT = timedelta(minutes=10)

IN_PROGRESS_ERROR = "refresh already in progress"
TIMED_OUT_ERROR = "refresh timed out"
NEVER_STARTED_ERROR = "refresh never started"
FINALIZE_INCOMPLETE_ERROR = "finalize did not complete"
AGENT_TIMED_OUT_ERROR = "The agent run did not finish within 2 hours"
RUN_VANISHED_ERROR = "The agent run no longer exists"


# ── Due refreshes ───────────────────────────────────────────────────────────


async def claim_due_dashboard(
    db: AsyncSession,
    dashboard: GatewayPublishedDashboard,
    *,
    now: datetime,
) -> str | None:
    """Claim one due dashboard and record its refresh row.

    Returns the refresh id to execute, or None when another replica won the
    row or the refresh was recorded as skipped.
    """
    seen = store.aware(dashboard.next_refresh_at)
    if seen is None:
        return None
    next_at = compute_next_refresh_at(
        now, dashboard.refresh_interval_minutes, dashboard.refresh_anchor_time, dashboard.refresh_timezone
    )
    if not await store.claim_due(db, dashboard_id=dashboard.id, seen_next=seen, new_next=next_at):
        return None
    await db.refresh(dashboard)
    if await store.active_refresh(db, dashboard.id) is not None:
        await store.create_refresh(
            db,
            dashboard=dashboard,
            refresh_id=new_refresh_id(),
            mode=dashboard.refresh_mode,
            trigger="schedule",
            status="skipped",
            scheduled_for=seen,
            error=IN_PROGRESS_ERROR,
        )
        dashboard.last_refresh_status = "skipped"
        await db.commit()
        return None
    refresh = await store.create_refresh(
        db,
        dashboard=dashboard,
        refresh_id=new_refresh_id(),
        mode=dashboard.refresh_mode,
        trigger="schedule",
        scheduled_for=seen,
    )
    return refresh.id


async def run_due_dashboard_refreshes(
    session_factory: Callable[[], AsyncSession],
    *,
    now_utc: datetime | None = None,
    storage: DashboardStorage | None = None,
    executor: QueryExecutor | None = None,
) -> int:
    """Claim and execute every due refresh. Returns the number executed.

    Claimed refreshes run concurrently under ``MAX_CONCURRENT_REFRESHES``.
    ``run_refresh`` already turns its own crashes into a failed row; anything
    that escapes it is logged and written to the row here, and never stops
    the other refreshes.
    """
    now = now_utc or datetime.now(UTC)
    async with session_factory() as db:
        due = await store.list_due_dashboards(db, now)
        claimed: list[str] = []
        for dashboard in due:
            try:
                refresh_id = await claim_due_dashboard(db, dashboard, now=now)
            except Exception as exc:
                logger.warning("Dashboard %s claim failed: %s", dashboard.id, exc)
                await db.rollback()
                continue
            if refresh_id:
                claimed.append(refresh_id)
    if not claimed:
        return 0
    gate = asyncio.Semaphore(MAX_CONCURRENT_REFRESHES)

    async def run_one(refresh_id: str) -> None:
        async with gate:
            try:
                await run_refresh(session_factory, refresh_id, storage=storage, executor=executor)
            except Exception as exc:
                logger.warning("Dashboard refresh %s failed to run: %s", refresh_id, exc)
                await _fail_by_id(session_factory, refresh_id, f"Refresh crashed: {exc}")

    await asyncio.gather(*(run_one(refresh_id) for refresh_id in claimed))
    return len(claimed)


async def _fail_by_id(session_factory: Callable[[], AsyncSession], refresh_id: str, error: str) -> None:
    """Best-effort failure write on a fresh session, for the crash paths."""
    try:
        async with session_factory() as db:
            refresh = await store.get_refresh(db, refresh_id)
            dashboard = await store.get_dashboard_by_id(db, refresh.dashboard_id) if refresh else None
            if refresh is not None and dashboard is not None and refresh.status in store.ACTIVE_REFRESH_STATUSES:
                await fail_refresh(db, dashboard, refresh, error)
    except Exception as exc:
        logger.warning("Dashboard refresh %s could not be marked failed: %s", refresh_id, exc)


# ── Agent runs ──────────────────────────────────────────────────────────────


def _agent_verdict(refresh: GatewayDashboardRefresh, run: GatewayChatRun | None, *, now: datetime) -> str | None:
    """Why this refresh should be finalized now, or None to keep waiting.

    Returns "" for a terminal run (finalize from its files) and an error
    string when the run vanished or timed out.
    """
    if run is None:
        return RUN_VANISHED_ERROR
    if run.status in TERMINAL_RUN_STATUSES:
        return ""
    if (store.aware(refresh.started_at) or now) + AGENT_REFRESH_TIMEOUT < now:
        return AGENT_TIMED_OUT_ERROR
    return None


async def poll_agent_refreshes(
    session_factory: Callable[[], AsyncSession],
    *,
    now_utc: datetime | None = None,
    storage: DashboardStorage | None = None,
) -> int:
    """Finalize agent-mode refreshes whose chat run has ended. Returns the count.

    Each candidate is claimed with a compare-and-set from ``running`` to
    ``finalizing`` before any work; only the replica that wins proceeds.
    """
    now = now_utc or datetime.now(UTC)
    finalized = 0
    async with session_factory() as db:
        for refresh in await store.list_running_agent_refreshes(db):
            run = await db.get(GatewayChatRun, refresh.run_id) if refresh.run_id else None
            verdict = _agent_verdict(refresh, run, now=now)
            if verdict is None:
                continue
            refresh_id = refresh.id
            claimed = await store.claim_refresh_status(
                db,
                refresh_id=refresh_id,
                seen="running",
                new="finalizing",
                detail={**(refresh.detail or {}), "finalizing_at": now.isoformat()},
            )
            if not claimed:
                continue
            await db.refresh(refresh)
            try:
                if verdict:
                    dashboard = await store.get_dashboard_by_id(db, refresh.dashboard_id)
                    if dashboard is not None:
                        await fail_refresh(db, dashboard, refresh, verdict)
                else:
                    assert run is not None
                    await finalize_agent_refresh(db, refresh, run, storage=storage)
            except Exception as exc:
                logger.warning("Dashboard refresh %s finalize failed: %s", refresh_id, exc)
                await db.rollback()
                # We own the row now; it must not stay "finalizing" forever.
                await _fail_by_id(session_factory, refresh_id, f"Finalize crashed: {exc}")
            finalized += 1
    return finalized


# ── Stale rows ──────────────────────────────────────────────────────────────


def sql_refresh_budget(sql_datasets: int) -> timedelta:
    """How long a sql-mode refresh with this many datasets may stay running."""
    return SQL_DATASET_TIMEOUT * max(1, sql_datasets) + STALE_MARGIN


def _detail(refresh: GatewayDashboardRefresh) -> dict:
    return refresh.detail if isinstance(refresh.detail, dict) else {}


def _detail_time(refresh: GatewayDashboardRefresh, key: str) -> datetime | None:
    value = _detail(refresh).get(key)
    try:
        return store.aware(datetime.fromisoformat(value)) if isinstance(value, str) else None
    except ValueError:
        return None


def stale_error(refresh: GatewayDashboardRefresh, *, now: datetime) -> str | None:
    """The reason this in-progress row can no longer finish, or None."""
    if refresh.status == "queued":
        created = store.aware(refresh.created_at)
        return NEVER_STARTED_ERROR if created and created + QUEUED_REFRESH_TIMEOUT < now else None
    if refresh.status == "running" and refresh.mode == "sql":
        started = store.aware(refresh.started_at)
        budget = sql_refresh_budget(int(_detail(refresh).get("sql_datasets") or 0))
        return TIMED_OUT_ERROR if started and started + budget < now else None
    if refresh.status == "finalizing":
        since = _detail_time(refresh, "finalizing_at") or store.aware(refresh.started_at)
        return FINALIZE_INCOMPLETE_ERROR if since and since + FINALIZING_REFRESH_TIMEOUT < now else None
    return None


async def fail_stale_refreshes(
    session_factory: Callable[[], AsyncSession],
    *,
    now_utc: datetime | None = None,
) -> int:
    """Fail rows a lost replica left behind. Returns the count.

    See ``stale_error`` for the three cases: queued rows nobody picked up,
    sql-mode running rows past their budget, and finalizing rows whose
    finalize never landed. Agent-mode running rows are the poll's business
    (``AGENT_REFRESH_TIMEOUT``).
    """
    now = now_utc or datetime.now(UTC)
    failed = 0
    async with session_factory() as db:
        candidates = (
            await store.list_refreshes_with_status(db, "queued")
            + await store.list_refreshes_with_status(db, "running", mode="sql")
            + await store.list_refreshes_with_status(db, "finalizing")
        )
        stale = [(refresh, error) for refresh in candidates if (error := stale_error(refresh, now=now))]
        for refresh, error in stale:
            refresh_id = refresh.id
            dashboard = await store.get_dashboard_by_id(db, refresh.dashboard_id)
            if dashboard is None:
                continue
            try:
                await fail_refresh(db, dashboard, refresh, error)
            except Exception as exc:
                logger.warning("Dashboard refresh %s could not be marked stale: %s", refresh_id, exc)
                await db.rollback()
                continue
            failed += 1
    return failed


async def run_dashboard_scheduler_tick(session_factory: Callable[[], AsyncSession]) -> tuple[int, int]:
    """One loop tick: due refreshes, then agent-run polling and stale cleanup.

    Returns ``(executed, settled)`` where settled counts finalized agent
    refreshes plus stale rows failed.
    """
    executed = await run_due_dashboard_refreshes(session_factory)
    settled = await poll_agent_refreshes(session_factory)
    settled += await fail_stale_refreshes(session_factory)
    return executed, settled
