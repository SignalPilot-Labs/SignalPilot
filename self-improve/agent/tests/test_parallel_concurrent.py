"""Tests for concurrent parallel run scenarios.

Verifies that the RunManager correctly handles multiple simultaneous agent
runs — the core of the parallel runner feature.
"""

import asyncio
import time
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from httpx import ASGITransport

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent.run_manager import RunManager, RunSlot, MAX_CONCURRENT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_docker_inspect():
    """Return minimal docker inspect JSON for environment detection."""
    import json
    return json.dumps([{
        "Config": {"Image": "test-image:latest"},
        "NetworkSettings": {"Networks": {"test-net": {}}},
        "Mounts": [
            {"Source": "/data", "Destination": "/data", "Mode": "rw"},
            {"Source": "/host/repo", "Destination": "/home/agentuser/repo", "Mode": "rw"},
        ],
    }])


def _mock_run_docker(args, timeout=30):
    """Mock docker CLI calls for testing."""
    cmd = args[0]
    if cmd == "inspect":
        if "--format" in args:
            return "running"
        return _mock_docker_inspect()
    if cmd == "run":
        return "abc123def456"
    if cmd in ("stop", "rm", "volume"):
        return ""
    return ""


CREDS = {"claude_token": "test", "git_token": "test", "github_repo": "test/repo"}


# ---------------------------------------------------------------------------
# RunManager concurrent slot tests
# ---------------------------------------------------------------------------


class TestConcurrentSlots:
    """Test multiple slots being managed simultaneously."""

    def test_multiple_slots_tracked(self):
        """RunManager tracks multiple slots independently."""
        mgr = RunManager()
        for i in range(5):
            slot = RunSlot(
                container_name=f"worker-{i}",
                status="running",
                run_id=f"run-{i}",
                prompt=f"task {i}",
                base_branch="main",
            )
            mgr.slots[slot.container_name] = slot

        assert len(mgr.get_all_slots()) == 5
        assert mgr.active_count() == 5

        # Each slot is independently accessible
        for i in range(5):
            s = mgr.get_slot_by_run_id(f"run-{i}")
            assert s is not None
            assert s.prompt == f"task {i}"

    def test_mixed_status_counting(self):
        """active_count only includes starting/running slots."""
        mgr = RunManager()
        statuses = ["running", "running", "completed", "stopped", "error", "starting"]
        for i, status in enumerate(statuses):
            mgr.slots[f"w-{i}"] = RunSlot(
                container_name=f"w-{i}", status=status, run_id=f"r-{i}"
            )

        assert mgr.active_count() == 3  # 2 running + 1 starting
        assert len(mgr.get_all_slots()) == 6

    def test_cleanup_only_removes_finished(self):
        """cleanup_all_finished leaves active runs untouched."""
        mgr = RunManager()
        mgr._run_docker = _mock_run_docker

        mgr.slots["active"] = RunSlot(container_name="active", status="running")
        mgr.slots["done1"] = RunSlot(container_name="done1", status="completed")
        mgr.slots["done2"] = RunSlot(container_name="done2", status="stopped")
        mgr.slots["err"] = RunSlot(container_name="err", status="error")

        cleaned = mgr.cleanup_all_finished()
        assert cleaned == 3
        assert len(mgr.slots) == 1
        assert "active" in mgr.slots

    def test_slot_isolation_by_container_name(self):
        """Each slot is keyed by container name — no collisions."""
        mgr = RunManager()
        s1 = RunSlot(container_name="w-aaa", status="running", run_id="r-1", prompt="task A")
        s2 = RunSlot(container_name="w-bbb", status="running", run_id="r-2", prompt="task B")
        mgr.slots["w-aaa"] = s1
        mgr.slots["w-bbb"] = s2

        assert mgr.get_slot("w-aaa").prompt == "task A"
        assert mgr.get_slot("w-bbb").prompt == "task B"
        assert mgr.get_slot("w-ccc") is None


