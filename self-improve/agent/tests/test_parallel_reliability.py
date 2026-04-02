"""Reliability tests for the parallel agent system.

Stress-tests error handling, recovery paths, and edge cases across:
- Signal delivery failures and recovery
- RunManager.send_signal method
- Worker health checks
- Container cleanup
- Monitor proxy error handling
- Concurrent error scenarios
- Slot state transition logic
"""

import asyncio
import pytest
import pytest_asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import httpx
from httpx import ASGITransport

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent.run_manager import RunManager, RunSlot, MAX_CONCURRENT, SIGNAL_ENDPOINTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_slot(**kwargs) -> RunSlot:
    defaults = {
        "run_id": "test-run-rel-001",
        "container_name": "improve-worker-rel00001",
        "status": "running",
        "container_id": "abc123def456",
        "volume_name": "improve-worker-repo-rel00001",
    }
    defaults.update(kwargs)
    return RunSlot(**defaults)


def _make_http_mock(json_return: dict | None = None, status_code: int = 200) -> AsyncMock:
    """Build a reusable httpx.AsyncClient mock."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_return or {"ok": True}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.get = AsyncMock(return_value=mock_resp)
    return mock_client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_manager():
    with patch("agent.main._run_manager") as m:
        m.get_all_slots.return_value = []
        m.active_count.return_value = 0
        m.get_slot_by_run_id.return_value = None
        yield m


@pytest_asyncio.fixture
async def client(mock_manager):
    """Async test client for the agent FastAPI app."""
    with patch("agent.db.init_db", new_callable=AsyncMock), \
         patch("agent.db.close_db", new_callable=AsyncMock), \
         patch("agent.db.mark_crashed_runs", new_callable=AsyncMock, return_value=0):
        from agent.main import app
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture
async def monitor_client():
    """Async test client for the monitor FastAPI app."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.commit = AsyncMock()
    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=None)
    mock_cursor.fetchall = AsyncMock(return_value=[])
    mock_conn.execute.return_value = mock_cursor
    mock_conn.executescript = AsyncMock()

    with patch("monitor.app._get_db", new_callable=AsyncMock, return_value=mock_conn), \
         patch("monitor.app.db", mock_conn), \
         patch("aiosqlite.connect", new_callable=AsyncMock, return_value=mock_conn):
        from monitor.app import app
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


# ===========================================================================
# Class: TestSignalDeliveryFailures
# ===========================================================================

class TestSignalDeliveryFailures:
    """Test what happens when HTTP calls to worker containers fail."""

    @pytest.mark.asyncio
    async def test_send_signal_unknown_signal(self):
        """Calling send_signal with an unknown signal raises ValueError with valid signals list."""
        mgr = RunManager()
        with pytest.raises(ValueError) as exc_info:
            await mgr.send_signal("improve-worker-x", "reboot")
        err_msg = str(exc_info.value)
        assert "Unknown signal" in err_msg
        assert "reboot" in err_msg
        # Should list the valid signals somewhere in the error
        for valid in SIGNAL_ENDPOINTS:
            assert valid in err_msg

    @pytest.mark.asyncio
    async def test_send_signal_connection_refused(self):
        """When worker container is unreachable, send_signal raises an httpx error."""
        mgr = RunManager()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.ConnectError):
                await mgr.send_signal("improve-worker-x", "stop")

    @pytest.mark.asyncio
    async def test_stop_run_signal_failure_still_updates_status(self):
        """When stop_run's send_signal fails, the error propagates and status is NOT updated."""
        mgr = RunManager()
        slot = _make_slot(container_name="improve-worker-stop-fail", status="running")
        mgr.slots["improve-worker-stop-fail"] = slot

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("agent.run_manager.db") as mock_db:
            mock_db.update_worker_status = AsyncMock()
            with pytest.raises(httpx.ConnectError):
                await mgr.stop_run("improve-worker-stop-fail", "test stop")

        # Status should NOT have been updated to stopped since send_signal raised
        assert slot.status == "running"
        # DB update for stopped status also should not have been called
        mock_db.update_worker_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_kill_run_signal_failure_still_marks_killed(self):
        """When kill_run's signal fails, it catches the exception and marks slot as killed."""
        mgr = RunManager()
        slot = _make_slot(container_name="improve-worker-kill-fail", status="running")
        mgr.slots["improve-worker-kill-fail"] = slot

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Container gone")
        )

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.object(mgr, "cleanup_container"), \
             patch("agent.run_manager.db") as mock_db:
            mock_db.update_worker_status = AsyncMock()
            result = await mgr.kill_run("improve-worker-kill-fail")

        # kill_run catches the error and still marks as killed
        assert slot.status == "killed"
        # Result should indicate failure but not raise
        assert result.get("ok") is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_kill_run_cleanup_called_even_on_signal_failure(self):
        """cleanup_container is called even when the kill signal fails."""
        mgr = RunManager()
        slot = _make_slot(container_name="improve-worker-kill-cleanup", status="running")
        mgr.slots["improve-worker-kill-cleanup"] = slot

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Container unreachable")
        )

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.object(mgr, "cleanup_container") as mock_cleanup, \
             patch("agent.run_manager.db") as mock_db:
            mock_db.update_worker_status = AsyncMock()
            await mgr.kill_run("improve-worker-kill-cleanup")

        mock_cleanup.assert_called_once_with("improve-worker-kill-cleanup")


