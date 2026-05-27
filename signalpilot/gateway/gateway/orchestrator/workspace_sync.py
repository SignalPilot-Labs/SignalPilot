"""WorkspaceSyncCoordinator — manages periodic workspace snapshot tasks.

Coordinates hydrate-on-create and periodic snapshot-on-interval for each
notebook session. The coordinator owns temp directories (S4) and does NOT know
about K8s or FastAPI — it receives a 'pull' callback that does the actual
pod exec (decoupling per §4.9).

Failure handling:
    - Periodic snapshot failure → WARN, no raise, counter++.
    - At MAX_CONSECUTIVE_FAILURES: ERROR logged once, continue.
    - On shutdown: each session gets one final snapshot within drain_seconds.

Concurrent-writer warning (C5 / §4.7):
    If two sessions share the same notebook_id, a WARNING is logged. Each session
    independently follows the atomic manifest protocol — last-writer-wins is the
    only accepted failure mode.

Temp directories are always cleaned up after each tick (S4 / coordinator owns lifecycle).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Awaitable, Callable

from ..storage.workspace_store import SnapshotResult, WorkspaceKey, WorkspaceStore

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 5

_PullCallback = Callable[[Path], Awaitable[None]]


class WorkspaceSyncCoordinator:
    """Manages hydrate + periodic snapshot for notebook sessions."""

    def __init__(
        self,
        store: WorkspaceStore,
        *,
        snapshot_interval: int,
        hydrate_timeout: int,
        tmp_root: Path,
    ) -> None:
        self._store = store
        self._snapshot_interval = snapshot_interval
        self._hydrate_timeout = hydrate_timeout
        self._tmp_root = tmp_root

        # session_id → asyncio.Task
        self._tasks: dict[str, asyncio.Task] = {}
        # session_id → WorkspaceKey (for shutdown)
        self._session_keys: dict[str, WorkspaceKey] = {}
        # session_id → pull callback (for shutdown)
        self._session_pulls: dict[str, _PullCallback] = {}
        # session_id → consecutive failure count
        self._failure_counts: dict[str, int] = {}
        # notebook_id → set of session_ids (concurrent-writer detection)
        self._active_notebook_ids: dict[str, set[str]] = defaultdict(set)
        # session_id → last SnapshotResult (S8)
        self._last_results: dict[str, SnapshotResult] = {}

    async def hydrate_for_pod(self, key: WorkspaceKey) -> Path:
        """Hydrate a workspace from the store into a temp directory.

        Returns the Path to the temp dir. Caller owns the lifecycle until
        snapshot_for_pod or start_periodic_snapshot takes over.

        Raises RuntimeError on non-cold-start hydrate failure (§4.8).
        """
        tmp_dir = Path(tempfile.mkdtemp(prefix="sp-ws-", dir=self._tmp_root))
        try:
            result = await asyncio.wait_for(
                self._store.hydrate(key, tmp_dir),
                timeout=self._hydrate_timeout,
            )
        except asyncio.TimeoutError:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise RuntimeError(
                f"Hydrate timeout ({self._hydrate_timeout}s) for notebook {key.notebook_id}"
            )
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        if result.cold_start:
            logger.info("Cold start hydrate for notebook %s", key.notebook_id)
        else:
            logger.info(
                "Hydrated notebook %s: version=%s, %d files, %d bytes",
                key.notebook_id,
                result.manifest_version,
                result.file_count,
                result.bytes_copied,
            )
        return tmp_dir

    async def snapshot_for_pod(
        self,
        key: WorkspaceKey,
        pull: _PullCallback,
    ) -> SnapshotResult:
        """Run a one-shot snapshot. Coordinator owns the temp dir for this tick."""
        with tempfile.TemporaryDirectory(
            prefix="sp-ws-tick-", dir=self._tmp_root
        ) as tmp_str:
            tmp_dir = Path(tmp_str)
            await pull(tmp_dir)
            result = await self._store.snapshot(key, tmp_dir)
        return result

    async def start_periodic_snapshot(
        self,
        *,
        key: WorkspaceKey,
        session_id: str,
        pull: _PullCallback,
    ) -> None:
        """Start a background periodic snapshot task for session_id.

        Logs WARNING if another session already has the same notebook_id
        (concurrent-writer scenario).
        """
        notebook_id = key.notebook_id
        existing = self._active_notebook_ids.get(notebook_id, set())
        if existing:
            logger.warning(
                "Concurrent session for notebook %s: existing=%r, new=%s",
                notebook_id,
                existing,
                session_id,
            )
        self._active_notebook_ids[notebook_id].add(session_id)
        self._session_keys[session_id] = key
        self._session_pulls[session_id] = pull
        self._failure_counts[session_id] = 0

        task = asyncio.create_task(
            self._periodic_loop(session_id=session_id, key=key, pull=pull),
            name=f"snapshot-{session_id}",
        )
        self._tasks[session_id] = task

    async def cancel_periodic_snapshot(self, session_id: str) -> None:
        """Cancel the periodic snapshot task for session_id. Awaits in-flight tick."""
        task = self._tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        key = self._session_keys.pop(session_id, None)
        if key:
            self._active_notebook_ids[key.notebook_id].discard(session_id)
            if not self._active_notebook_ids[key.notebook_id]:
                del self._active_notebook_ids[key.notebook_id]

        self._session_pulls.pop(session_id, None)
        self._failure_counts.pop(session_id, None)

    async def shutdown(self, drain_seconds: int) -> None:
        """Cancel all periodic tasks; run one final snapshot per session within deadline."""
        session_ids = list(self._tasks.keys())
        for session_id in session_ids:
            task = self._tasks.pop(session_id, None)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Final snapshots — best-effort within drain_seconds.
        if not session_ids:
            return

        async def _drain_one(session_id: str) -> None:
            key = self._session_keys.get(session_id)
            pull = self._session_pulls.get(session_id)
            if not key or not pull:
                return
            try:
                result = await self.snapshot_for_pod(key, pull)
                self._last_results[session_id] = result
                logger.info("Shutdown snapshot complete for session %s", session_id)
            except Exception as exc:
                logger.error(
                    "Shutdown snapshot failed for session %s: %s: %s",
                    session_id,
                    type(exc).__name__,
                    exc,
                )

        try:
            await asyncio.wait_for(
                asyncio.gather(*[_drain_one(sid) for sid in session_ids]),
                timeout=drain_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Shutdown drain timed out after %ds — some snapshots may be incomplete",
                drain_seconds,
            )
        finally:
            # Clean up all session state so the coordinator does not accumulate
            # stale entries if re-used after shutdown (e.g. via lru_cache in tests).
            for session_id in session_ids:
                key = self._session_keys.pop(session_id, None)
                if key:
                    self._active_notebook_ids[key.notebook_id].discard(session_id)
                    if not self._active_notebook_ids[key.notebook_id]:
                        self._active_notebook_ids.pop(key.notebook_id, None)
                self._session_pulls.pop(session_id, None)
                self._failure_counts.pop(session_id, None)

    def last_snapshot_result(self, session_id: str) -> SnapshotResult | None:
        """Return the last SnapshotResult for session_id (S8). None if no snapshot yet."""
        return self._last_results.get(session_id)

    async def _periodic_loop(
        self,
        *,
        session_id: str,
        key: WorkspaceKey,
        pull: _PullCallback,
    ) -> None:
        """Background loop that runs snapshot every snapshot_interval seconds."""
        while True:
            await asyncio.sleep(self._snapshot_interval)
            await self._run_snapshot_tick(session_id=session_id, key=key, pull=pull)

    async def _run_snapshot_tick(
        self,
        *,
        session_id: str,
        key: WorkspaceKey,
        pull: _PullCallback,
    ) -> None:
        """Run one snapshot tick. Logs failures; raises after MAX_CONSECUTIVE_FAILURES."""
        try:
            result = await self.snapshot_for_pod(key, pull)
            self._last_results[session_id] = result
            self._failure_counts[session_id] = 0
            logger.debug(
                "Periodic snapshot for session %s: %d files, %d bytes",
                session_id,
                result.file_count,
                result.bytes_uploaded,
            )
        except Exception as exc:
            count = self._failure_counts.get(session_id, 0) + 1
            self._failure_counts[session_id] = count
            if count >= MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    "Periodic snapshot for session %s: %d consecutive failures "
                    "(last: %s: %s). Continuing.",
                    session_id,
                    count,
                    type(exc).__name__,
                    exc,
                )
            else:
                logger.warning(
                    "Periodic snapshot failed for session %s (attempt %d): %s: %s",
                    session_id,
                    count,
                    type(exc).__name__,
                    exc,
                )


@lru_cache(maxsize=1)
def get_workspace_sync_coordinator() -> WorkspaceSyncCoordinator:
    """Return the global WorkspaceSyncCoordinator singleton."""
    from pathlib import Path

    from ..config.workspace_storage import get_workspace_storage_settings
    from ..storage.factory import get_workspace_store

    settings = get_workspace_storage_settings()
    store = get_workspace_store()
    return WorkspaceSyncCoordinator(
        store,
        snapshot_interval=settings.sp_workspace_snapshot_interval_seconds,
        hydrate_timeout=settings.sp_workspace_hydrate_timeout_seconds,
        tmp_root=Path(settings.effective_tmp_root()),
    )
