"""Apply retention windows and remove orphaned evaluation resources.

Retain artifacts for the last 10 runs in each organization.
Retain traces for the last 100 runs in each organization.
Run finalization enforces retention. The periodic sweeper enforces the same limits.
Do not remove accuracy history.

The reaper removes evaluation branches for inactive runs.
It also removes orphaned task connections.
"""

from __future__ import annotations

import logging

from ..config.evals import get_eval_run_settings
from ..db.engine import get_session_factory
from ..store import Store
from ..store import evals as evals_store
from .branches import run_suffix_of
from .object_store import EvidenceStoreDisabled, get_object_store

logger = logging.getLogger(__name__)


async def enforce_retention(org_id: str) -> dict:
    """Prune this org past the windows. Returns counts for logging/tests."""
    factory = get_session_factory()
    try:
        obj = get_object_store()
    except EvidenceStoreDisabled:
        obj = None

    pruned = {"artifact_runs": 0, "trace_runs": 0, "objects": 0}

    async with factory() as session:
        artifact_victims = await evals_store.runs_outside_window(
            session, org_id=org_id, window=evals_store.ARTIFACT_RUN_WINDOW, flag="artifacts_pruned"
        )
    for run_id in artifact_victims:
        if obj is not None:
            try:
                pruned["objects"] += await obj.delete_prefix(obj.artifacts_prefix(org_id, run_id))
            except Exception:
                logger.exception("artifact prune failed for %s — will retry on next sweep", run_id)
                continue
        async with factory() as session:
            await evals_store.mark_pruned(session, org_id=org_id, run_ids=[run_id], flag="artifacts_pruned")
        pruned["artifact_runs"] += 1

    async with factory() as session:
        trace_victims = await evals_store.runs_outside_window(
            session, org_id=org_id, window=evals_store.TRACE_RUN_WINDOW, flag="traces_pruned"
        )
    for run_id in trace_victims:
        if obj is not None:
            try:
                pruned["objects"] += await obj.delete_prefix(obj.run_prefix(org_id, run_id) + "/")
            except Exception:
                logger.exception("trace prune failed for %s — will retry on next sweep", run_id)
                continue
        async with factory() as session:
            await evals_store.delete_trace_rows(session, org_id=org_id, run_ids=[run_id])
            await evals_store.mark_pruned(session, org_id=org_id, run_ids=[run_id], flag="traces_pruned")
        pruned["trace_runs"] += 1

    return pruned


async def retention_sweep() -> None:
    """Cross-org backstop, called from the lifespan loop."""
    factory = get_session_factory()
    async with factory() as session:
        org_ids = await evals_store.org_ids_with_runs(session)
    for org_id in org_ids:
        try:
            await enforce_retention(org_id)
        except Exception:
            logger.exception("retention sweep failed for org %s", org_id)


async def recover_stale_runs() -> int:
    """Fail runs whose lease expired, revoke their keys, free their resources.

    A gateway that dies mid-run leaves rows in "running" with live
    credentials and live branches. Nothing else notices: the in-process
    `finally` died with the process, and a reaper that treats "running" as
    live would protect those branches forever. Called at startup and on the
    reaper's period.
    """
    from ..db.engine import get_session_factory
    from .runner import revoke_run_keys

    factory = get_session_factory()
    async with factory() as session:
        stale = await evals_store.list_stale_runs(session)
    for run in stale:
        org_id, run_id = run["org_id"], run["id"]
        logger.warning("recovering stale eval run %s (org %s): lease expired", run_id, org_id)
        try:
            await revoke_run_keys(org_id, run_id, run.get("api_key_id"))
        except Exception:
            logger.exception("could not revoke keys for stale run %s", run_id)
        async with factory() as session:
            await evals_store.update_run(
                session,
                org_id=org_id,
                run_id=run_id,
                status="failed",
                error="run did not finish — the gateway executing it stopped responding",
                finished_at=_now_iso(),
                lease_expires_at=None,
            )
    return len(stale)


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


async def reap_orphans() -> dict:
    """Delete eval-* branches (and their per-task connections) whose run is
    not live. Cross-org: branch names carry the run suffix, so ownership is
    resolvable without guessing."""
    settings = get_eval_run_settings()
    factory = get_session_factory()
    reaped = {"branches": 0, "connections": 0}

    async with factory() as session:
        live = await evals_store.list_live_runs(session)
    live_suffixes = {r["id"].rsplit("-", 1)[-1][:6] for r in live}
    live_orgs = {r["org_id"] for r in live}

    # Providers are per-org config; sweep every org that has ever run.
    async with factory() as session:
        org_ids = await evals_store.org_ids_with_runs(session)

    from .provision import ProvisioningError, resolve_branch_provider

    for org_id in org_ids:
        async with factory() as session:
            store = Store(session, org_id=org_id)
            cfg = await evals_store.get_config(session, org_id=org_id)
            try:
                provider = await resolve_branch_provider(store, cfg, settings)
            except ProvisioningError:
                continue

        try:
            branches = await provider.list_eval_branches()
            for branch in branches:
                suffix = run_suffix_of(branch)
                if suffix and suffix in live_suffixes:
                    continue  # The active run owns this branch.
                try:
                    await provider.delete(branch)
                    reaped["branches"] += 1
                    logger.warning("reaped orphan eval branch %s (org %s)", branch, org_id)
                except Exception:
                    logger.exception("could not reap branch %s", branch)
                async with factory() as session:
                    store = Store(session, org_id=org_id)
                    try:
                        if await store.delete_connection(branch[:64]):
                            reaped["connections"] += 1
                    except Exception:
                        pass
        finally:
            await provider.aclose()

        # Connections tagged sp-eval whose branch is gone (fork failed early).
        if org_id not in live_orgs:
            async with factory() as session:
                store = Store(session, org_id=org_id)
                try:
                    conns = await store.list_connections()
                    for c in conns:
                        if "sp-eval" in (getattr(c, "tags", None) or []) and str(
                            getattr(c, "name", "")
                        ).startswith("eval-"):
                            await store.delete_connection(c.name)
                            reaped["connections"] += 1
                except Exception:
                    logger.exception("orphan connection sweep failed for %s", org_id)

    return reaped