class TestConcurrentStartRuns:
    """Test starting multiple runs concurrently via the RunManager."""

    @pytest.mark.asyncio
    async def test_concurrent_start_three_runs(self):
        """Three concurrent start_run calls should all succeed (below limit)."""
        mgr = RunManager()
        mgr._run_docker = _mock_run_docker

        async def mock_health(container_name, timeout=120):
            pass  # Instant health check

        mgr._wait_for_health = mock_health

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        call_count = 0

        async def mock_post(url, json=None):
            nonlocal call_count
            call_count += 1
            mock_resp.json.return_value = {"run_id": f"run-{call_count}"}
            return mock_resp

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            # Start 3 runs concurrently
            results = await asyncio.gather(
                mgr.start_run("task 1", 10.0, 30, "main", CREDS),
                mgr.start_run("task 2", 10.0, 30, "main", CREDS),
                mgr.start_run("task 3", 10.0, 30, "main", CREDS),
            )

        assert len(results) == 3
        assert mgr.active_count() == 3
        # Each slot has a unique container name
        names = [s.container_name for s in mgr.get_all_slots()]
        assert len(set(names)) == 3

    @pytest.mark.asyncio
    async def test_max_concurrent_enforced_on_parallel_start(self):
        """Cannot exceed MAX_CONCURRENT when starting runs."""
        mgr = RunManager()
        mgr._run_docker = _mock_run_docker

        # Pre-fill to MAX_CONCURRENT
        for i in range(MAX_CONCURRENT):
            mgr.slots[f"pre-{i}"] = RunSlot(
                container_name=f"pre-{i}", status="running"
            )

        with pytest.raises(RuntimeError, match="Max concurrent"):
            await mgr.start_run("overflow", 10.0, 30, "main", CREDS)

    @pytest.mark.asyncio
    async def test_start_after_cleanup_succeeds(self):
        """After cleaning up finished runs, new ones can start."""
        mgr = RunManager()
        mgr._run_docker = _mock_run_docker

        # Fill to max with completed runs
        for i in range(MAX_CONCURRENT):
            mgr.slots[f"done-{i}"] = RunSlot(
                container_name=f"done-{i}", status="completed"
            )

        # All slots are finished so active=0
        assert mgr.active_count() == 0

        # Cleanup
        mgr.cleanup_all_finished()
        assert len(mgr.slots) == 0

        # Should be able to start a new run
        mgr._wait_for_health = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"run_id": "new-1"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            slot = await mgr.start_run("fresh start", 5.0, 60, "main", CREDS)

        assert slot.status == "running"
        assert mgr.active_count() == 1


class TestConcurrentSignals:
    """Test sending signals to multiple concurrent runs."""

    @pytest.mark.asyncio
    async def test_stop_specific_run_among_many(self):
        """Stopping one run doesn't affect others."""
        mgr = RunManager()
        for i in range(3):
            mgr.slots[f"w-{i}"] = RunSlot(
                container_name=f"w-{i}", status="running", run_id=f"r-{i}"
            )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await mgr.stop_run("w-1", "test stop")

        assert mgr.slots["w-0"].status == "running"
        assert mgr.slots["w-1"].status == "stopped"
        assert mgr.slots["w-2"].status == "running"
        assert mgr.active_count() == 2

    @pytest.mark.asyncio
    async def test_kill_one_cleans_up_only_that_container(self):
        """Killing one run cleans up only its container."""
        mgr = RunManager()
        docker_calls = []

        def mock_docker(args, timeout=30):
            docker_calls.append(args)
            return _mock_run_docker(args, timeout)

        mgr._run_docker = mock_docker

        for i in range(3):
            mgr.slots[f"w-{i}"] = RunSlot(
                container_name=f"w-{i}", status="running", run_id=f"r-{i}"
            )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await mgr.kill_run("w-1")

        assert mgr.slots["w-1"].status == "killed"
        assert mgr.slots["w-0"].status == "running"
        assert mgr.slots["w-2"].status == "running"

        # Docker stop/rm was called for w-1
        stop_calls = [c for c in docker_calls if c[0] == "stop"]
        rm_calls = [c for c in docker_calls if c[0] == "rm"]
        assert any("w-1" in c for c in stop_calls)
        assert any("w-1" in c for c in rm_calls)

    @pytest.mark.asyncio
    async def test_parallel_signals_to_multiple_runs(self):
        """Sending different signals to different runs concurrently."""
        mgr = RunManager()
        for i in range(4):
            mgr.slots[f"w-{i}"] = RunSlot(
                container_name=f"w-{i}", status="running", run_id=f"r-{i}"
            )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await asyncio.gather(
                mgr.pause_run("w-0"),
                mgr.send_signal("w-1", "inject", {"payload": "focus on tests"}),
                mgr.unlock_run("w-2"),
                mgr.resume_run("w-3"),
            )

        assert len(results) == 4
        assert all(r.get("ok") for r in results)


