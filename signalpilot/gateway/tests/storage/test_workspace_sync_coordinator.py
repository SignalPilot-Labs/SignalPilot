"""Tests for WorkspaceSyncCoordinator."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.storage.local_store import LocalWorkspaceStore
from gateway.storage.workspace_store import SnapshotResult, WorkspaceKey


def _make_key(notebook_id: str = "nb001") -> WorkspaceKey:
    return WorkspaceKey(org_id="org1", user_id="user1", notebook_id=notebook_id)


def _make_coordinator(store, *, interval: int = 1, hydrate_timeout: int = 10, tmp_root: Path):
    from gateway.orchestrator.workspace_sync import WorkspaceSyncCoordinator

    return WorkspaceSyncCoordinator(
        store,
        snapshot_interval=interval,
        hydrate_timeout=hydrate_timeout,
        tmp_root=tmp_root,
    )


class TestHydrateForPod:
    @pytest.mark.asyncio
    async def test_hydrate_cold_start_returns_path(self, tmp_path: Path):
        """hydrate_for_pod returns a temp directory path for a cold start."""
        store = LocalWorkspaceStore(root=tmp_path / "store")
        coord = _make_coordinator(store, tmp_root=tmp_path / "tmp")
        (tmp_path / "tmp").mkdir(exist_ok=True)

        key = _make_key()
        path = await coord.hydrate_for_pod(key)

        assert path.is_dir()


class TestSnapshotForPod:
    @pytest.mark.asyncio
    async def test_snapshot_for_pod_roundtrip(self, tmp_path: Path):
        """snapshot_for_pod + hydrate_for_pod roundtrip works end-to-end."""
        store = LocalWorkspaceStore(root=tmp_path / "store")
        coord = _make_coordinator(store, tmp_root=tmp_path / "tmp")
        (tmp_path / "tmp").mkdir(exist_ok=True)

        key = _make_key()

        async def _pull(dest: Path) -> None:
            (dest / "myfile.txt").write_text("hello")

        result = await coord.snapshot_for_pod(key, _pull)

        assert result.file_count == 1
        assert result.manifest_version

        # Re-hydrate and verify content.
        dest = tmp_path / "dest"
        dest.mkdir()
        hr = await store.hydrate(key, dest)
        assert not hr.cold_start
        assert (dest / "myfile.txt").read_text() == "hello"

    @pytest.mark.asyncio
    async def test_temp_dir_per_tick_is_deleted(self, tmp_path: Path):
        """Coordinator's TemporaryDirectory is deleted after snapshot_for_pod completes."""
        store = LocalWorkspaceStore(root=tmp_path / "store")
        tmp_root = tmp_path / "tmp"
        tmp_root.mkdir()
        coord = _make_coordinator(store, tmp_root=tmp_root)

        key = _make_key()

        async def _pull(dest: Path) -> None:
            (dest / "f.txt").write_text("x")

        await coord.snapshot_for_pod(key, _pull)

        # After snapshot_for_pod, all sp-ws-tick- dirs should be cleaned up.
        leftover = list(tmp_root.glob("sp-ws-tick-*"))
        assert leftover == [], f"Temp dirs not cleaned up: {leftover}"