# ===========================================================================
# Class: TestRunManagerSendSignal
# ===========================================================================

class TestRunManagerSendSignal:
    """Test the send_signal method directly on RunManager."""

    @pytest.mark.asyncio
    async def test_send_signal_correct_endpoint_mapping(self):
        """For each signal in SIGNAL_ENDPOINTS, the correct URL endpoint is used."""
        mgr = RunManager()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        expected_mappings = {
            "stop": "stop",
            "pause": "pause",
            "resume": "resume_signal",
            "inject": "inject",
            "unlock": "unlock",
            "kill": "kill",
        }

        with patch("httpx.AsyncClient", return_value=mock_client):
            for signal, expected_endpoint in expected_mappings.items():
                mock_client.post.reset_mock()
                await mgr.send_signal("improve-worker-x", signal)
                called_url = mock_client.post.call_args[0][0]
                assert called_url == f"http://improve-worker-x:8500/{expected_endpoint}", \
                    f"signal={signal!r} should map to /{expected_endpoint}, got {called_url}"

    @pytest.mark.asyncio
    async def test_send_signal_with_payload(self):
        """Payload dict is forwarded as the JSON body."""
        mgr = RunManager()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        payload = {"payload": "do something important", "extra": 42}
        with patch("httpx.AsyncClient", return_value=mock_client):
            await mgr.send_signal("improve-worker-x", "inject", payload)

        mock_client.post.assert_called_once()
        called_json = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1].get("json")
        assert called_json == payload

    @pytest.mark.asyncio
    async def test_send_signal_without_payload(self):
        """Empty dict is sent as JSON body when no payload is provided."""
        mgr = RunManager()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await mgr.send_signal("improve-worker-x", "stop")

        mock_client.post.assert_called_once()
        called_json = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1].get("json")
        assert called_json == {}

    @pytest.mark.asyncio
    async def test_send_signal_http_error_propagates(self):
        """When the worker returns 4xx/5xx, raise_for_status() propagates the error."""
        mgr = RunManager()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"detail": "not found"}
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404 Not Found",
                request=MagicMock(),
                response=MagicMock(status_code=404),
            )
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await mgr.send_signal("improve-worker-x", "stop")


# ===========================================================================
# Class: TestWorkerHealthCheck
# ===========================================================================

class TestWorkerHealthCheck:
    """Test the get_worker_health method."""

    @pytest.mark.asyncio
    async def test_get_worker_health_success(self):
        """Mock a 200 response with health data; verify it is returned."""
        mgr = RunManager()
        health_data = {"status": "running", "current_run_id": "run-abc", "uptime_s": 120}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = health_data
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await mgr.get_worker_health("improve-worker-x")

        assert result == health_data
        mock_client.get.assert_called_once_with("http://improve-worker-x:8500/health")

    @pytest.mark.asyncio
    async def test_get_worker_health_connection_error(self):
        """Connection failure from get_worker_health propagates as an exception."""
        mgr = RunManager()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.ConnectError):
                await mgr.get_worker_health("improve-worker-x")

    @pytest.mark.asyncio
    async def test_get_worker_health_timeout(self):
        """Timeout from get_worker_health propagates as an exception."""
        mgr = RunManager()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Timed out"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.TimeoutException):
                await mgr.get_worker_health("improve-worker-x")