class TestConcurrentAPIEndpoints:
    """Test the FastAPI endpoints with concurrent requests."""

    @pytest_asyncio.fixture
    async def client(self):
        with patch("agent.db.init_db", new_callable=AsyncMock), \
             patch("agent.db.close_db", new_callable=AsyncMock), \
             patch("agent.db.mark_crashed_runs", new_callable=AsyncMock, return_value=0):
            from agent.main import app
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac

    @pytest.mark.asyncio
    async def test_concurrent_status_and_list_requests(self, client):
        """Multiple status/list requests can be served concurrently."""
        with patch("agent.main._run_manager") as mock_mgr:
            mock_mgr.get_all_slots.return_value = []
            mock_mgr.active_count.return_value = 0

            results = await asyncio.gather(
                client.get("/parallel/status"),
                client.get("/parallel/runs"),
                client.get("/parallel/status"),
            )

        assert all(r.status_code == 200 for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_start_requests_limited(self, client):
        """Concurrent start requests that exceed limit get 409."""
        call_count = 0

        async def mock_start(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > MAX_CONCURRENT:
                raise RuntimeError(f"[run_manager] Max concurrent runs ({MAX_CONCURRENT}) reached")
            return RunSlot(
                container_name=f"w-{call_count}",
                status="running",
                run_id=f"r-{call_count}",
            )

        with patch("agent.main._run_manager") as mock_mgr:
            mock_mgr.start_run = mock_start

            with patch("agent.run_manager.RunManager.to_dict", return_value={
                "run_id": "test", "container_name": "test",
                "status": "running", "container_id": "",
                "prompt": None, "max_budget_usd": 0,
                "duration_minutes": 0, "base_branch": "main",
                "started_at": time.time(), "error_message": None,
                "volume_name": "",
            }):
                # Send MAX_CONCURRENT + 2 start requests
                results = await asyncio.gather(*[
                    client.post("/parallel/start", json={"prompt": f"task {i}"})
                    for i in range(MAX_CONCURRENT + 2)
                ])

        successes = [r for r in results if r.status_code == 200]
        conflicts = [r for r in results if r.status_code == 409]

        assert len(successes) == MAX_CONCURRENT
        assert len(conflicts) == 2


class TestToDict:
    """Verify serialization for multiple slots."""

    def test_multiple_slots_serialize_independently(self):
        """Each slot serializes with its own data."""
        slots = [
            RunSlot(container_name=f"w-{i}", status="running", run_id=f"r-{i}", prompt=f"p-{i}")
            for i in range(5)
        ]
        dicts = [RunManager.to_dict(s) for s in slots]

        for i, d in enumerate(dicts):
            assert d["run_id"] == f"r-{i}"
            assert d["prompt"] == f"p-{i}"
            assert d["container_name"] == f"w-{i}"
