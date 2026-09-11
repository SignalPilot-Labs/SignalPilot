"""Long-running background coroutines started by the gateway lifespan.

Each loop is a top-level ``async def`` that receives its dependencies as
parameters. ``start_background_tasks`` schedules every loop and
``cancel_background_tasks`` cancels them during shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..connectors.health_monitor import health_monitor
from ..connectors.pool_manager import pool_manager
from ..connectors.schema_cache import schema_cache
from ..governance.context import current_org_id_var
from ..models import ConnectionUpdate
from ..store import Store

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..config.notebooks import NotebookSettings

    SessionFactory = async_sessionmaker[AsyncSession]
else:
    SessionFactory = Any

logger = logging.getLogger(__name__)


async def health_flush_loop() -> None:
    """Flush buffered health events to DB every 5 seconds."""
    while True:
        await asyncio.sleep(5)
        try:
            await health_monitor.flush_to_db()
        except Exception as e:
            logger.warning("Health flush loop error: %s", e)


async def health_cleanup_loop() -> None:
    """Delete health events older than 7 days, every hour."""
    while True:
        await asyncio.sleep(3600)
        try:
            await health_monitor.cleanup_old_events()
        except Exception as e:
            logger.warning("Health cleanup loop error: %s", e)


async def health_ping_loop(session_factory: SessionFactory) -> None:
    """Ping each connection every 30s to keep health stats fresh."""
    await asyncio.sleep(10)  # Wait for startup to settle
    while True:
        try:
            async with session_factory() as session:
                store = Store(session, allow_unscoped=True)
                connections = await store.list_connections()
                for conn_info in connections:
                    token = current_org_id_var.set(conn_info.org_id)
                    try:
                        inner_store = Store(session, org_id=conn_info.org_id)
                        # A single row with undecryptable credentials must
                        # not abort the sweep for every other connection.
                        try:
                            conn_str = await inner_store.get_connection_string(conn_info.name)
                            extras = await inner_store.get_credential_extras(conn_info.name)
                        except Exception as e:
                            logger.debug(
                                "Health ping skipped for %s: %s", conn_info.name, e
                            )
                            continue
                        if not conn_str:
                            continue
                        start = time.monotonic()
                        try:
                            async with pool_manager.connection(
                                conn_info.db_type,
                                conn_str,
                                credential_extras=extras,
                                connection_name=conn_info.name,
                            ) as connector:
                                ok = await connector.health_check()
                            elapsed = (time.monotonic() - start) * 1000
                            health_monitor.record(
                                conn_info.name,
                                elapsed,
                                ok,
                                error=None if ok else "health_check returned false",
                                db_type=conn_info.db_type,
                            )
                        except Exception as e:
                            elapsed = (time.monotonic() - start) * 1000
                            health_monitor.record(
                                conn_info.name,
                                elapsed,
                                False,
                                error=str(e)[:200],
                                db_type=conn_info.db_type,
                            )
                    finally:
                        current_org_id_var.reset(token)
        except Exception as e:
            logger.warning("Health ping loop error: %s", e)
        await asyncio.sleep(30)


async def pool_cleanup_loop() -> None:
    """Close idle pooled connections every minute."""
    while True:
        await asyncio.sleep(60)
        await pool_manager.cleanup_idle()


async def schema_refresh_loop(session_factory: SessionFactory) -> None:
    """Refresh cached schemas for connections whose refresh interval elapsed."""
    while True:
        await asyncio.sleep(30)
        try:
            async with session_factory() as session:
                store = Store(session, allow_unscoped=True)  # Background task: needs cross-user access
                connections = await store.list_connections()
                now = time.time()
                for conn_info in connections:
                    interval = conn_info.schema_refresh_interval
                    if not interval:
                        continue
                    last_refresh = conn_info.last_schema_refresh or 0
                    if now - last_refresh < interval:
                        continue
                    # Outer Store is allow_unscoped; construct a per-org inner Store
                    # so get_connection_string, get_credential_extras, and update_connection
                    # are correctly scoped and update_connection's WHERE clause matches.
                    token = current_org_id_var.set(conn_info.org_id)
                    try:
                        inner_store = Store(session, org_id=conn_info.org_id)
                        conn_str = await inner_store.get_connection_string(conn_info.name)
                        if not conn_str:
                            continue
                        extras = await inner_store.get_credential_extras(conn_info.name)
                        async with pool_manager.connection(
                            conn_info.db_type,
                            conn_str,
                            credential_extras=extras,
                            connection_name=conn_info.name,
                        ) as connector:
                            schema = await connector.get_schema()
                        diff_result = schema_cache.put(conn_info.name, schema, track_diff=True)
                        await inner_store.update_connection(
                            conn_info.name,
                            ConnectionUpdate(
                                last_schema_refresh=now,
                            ),
                        )
                        if diff_result and diff_result.get("has_changes"):
                            added = len(diff_result.get("added_tables", []))
                            removed = len(diff_result.get("removed_tables", []))
                            modified = len(diff_result.get("modified_tables", []))
                            logger.info(
                                "Schema change detected for '%s': +%d/-%d tables, %d modified",
                                conn_info.name,
                                added,
                                removed,
                                modified,
                            )
                        else:
                            logger.info(
                                "Scheduled schema refresh for '%s': %d tables (no structural changes)",
                                conn_info.name,
                                len(schema),
                            )
                    except Exception as e:
                        logger.warning(
                            "Scheduled schema refresh failed for '%s': %s",
                            conn_info.name,
                            e,
                        )
                    finally:
                        current_org_id_var.reset(token)
        except Exception as e:
            logger.warning("Schema refresh loop error: %s", e)


async def notebook_lifecycle_loop(
    session_factory: SessionFactory,
    get_settings: Callable[[], NotebookSettings] | None = None,
) -> None:
    """Runtime v2 session lifecycle, every 300 s:

    - extend the execution grant of every session with a fresh ping (the
      provider caps one grant; the loop keeps active sessions alive);
    - flush-by-contract, snapshot, and release compute for idle sessions
      (scale-to-zero — resume happens on the next request);
    - destroy notebook-tagged sandboxes no live session row owns (the
      crashed-gateway backstop the provider time limit only bounds).
    """
    from ..config.notebooks import get_notebook_settings
    from ..notebooks.backends import VercelNotebookBackend, get_notebook_backend
    from ..notebooks.session_service import snapshot_idle_session
    from ..store import notebook_sessions as ns

    if get_settings is None:
        get_settings = get_notebook_settings

    while True:
        await asyncio.sleep(300)
        try:
            settings = get_settings()
            if settings.resolved_backend() != "vercel":
                continue
            backend = get_notebook_backend(settings)
            async with session_factory() as session:
                now = time.time()
                for s in await ns.list_running_internal(session):
                    if not s.runtime_handle:
                        continue
                    idle = now - (s.last_ping or 0)
                    if idle < settings.idle_snapshot_seconds:
                        try:
                            await backend.extend(
                                s.runtime_handle, settings.session_grant_seconds
                            )
                            await ns.update_session_runtime(
                                session,
                                session_id=s.session_id,
                                org_id=s.org_id,
                                last_extend_at=now,
                            )
                        except Exception:
                            logger.warning(
                                "Extend failed for session %s; snapshot backstop applies",
                                s.session_id,
                                exc_info=True,
                            )
                    else:
                        logger.info(
                            "Snapshotting idle notebook session %s (idle %.0fs)",
                            s.session_id,
                            idle,
                        )
                        await snapshot_idle_session(session, internal=s, backend=backend)
                if isinstance(backend, VercelNotebookBackend):
                    keep = await ns.live_runtime_handles(session)
                    reaped = await backend.reap_orphans(keep)
                    if reaped:
                        logger.info("Notebook sandbox reaper: destroyed %d orphan(s)", reaped)
        except Exception as e:
            logger.warning("Notebook lifecycle loop error: %s", e)


async def knowledge_retention_loop(session_factory: SessionFactory) -> None:
    """Prune knowledge retrieval events past the retention window.

    BM25 ranks documents during each query. This loop limits event log growth.
    """
    from ..store.knowledge_search import prune_retrieval_events

    await asyncio.sleep(30)
    while True:
        try:
            async with session_factory() as session:
                pruned = await prune_retrieval_events(session)
                if pruned:
                    logger.info("Pruned %d old knowledge retrieval event(s)", pruned)
        except Exception as e:
            logger.warning("Knowledge retention loop error: %s", e)
        await asyncio.sleep(3600)


async def schema_watch_loop(session_factory: SessionFactory) -> None:
    """Run scheduled schema-difference checks every minute.

    A detected difference can create a GitHub pull request.
    """
    from ..schema_watch.runner import run_due_watches

    while True:
        await asyncio.sleep(60)
        try:
            ran = await run_due_watches(session_factory)
            if ran:
                logger.info("Schema watch loop: ran %d watch(es)", ran)
        except Exception as e:
            logger.warning("Schema watch loop error: %s", e)


async def eval_reaper_loop() -> None:
    """Recover stale runs and remove orphaned eval branches every two minutes.

    Recovery marks stale runs before the reaper checks their branches.
    """
    from ..evals.retention import reap_orphans, recover_stale_runs

    # A run from an earlier process cannot continue in this process.
    try:
        recovered = await recover_stale_runs()
        if recovered:
            logger.warning("Eval startup recovery: failed %d stale run(s)", recovered)
    except Exception as e:
        logger.warning("Eval startup recovery error: %s", e)

    while True:
        await asyncio.sleep(120)
        try:
            await recover_stale_runs()
            reaped = await reap_orphans()
            if reaped["branches"] or reaped["connections"]:
                logger.warning("Eval reaper: %s", reaped)
        except Exception as e:
            logger.warning("Eval reaper loop error: %s", e)


async def eval_retention_loop() -> None:
    """Backstop for the on-write retention enforcement, hourly."""
    from ..evals.retention import retention_sweep

    while True:
        await asyncio.sleep(3600)
        try:
            await retention_sweep()
        except Exception as e:
            logger.warning("Eval retention loop error: %s", e)


async def dbt_map_reaper_loop() -> None:
    """Fail dbt-map compiles whose lease died with a previous process."""
    from ..dbt_map.runner import reap_stale_compiles

    while True:
        await asyncio.sleep(120)
        try:
            reaped = await reap_stale_compiles()
            if reaped:
                logger.warning("dbt-map reaper: failed %d stale compile(s)", reaped)
        except Exception as e:
            logger.warning("dbt-map reaper loop error: %s", e)


async def improvement_schedule_loop(session_factory: SessionFactory) -> None:
    """Seed due daily improvement runs every minute.

    Each enabled org gets at most one system-initiated run per ET day.
    """
    from ..improvements.scheduler import run_due_improvement_runs

    while True:
        await asyncio.sleep(60)
        try:
            ran = await run_due_improvement_runs(session_factory)
            if ran:
                logger.info("Improvement schedule loop: processed %d org(s)", ran)
        except Exception as e:
            logger.warning("Improvement schedule loop error: %s", e)


async def dashboard_refresh_loop(session_factory: SessionFactory) -> None:
    """Run due dashboard refreshes, finalize agent refreshes, and fail
    stale rows every minute.

    Compare-and-sets on next_refresh_at and on the refresh status make the
    claims replica-safe.
    """
    from ..dashboards.scheduler import run_dashboard_scheduler_tick

    while True:
        await asyncio.sleep(60)
        try:
            executed, settled = await run_dashboard_scheduler_tick(session_factory)
            if executed or settled:
                logger.info("Dashboard refresh loop: executed %d, settled %d", executed, settled)
        except Exception as e:
            logger.warning("Dashboard refresh loop error: %s", e)


async def repo_mirror_reconcile_startup() -> None:
    """One-shot: heal GitHub-linked projects whose bare mirror is missing.

    Covers a reset repos volume, a failed import clone, or a container
    remount so users never hit "the production branch is not available".
    Best-effort and slightly delayed so it never slows startup.
    """
    await asyncio.sleep(15)
    try:
        from ..git.sync import reconcile_all_repo_mirrors

        await reconcile_all_repo_mirrors()
    except Exception as e:
        logger.warning("repo mirror reconcile failed: %s", e)


# Task registry.

BACKGROUND_TASK_NAMES: tuple[str, ...] = (
    "health_flush",
    "health_cleanup",
    "health_ping",
    "pool_cleanup",
    "schema_refresh",
    "notebook_lifecycle",
    "knowledge_retention",
    "schema_watch",
    "eval_reaper",
    "eval_retention",
    "improvement_schedule",
    "dbt_map_reaper",
    "dashboard_refresh",
    "repo_mirror_reconcile",
)


def start_background_tasks(
    session_factory: SessionFactory,
    *,
    get_notebook_settings: Callable[[], NotebookSettings] | None = None,
) -> list[asyncio.Task[None]]:
    """Schedule every background loop and return the tasks in registry order."""
    coroutines = (
        health_flush_loop(),
        health_cleanup_loop(),
        health_ping_loop(session_factory),
        pool_cleanup_loop(),
        schema_refresh_loop(session_factory),
        notebook_lifecycle_loop(session_factory, get_notebook_settings),
        knowledge_retention_loop(session_factory),
        schema_watch_loop(session_factory),
        eval_reaper_loop(),
        eval_retention_loop(),
        improvement_schedule_loop(session_factory),
        dbt_map_reaper_loop(),
        dashboard_refresh_loop(session_factory),
        repo_mirror_reconcile_startup(),
    )
    return [
        asyncio.create_task(coro, name=name)
        for name, coro in zip(BACKGROUND_TASK_NAMES, coroutines, strict=True)
    ]


async def cancel_background_tasks(tasks: list[asyncio.Task[None]]) -> None:
    """Cancel every task and wait until each one has actually stopped."""
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