class TestPeriodicSnapshot:
    @pytest.mark.asyncio
    async def test_periodic_runs_at_interval(self, tmp_path: Path):
        """Periodic snapshot task calls pull at approximately snapshot_interval."""
        store = LocalWorkspaceStore(root=tmp_path / "store")
        tmp_root = tmp_path / "tmp"
        tmp_root.mkdir()
        coord = _make_coordinator(store, interval=1, tmp_root=tmp_root)

        key = _make_key()
        pull_calls: list[Path] = []

        async def _pull(dest: Path) -> None:
            pull_calls.append(dest)
            (dest / "f.txt").write_text("data")

        await coord.start_periodic_snapshot(key=key, session_id="sess-1", pull=_pull)

        await asyncio.sleep(2.5)
        await coord.cancel_periodic_snapshot("sess-1")

        assert len(pull_calls) >= 1, "pull should have been called at least once"

    @pytest.mark.asyncio
    async def test_failure_logged_not_raised(self, tmp_path: Path, caplog):
        """Snapshot failure in periodic task is logged as WARNING, not raised."""
        import logging

        store = LocalWorkspaceStore(root=tmp_path / "store")
        tmp_root = tmp_path / "tmp"
        tmp_root.mkdir()
        coord = _make_coordinator(store, interval=1, tmp_root=tmp_root)

        key = _make_key()

        async def _failing_pull(dest: Path) -> None:
            raise RuntimeError("simulated pull failure")

        with caplog.at_level(logging.WARNING, logger="gateway.orchestrator.workspace_sync"):
            await coord.start_periodic_snapshot(key=key, session_id="sess-fail", pull=_failing_pull)
            await asyncio.sleep(2.5)
            await coord.cancel_periodic_snapshot("sess-fail")

        # Should have warning logs, not raises.
        assert any("fail" in r.message.lower() for r in caplog.records), (
            "Expected a failure warning in logs"
        )

    @pytest.mark.asyncio
    async def test_five_strike_error_log(self, tmp_path: Path, caplog):
        """After MAX_CONSECUTIVE_FAILURES, an ERROR is logged once."""
        import logging

        from gateway.orchestrator.workspace_sync import MAX_CONSECUTIVE_FAILURES

        store = LocalWorkspaceStore(root=tmp_path / "store")
        tmp_root = tmp_path / "tmp"
        tmp_root.mkdir()
        # Very short interval to get many ticks quickly.
        coord = _make_coordinator(store, interval=1, tmp_root=tmp_root)

        key = _make_key()

        async def _failing_pull(dest: Path) -> None:
            raise RuntimeError("persistent failure")

        # Manually drive the tick enough times to hit the threshold.
        coord._failure_counts["sess-5strike"] = 0
        coord._session_keys["sess-5strike"] = key
        coord._session_pulls["sess-5strike"] = _failing_pull

        with caplog.at_level(logging.ERROR, logger="gateway.orchestrator.workspace_sync"):
            for _ in range(MAX_CONSECUTIVE_FAILURES + 1):
                await coord._run_snapshot_tick(
                    session_id="sess-5strike", key=key, pull=_failing_pull
                )

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) >= 1, "Expected at least one ERROR log after 5 consecutive failures"

    @pytest.mark.asyncio
    async def test_cancel_awaits_in_flight_tick(self, tmp_path: Path):
        """cancel_periodic_snapshot awaits in-flight tick before returning."""
        store = LocalWorkspaceStore(root=tmp_path / "store")
        tmp_root = tmp_path / "tmp"
        tmp_root.mkdir()
        coord = _make_coordinator(store, interval=60, tmp_root=tmp_root)

        key = _make_key()
        started = asyncio.Event()
        blocked = asyncio.Event()

        async def _slow_pull(dest: Path) -> None:
            started.set()
            await blocked.wait()
            (dest / "f.txt").write_text("ok")

        # Start with a very short interval so tick fires immediately.
        coord._snapshot_interval = 0.01
        await coord.start_periodic_snapshot(key=key, session_id="sess-cancel", pull=_slow_pull)

        # Wait for tick to start, then cancel while it's in progress.
        await asyncio.wait_for(started.wait(), timeout=2.0)
        blocked.set()

        await coord.cancel_periodic_snapshot("sess-cancel")
        # Should complete without error.

    @pytest.mark.asyncio
    async def test_two_sessions_same_notebook_concurrent_writer_warning(
        self, tmp_path: Path, caplog
    ):
        """Two sessions with same notebook_id: each is independent + WARNING fires."""
        import logging

        store = LocalWorkspaceStore(root=tmp_path / "store")
        tmp_root = tmp_path / "tmp"
        tmp_root.mkdir()
        coord = _make_coordinator(store, interval=60, tmp_root=tmp_root)

        key = _make_key(notebook_id="shared-notebook")

        async def _pull(dest: Path) -> None:
            (dest / "f.txt").write_text("ok")

        with caplog.at_level(logging.WARNING, logger="gateway.orchestrator.workspace_sync"):
            await coord.start_periodic_snapshot(key=key, session_id="sess-A", pull=_pull)
            await coord.start_periodic_snapshot(key=key, session_id="sess-B", pull=_pull)

        # Both tasks registered.
        assert "sess-A" in coord._tasks
        assert "sess-B" in coord._tasks

        # WARNING should have fired for the second registration.
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("concurrent" in m.lower() for m in warning_msgs), (
            f"Expected concurrent-writer warning. Got: {warning_msgs}"
        )

        await coord.cancel_periodic_snapshot("sess-A")
        await coord.cancel_periodic_snapshot("sess-B")


class TestShutdownDrain:
    @pytest.mark.asyncio
    async def test_shutdown_runs_final_snapshot_within_deadline(self, tmp_path: Path):
        """shutdown() runs final snapshot for each session within drain_seconds."""
        store = LocalWorkspaceStore(root=tmp_path / "store")
        tmp_root = tmp_path / "tmp"
        tmp_root.mkdir()
        coord = _make_coordinator(store, interval=60, tmp_root=tmp_root)

        key = _make_key()

        snapshot_called: list[bool] = []

        async def _pull(dest: Path) -> None:
            snapshot_called.append(True)
            (dest / "f.txt").write_text("final")

        await coord.start_periodic_snapshot(key=key, session_id="sess-drain", pull=_pull)
        await coord.shutdown(drain_seconds=5)

        assert snapshot_called, "Final snapshot should have been called during shutdown"