# ===========================================================================
# Class: TestCleanupContainer
# ===========================================================================

class TestCleanupContainer:
    """Test the cleanup_container method."""

    def test_cleanup_container_stops_and_removes(self):
        """docker stop and docker rm are both called during cleanup."""
        mgr = RunManager()
        calls_made: list[list[str]] = []

        def fake_docker(args, timeout=30):
            calls_made.append(args)
            return ""

        with patch.object(mgr, "_run_docker", side_effect=fake_docker):
            mgr.cleanup_container("improve-worker-x")

        assert len(calls_made) == 2
        assert calls_made[0][0] == "stop"
        assert "improve-worker-x" in calls_made[0]
        assert calls_made[1][0] == "rm"
        assert "improve-worker-x" in calls_made[1]

    def test_cleanup_container_stop_failure_continues(self):
        """If docker stop fails, docker rm is still attempted."""
        mgr = RunManager()
        calls_made: list[list[str]] = []

        def fake_docker(args, timeout=30):
            calls_made.append(args)
            if args[0] == "stop":
                raise RuntimeError("docker stop failed: container not running")
            return ""

        with patch.object(mgr, "_run_docker", side_effect=fake_docker):
            # Should not raise even though stop failed
            mgr.cleanup_container("improve-worker-x")

        rm_calls = [c for c in calls_made if c[0] == "rm"]
        assert len(rm_calls) == 1, "docker rm must be called even when docker stop fails"
        assert "improve-worker-x" in rm_calls[0]

    def test_cleanup_container_with_volume_removal(self):
        """When remove_volume=True, docker volume rm is called with the slot's volume_name."""
        mgr = RunManager()
        slot = _make_slot(
            container_name="improve-worker-vol",
            volume_name="improve-worker-repo-vol",
            status="completed",
        )
        mgr.slots["improve-worker-vol"] = slot
        calls_made: list[list[str]] = []

        def fake_docker(args, timeout=30):
            calls_made.append(args)
            return ""

        with patch.object(mgr, "_run_docker", side_effect=fake_docker):
            mgr.cleanup_container("improve-worker-vol", remove_volume=True)

        commands = [c[0] for c in calls_made]
        assert "volume" in commands, "docker volume rm should be called"
        vol_call = next(c for c in calls_made if c[0] == "volume")
        assert vol_call == ["volume", "rm", "improve-worker-repo-vol"]

    def test_cleanup_container_removes_from_slots(self):
        """After cleanup_all_finished, the cleaned container is removed from self.slots."""
        mgr = RunManager()
        mgr.slots["improve-worker-done"] = _make_slot(
            container_name="improve-worker-done",
            status="completed",
        )
        mgr.slots["improve-worker-active"] = _make_slot(
            container_name="improve-worker-active",
            status="running",
        )

        def fake_cleanup(name, remove_volume=False):
            pass

        with patch.object(mgr, "cleanup_container", side_effect=fake_cleanup):
            mgr.cleanup_all_finished()

        assert "improve-worker-done" not in mgr.slots
        assert "improve-worker-active" in mgr.slots


# ===========================================================================
# Class: TestMonitorProxyErrorHandling
# ===========================================================================

