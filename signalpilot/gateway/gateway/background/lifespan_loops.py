"""Background loops started by the gateway lifespan.

Each loop runs for the life of the process. ``start_background_loops`` creates
the tasks in a fixed order and returns them so the lifespan can cancel them in
the same order on shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import time

from ..connectors.health_monitor import health_monitor
from ..connectors.pool_manager import pool_manager
from ..connectors.schema_cache import schema_cache
from ..db.engine import get_session_factory
from ..governance.context import current_org_id_var
from ..models import ConnectionUpdate
from ..store import Store

logger = logging.getLogger(__name__)


async def _health_flush_loop():
    """Flush buffered health events to DB every 5 seconds."""
    while True:
        await asyncio.sleep(5)
        try:
            await health_monitor.flush_to_db()
        except Exception as e:
            logger.warning("Health flush loop error: %s", e)


async def _health_cleanup_loop():
    """Delete health events older than 7 days, every hour."""
    while True:
        await asyncio.sleep(3600)
        try:
            await health_monitor.cleanup_old_events()
        except Exception as e:
            logger.warning("Health cleanup loop error: %s", e)


async def _health_ping_loop():
    """Ping each connection every 30s to keep health stats fresh."""
    await asyncio.sleep(10)  # Wait for startup to settle
    while True:
        try:
            factory = get_session_factory()
            async with factory() as session:
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
                            logger.debug("Health ping skipped for %s: %s", conn_info.name, e)
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


async def _pool_cleanup_loop():
    while True:
        await asyncio.sleep(60)
        await pool_manager.cleanup_idle()


async def _schema_refresh_loop():
    while True:
        await asyncio.sleep(30)
        try:
            factory = get_session_factory()
            async with factory() as session:
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


async def _notebook_lifecycle_loop():
    """Runtime v2 session lifecycle, every 300 s:

    - extend the execution grant of every session with a fresh ping (the
      provider caps one grant; the loop keeps active sessions alive);
    - flush-by-contract, snapshot, and release compute for idle sessions
      (scale-to-zero — resume happens on the next request);
    - destroy notebook-tagged sandboxes no live session row owns (the
      crashed-gateway backstop the provider time limit only bounds).
    """
    import time as _time

    from ..config.notebooks import get_notebook_settings
    from ..notebooks.backends import VercelNotebookBackend, get_notebook_backend
    from ..notebooks.session_service import snapshot_idle_session
    from ..store import notebook_sessions as ns

    while True:
        await asyncio.sleep(300)
        try:
            settings = get_notebook_settings()
            if settings.resolved_backend() != "vercel":
                continue
            backend = get_notebook_backend(settings)
            factory = get_session_factory()
            async with factory() as session:
                now = _time.time()
                for s in await ns.list_running_internal(session):
                    if not s.runtime_handle:
                        continue
                    idle = now - (s.last_ping or 0)
                    if idle < settings.idle_snapshot_seconds:
                        try:
                            await backend.extend(s.runtime_handle, settings.session_grant_seconds)
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


async def _knowledge_retention_loop():
    """Prune knowledge retrieval events past the retention window.

    BM25 ranks documents during each query. This loop limits event log growth.
    """
    from ..store.knowledge_search import prune_retrieval_events

    await asyncio.sleep(30)
    while True:
        try:
            factory = get_session_factory()
            async with factory() as session:
                pruned = await prune_retrieval_events(session)
                if pruned:
                    logger.info("Pruned %d old knowledge retrieval event(s)", pruned)
        except Exception as e:
            logger.warning("Knowledge retention loop error: %s", e)
        await asyncio.sleep(3600)


async def _schema_watch_loop():
    """Run scheduled schema-difference checks every minute.

    A detected difference can create a GitHub pull request.
    """
    from ..schema_watch.runner import run_due_watches

    while True:
        await asyncio.sleep(60)
        try:
            ran = await run_due_watches(get_session_factory())
            if ran:
                logger.info("Schema watch loop: ran %d watch(es)", ran)
        except Exception as e:
            logger.warning("Schema watch loop error: %s", e)


async def _eval_reaper_loop():
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


async def _eval_retention_loop():
    """Backstop for the on-write retention enforcement, hourly."""
    from ..evals.retention import retention_sweep

    while True:
        await asyncio.sleep(3600)
        try:
            await retention_sweep()
        except Exception as e:
            logger.warning("Eval retention loop error: %s", e)


async def _dbt_map_reaper_loop():
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


async def _improvement_schedule_loop():
    """Seed due daily improvement runs every minute.

    Each enabled org gets at most one system-initiated run per ET day.
    """
    from ..improvements.scheduler import run_due_improvement_runs

    while True:
        await asyncio.sleep(60)
        try:
            ran = await run_due_improvement_runs(get_session_factory())
            if ran:
                logger.info("Improvement schedule loop: processed %d org(s)", ran)
        except Exception as e:
            logger.warning("Improvement schedule loop error: %s", e)


async def _credit_daily_snapshot_loop():
    """Write the model_day / seat_day credit rows once per UTC day."""
    from .loops import credit_daily_snapshot_loop

    await credit_daily_snapshot_loop(get_session_factory())


async def _repo_mirror_reconcile_startup() -> None:
    # Heal any GitHub-linked project whose bare mirror is missing (reset
    # repos volume, failed import clone, container remount) so users never
    # hit "the production branch is not available". One-shot, best-effort,
    # slightly delayed so it never slows startup.
    await asyncio.sleep(15)
    try:
        from ..git.sync import reconcile_all_repo_mirrors

        await reconcile_all_repo_mirrors()
    except Exception as e:
        logger.warning("repo mirror reconcile failed: %s", e)


def start_background_loops() -> list[asyncio.Task]:
    """Create every background task in startup order and return them."""
    return [
        asyncio.create_task(_health_flush_loop()),
        asyncio.create_task(_health_cleanup_loop()),
        asyncio.create_task(_health_ping_loop()),
        asyncio.create_task(_pool_cleanup_loop()),
        asyncio.create_task(_schema_refresh_loop()),
        asyncio.create_task(_notebook_lifecycle_loop()),
        asyncio.create_task(_knowledge_retention_loop()),
        asyncio.create_task(_schema_watch_loop()),
        asyncio.create_task(_eval_reaper_loop()),
        asyncio.create_task(_eval_retention_loop()),
        asyncio.create_task(_improvement_schedule_loop()),
        asyncio.create_task(_credit_daily_snapshot_loop()),
        asyncio.create_task(_dbt_map_reaper_loop()),
        asyncio.create_task(_repo_mirror_reconcile_startup()),
    ]