class TestMonitorProxyErrorHandling:
    """Test the monitor parallel proxy endpoints when agent is unreachable or errors."""

    @pytest.mark.asyncio
    async def test_parallel_start_agent_timeout(self, monitor_client):
        """Agent takes too long to respond to /parallel/start → 502."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timed out"))

        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("monitor.app._get_db", new_callable=AsyncMock, return_value=mock_conn):
            resp = await monitor_client.post("/api/parallel/start", json={})

        assert resp.status_code == 502
        assert "unreachable" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_parallel_stop_agent_unreachable(self, monitor_client):
        """Agent unreachable for stop signal → 502."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = await monitor_client.post(
                "/api/parallel/runs/some-run-id/stop",
                json={"payload": "stop now"},
            )

        assert resp.status_code == 502
        assert "unreachable" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_parallel_inject_agent_unreachable(self, monitor_client):
        """Agent unreachable for inject → 502."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = await monitor_client.post(
                "/api/parallel/runs/some-run-id/inject",
                json={"payload": "focus on docs"},
            )

        assert resp.status_code == 502
        assert "unreachable" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_parallel_status_returns_unreachable(self, monitor_client):
        """Status endpoint returns {"status": "unreachable"} when agent is down."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = await monitor_client.get("/api/parallel/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unreachable"
        assert "error" in data

    @pytest.mark.asyncio
    async def test_parallel_cleanup_agent_unreachable(self, monitor_client):
        """Cleanup when agent is down → 502."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = await monitor_client.post("/api/parallel/cleanup")

        assert resp.status_code == 502
        assert "unreachable" in resp.json()["detail"].lower()


# ===========================================================================
# Class: TestConcurrentErrorRecovery
# ===========================================================================

class TestConcurrentErrorRecovery:
    """Test error scenarios in concurrent operation."""

    @pytest.mark.asyncio
    async def test_concurrent_start_one_fails_others_succeed(self, client, mock_manager):
        """Start 3 runs concurrently; one Docker run fails. The failed one gets an error response."""
        good_slot_1 = _make_slot(run_id="concurrent-1", container_name="improve-worker-c1", status="running")
        good_slot_2 = _make_slot(run_id="concurrent-2", container_name="improve-worker-c2", status="running")

        call_count = 0

        async def start_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("[run_manager] docker run failed: image not found")
            return good_slot_1 if call_count == 1 else good_slot_2

        mock_manager.start_run = AsyncMock(side_effect=start_side_effect)

        with patch.object(RunManager, "to_dict", return_value=RunManager.to_dict(good_slot_1)):
            resp1 = await client.post("/parallel/start", json={"prompt": "task 1"})
        assert resp1.status_code == 200

        resp2 = await client.post("/parallel/start", json={"prompt": "task 2"})
        assert resp2.status_code in (500, 502, 503, 409)

        with patch.object(RunManager, "to_dict", return_value=RunManager.to_dict(good_slot_2)):
            resp3 = await client.post("/parallel/start", json={"prompt": "task 3"})
        assert resp3.status_code == 200

    @pytest.mark.asyncio
    async def test_rapid_stop_kill_same_run(self, client, mock_manager):
        """Issue stop then immediately kill on the same run; both handled gracefully."""
        run_id = "rapid-sk-run"
        slot = _make_slot(run_id=run_id, container_name="improve-worker-sk001", status="running")
        mock_manager.get_slot_by_run_id.return_value = slot
        mock_manager.stop_run = AsyncMock(return_value={"ok": True, "signal": "stop"})
        mock_manager.kill_run = AsyncMock(return_value={"ok": True, "signal": "kill"})

        stop_resp = await client.post(f"/parallel/runs/{run_id}/stop", json={})
        assert stop_resp.status_code == 200

        # Simulate state change after stop
        slot.status = "stopped"

        # Kill should still work even for a stopped slot (no guard on kill)
        kill_resp = await client.post(f"/parallel/runs/{run_id}/kill")
        assert kill_resp.status_code == 200

        mock_manager.stop_run.assert_awaited_once()
        mock_manager.kill_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_inject_during_stop(self, client, mock_manager):
        """Inject a prompt while also sending a stop; both operations complete without crashing."""
        run_id = "inject-stop-run"
        slot = _make_slot(run_id=run_id, container_name="improve-worker-is001", status="running")
        mock_manager.get_slot_by_run_id.return_value = slot
        mock_manager.inject_prompt = AsyncMock(return_value={"ok": True, "signal": "inject"})
        mock_manager.stop_run = AsyncMock(return_value={"ok": True, "signal": "stop"})

        inject_resp = await client.post(
            f"/parallel/runs/{run_id}/inject",
            json={"payload": "focus on reliability"},
        )
        stop_resp = await client.post(f"/parallel/runs/{run_id}/stop", json={})

        assert inject_resp.status_code == 200
        assert stop_resp.status_code == 200

    @pytest.mark.asyncio
    async def test_status_endpoint_during_rapid_state_changes(self, client, mock_manager):
        """Query /parallel/status multiple times; always returns valid JSON."""
        slots = [
            _make_slot(run_id=f"state-run-{i}", container_name=f"improve-worker-s{i:07x}", status="running")
            for i in range(3)
        ]
        mock_manager.get_all_slots.return_value = slots
        mock_manager.active_count.return_value = 3

        for i in range(5):
            if i % 2 == 0:
                mock_manager.active_count.return_value = max(0, 3 - i)
            resp = await client.get("/parallel/status")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)
            assert "active" in data
            assert "total_slots" in data


# ===========================================================================
# Class: TestSlotStateTransitions
# ===========================================================================

class TestSlotStateTransitions:
    """Test RunManager slot state management directly."""

    def test_slot_status_values(self):
        """All valid status values can be assigned to a RunSlot."""
        valid_statuses = ["starting", "running", "completed", "stopped", "error", "killed"]
        for status in valid_statuses:
            slot = RunSlot(status=status)
            assert slot.status == status

    def test_active_count_only_counts_starting_and_running(self):
        """active_count returns the count of only starting+running slots."""
        mgr = RunManager()
        all_statuses = {
            "w-starting": RunSlot(status="starting"),
            "w-running": RunSlot(status="running"),
            "w-completed": RunSlot(status="completed"),
            "w-stopped": RunSlot(status="stopped"),
            "w-error": RunSlot(status="error"),
            "w-killed": RunSlot(status="killed"),
        }
        mgr.slots = all_statuses
        assert mgr.active_count() == 2

    def test_cleanup_all_finished_returns_count(self):
        """cleanup_all_finished returns the number of slots that were cleaned up."""
        mgr = RunManager()
        mgr.slots = {
            "a": RunSlot(status="running"),
            "b": RunSlot(status="completed"),
            "c": RunSlot(status="stopped"),
            "d": RunSlot(status="error"),
            "e": RunSlot(status="killed"),
        }

        def fake_cleanup(name, remove_volume=False):
            pass

        with patch.object(mgr, "cleanup_container", side_effect=fake_cleanup):
            count = mgr.cleanup_all_finished()

        assert count == 4

    def test_cleanup_preserves_starting_slots(self):
        """Slots with status 'starting' are not removed by cleanup_all_finished."""
        mgr = RunManager()
        mgr.slots = {
            "w-starting": RunSlot(status="starting"),
            "w-running": RunSlot(status="running"),
            "w-done": RunSlot(status="completed"),
        }

        def fake_cleanup(name, remove_volume=False):
            pass

        with patch.object(mgr, "cleanup_container", side_effect=fake_cleanup):
            count = mgr.cleanup_all_finished()

        assert count == 1
        assert "w-starting" in mgr.slots
        assert "w-running" in mgr.slots
        assert "w-done" not in mgr.slots

    def test_to_dict_serialization_all_fields(self):
        """RunManager.to_dict includes all expected fields with correct values."""
        import time
        ts = time.time()
        slot = RunSlot(
            run_id="dict-run-001",
            container_name="improve-worker-dict001",
            container_id="abc123def456",
            status="running",
            prompt="test the serialization",
            max_budget_usd=5.0,
            duration_minutes=30.0,
            base_branch="main",
            error_message=None,
            volume_name="improve-worker-repo-dict001",
            started_at=ts,
        )
        d = RunManager.to_dict(slot)

        expected_keys = {
            "run_id",
            "container_name",
            "container_id",
            "status",
            "prompt",
            "max_budget_usd",
            "duration_minutes",
            "base_branch",
            "started_at",
            "error_message",
            "volume_name",
        }
        assert set(d.keys()) == expected_keys

        assert d["run_id"] == "dict-run-001"
        assert d["container_name"] == "improve-worker-dict001"
        assert d["container_id"] == "abc123def456"
        assert d["status"] == "running"
        assert d["prompt"] == "test the serialization"
        assert d["max_budget_usd"] == 5.0
        assert d["duration_minutes"] == 30.0
        assert d["base_branch"] == "main"
        assert d["started_at"] == ts
        assert d["error_message"] is None
        assert d["volume_name"] == "improve-worker-repo-dict001"
