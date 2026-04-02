"""End-to-end parallel agent flow tests.

Tests realistic multi-step user flows across the /parallel/* endpoints,
covering full lifecycle sequences, multi-run scenarios, edge cases,
prompt variations, and monitor endpoint checks.
"""

import pytest
import pytest_asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from httpx import ASGITransport

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent.run_manager import RunSlot, RunManager, MAX_CONCURRENT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_slot(**kwargs):
    defaults = {
        "run_id": "test-run-123",
        "container_name": "improve-worker-abc12345",
        "status": "running",
        "container_id": "abc123",
    }
    defaults.update(kwargs)
    return RunSlot(**defaults)


def _slot_dict(slot: RunSlot) -> dict:
    """Return a full serialized dict for use in mock return values."""
    return RunManager.to_dict(slot)


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


# ---------------------------------------------------------------------------
# Class: TestFullLifecycleFlows
# ---------------------------------------------------------------------------

class TestFullLifecycleFlows:
    """End-to-end lifecycle flows: start → signal → cleanup."""

    @pytest.mark.asyncio
    async def test_start_inject_stop_cleanup(self, client, mock_manager):
        """Start a run, inject a prompt, stop it, then clean up."""
        run_id = "flow-run-001"
        slot = _make_slot(run_id=run_id, status="running")

        # --- Step 1: Start ---
        mock_manager.start_run = AsyncMock(return_value=slot)
        with patch.object(RunManager, "to_dict", return_value=_slot_dict(slot)):
            resp = await client.post("/parallel/start", json={"prompt": "improve tests"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_manager.start_run.assert_awaited_once()

        # --- Step 2: Inject ---
        mock_manager.get_slot_by_run_id.return_value = slot
        mock_manager.inject_prompt = AsyncMock(return_value={"ok": True, "signal": "inject"})
        resp = await client.post(
            f"/parallel/runs/{run_id}/inject",
            json={"payload": "focus on performance"},
        )
        assert resp.status_code == 200
        mock_manager.inject_prompt.assert_awaited_once_with(
            slot.container_name, {"payload": "focus on performance"}
        )

        # --- Step 3: Stop ---
        mock_manager.stop_run = AsyncMock(return_value={"ok": True, "signal": "stop"})
        resp = await client.post(
            f"/parallel/runs/{run_id}/stop",
            json={"payload": "done"},
        )
        assert resp.status_code == 200
        mock_manager.stop_run.assert_awaited_once_with(slot.container_name, "done")

        # --- Step 4: Cleanup (simulate slot now stopped) ---
        slot.status = "stopped"
        mock_manager.get_all_slots.return_value = [slot]
        mock_manager.cleanup_all_finished = MagicMock()
        resp = await client.post("/parallel/cleanup")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["cleaned"] == 1
        mock_manager.cleanup_all_finished.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_pause_resume_stop(self, client, mock_manager):
        """Start a run, pause it, resume it, then stop it."""
        run_id = "flow-run-002"
        slot = _make_slot(run_id=run_id, status="running")
        mock_manager.get_slot_by_run_id.return_value = slot

        # Start
        mock_manager.start_run = AsyncMock(return_value=slot)
        with patch.object(RunManager, "to_dict", return_value=_slot_dict(slot)):
            resp = await client.post("/parallel/start", json={})
        assert resp.status_code == 200

        # Pause — slot is running, should succeed
        mock_manager.pause_run = AsyncMock(return_value={"ok": True, "signal": "pause"})
        resp = await client.post(f"/parallel/runs/{run_id}/pause")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_manager.pause_run.assert_awaited_once_with(slot.container_name)

        # Simulate state transition to paused
        slot.status = "paused"

        # Resume — for resume there's no status guard in the endpoint; it calls through
        mock_manager.resume_run = AsyncMock(return_value={"ok": True, "signal": "resume"})
        resp = await client.post(f"/parallel/runs/{run_id}/resume")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_manager.resume_run.assert_awaited_once_with(slot.container_name)

        # Simulate transition back to running
        slot.status = "running"

        # Stop
        mock_manager.stop_run = AsyncMock(return_value={"ok": True, "signal": "stop"})
        resp = await client.post(f"/parallel/runs/{run_id}/stop", json={})
        assert resp.status_code == 200
        mock_manager.stop_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_unlock_complete(self, client, mock_manager):
        """Start a run, then unlock its session gate."""
        run_id = "flow-run-003"
        slot = _make_slot(run_id=run_id, status="running")

        mock_manager.start_run = AsyncMock(return_value=slot)
        with patch.object(RunManager, "to_dict", return_value=_slot_dict(slot)):
            resp = await client.post("/parallel/start", json={"prompt": "time-locked task"})
        assert resp.status_code == 200

        mock_manager.get_slot_by_run_id.return_value = slot
        mock_manager.unlock_run = AsyncMock(return_value={"ok": True, "signal": "unlock"})
        resp = await client.post(f"/parallel/runs/{run_id}/unlock")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_manager.unlock_run.assert_awaited_once_with(slot.container_name)

    @pytest.mark.asyncio
    async def test_start_kill_cleanup(self, client, mock_manager):
        """Start a run, kill it immediately, then clean up."""
        run_id = "flow-run-004"
        slot = _make_slot(run_id=run_id, status="running")

        mock_manager.start_run = AsyncMock(return_value=slot)
        with patch.object(RunManager, "to_dict", return_value=_slot_dict(slot)):
            resp = await client.post("/parallel/start", json={})
        assert resp.status_code == 200

        # Kill
        mock_manager.get_slot_by_run_id.return_value = slot
        mock_manager.kill_run = AsyncMock(return_value={"ok": True, "signal": "kill"})
        resp = await client.post(f"/parallel/runs/{run_id}/kill")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_manager.kill_run.assert_awaited_once_with(slot.container_name)

        # Simulate killed status
        slot.status = "killed"
        mock_manager.get_all_slots.return_value = [slot]
        mock_manager.cleanup_all_finished = MagicMock()
        resp = await client.post("/parallel/cleanup")
        assert resp.status_code == 200
        assert resp.json()["cleaned"] == 1


# ---------------------------------------------------------------------------
# Class: TestMultiRunFlows
# ---------------------------------------------------------------------------

class TestMultiRunFlows:
    """Tests for multiple concurrent runs with independent operations."""

    @pytest.mark.asyncio
    async def test_three_concurrent_runs_independent_signals(self, client, mock_manager):
        """Start 3 runs, send different signals to each, verify each got the right one."""
        slots = [
            _make_slot(run_id=f"multi-run-{i}", container_name=f"improve-worker-{i:08x}", status="running")
            for i in range(3)
        ]

        # Set up start_run to return each slot in sequence
        mock_manager.start_run = AsyncMock(side_effect=slots)
        for slot in slots:
            with patch.object(RunManager, "to_dict", return_value=_slot_dict(slot)):
                resp = await client.post("/parallel/start", json={"prompt": f"task {slot.run_id}"})
            assert resp.status_code == 200

        # Stop run-0
        mock_manager.get_slot_by_run_id.side_effect = lambda rid: next(
            (s for s in slots if s.run_id == rid), None
        )
        mock_manager.stop_run = AsyncMock(return_value={"ok": True, "signal": "stop"})
        resp = await client.post("/parallel/runs/multi-run-0/stop", json={"payload": "done"})
        assert resp.status_code == 200
        mock_manager.stop_run.assert_awaited_once_with(slots[0].container_name, "done")

        # Pause run-1
        mock_manager.pause_run = AsyncMock(return_value={"ok": True, "signal": "pause"})
        resp = await client.post("/parallel/runs/multi-run-1/pause")
        assert resp.status_code == 200
        mock_manager.pause_run.assert_awaited_once_with(slots[1].container_name)

        # Inject into run-2
        mock_manager.inject_prompt = AsyncMock(return_value={"ok": True, "signal": "inject"})
        resp = await client.post(
            "/parallel/runs/multi-run-2/inject",
            json={"payload": "focus on docs"},
        )
        assert resp.status_code == 200
        mock_manager.inject_prompt.assert_awaited_once_with(
            slots[2].container_name, {"payload": "focus on docs"}
        )

    @pytest.mark.asyncio
    async def test_start_runs_stop_one_others_continue(self, client, mock_manager):
        """Start 3 runs, stop one, verify other 2 still running."""
        slots = [
            _make_slot(run_id=f"cont-run-{i}", container_name=f"improve-worker-c{i:07x}", status="running")
            for i in range(3)
        ]
        mock_manager.start_run = AsyncMock(side_effect=slots)

        for slot in slots:
            with patch.object(RunManager, "to_dict", return_value=_slot_dict(slot)):
                resp = await client.post("/parallel/start", json={})
            assert resp.status_code == 200

        # Stop only run-1
        mock_manager.get_slot_by_run_id.side_effect = lambda rid: next(
            (s for s in slots if s.run_id == rid), None
        )
        mock_manager.stop_run = AsyncMock(return_value={"ok": True, "signal": "stop"})
        resp = await client.post("/parallel/runs/cont-run-1/stop", json={})
        assert resp.status_code == 200

        # Simulate state update
        slots[1].status = "stopped"

        # Verify other slots still running
        assert slots[0].status == "running"
        assert slots[2].status == "running"
        assert slots[1].status == "stopped"

        # Check the list endpoint returns correct count
        mock_manager.get_all_slots.return_value = slots
        mock_manager.active_count.return_value = 2
        resp = await client.get("/parallel/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] == 2

    @pytest.mark.asyncio
    async def test_fill_to_max_cleanup_start_more(self, client, mock_manager):
        """Fill all slots → 409 on next start → cleanup → new start succeeds."""
        # Attempt to start when at max
        mock_manager.start_run = AsyncMock(
            side_effect=RuntimeError(f"[run_manager] Max concurrent runs ({MAX_CONCURRENT}) reached")
        )
        resp = await client.post("/parallel/start", json={})
        assert resp.status_code == 409
        assert "Max concurrent" in resp.json()["detail"]

        # Simulate cleanup freeing a slot
        finished_slots = [
            _make_slot(run_id=f"old-run-{i}", container_name=f"improve-worker-o{i:07x}", status="completed")
            for i in range(3)
        ]
        mock_manager.get_all_slots.return_value = finished_slots
        mock_manager.cleanup_all_finished = MagicMock()

        resp = await client.post("/parallel/cleanup")
        assert resp.status_code == 200
        assert resp.json()["cleaned"] == 3

        # Now start succeeds
        new_slot = _make_slot(run_id="new-run-after-cleanup", status="running")
        mock_manager.start_run = AsyncMock(return_value=new_slot)
        with patch.object(RunManager, "to_dict", return_value=_slot_dict(new_slot)):
            resp = await client.post("/parallel/start", json={"prompt": "fresh start"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# Class: TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases: nonexistent runs, invalid state transitions, double signals."""

    @pytest.mark.asyncio
    async def test_signal_to_nonexistent_run(self, client, mock_manager):
        """All signal endpoints return 404 for an unknown run ID."""
        mock_manager.get_slot_by_run_id.return_value = None

        for endpoint in ("stop", "pause", "resume", "kill", "unlock"):
            resp = await client.post(f"/parallel/runs/ghost-run-999/{endpoint}", json={})
            assert resp.status_code == 404, f"Expected 404 for /{endpoint}, got {resp.status_code}"
            assert "not found" in resp.json()["detail"].lower()

        # inject also requires payload but 404 should fire before 400
        resp = await client.post(
            "/parallel/runs/ghost-run-999/inject",
            json={"payload": "test"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_stop_already_stopped_run(self, client, mock_manager):
        """Stopping a run that is already stopped returns 409."""
        slot = _make_slot(run_id="stopped-run", status="stopped")
        mock_manager.get_slot_by_run_id.return_value = slot

        resp = await client.post("/parallel/runs/stopped-run/stop", json={})
        assert resp.status_code == 409
        assert "stopped" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_pause_non_running_states(self, client, mock_manager):
        """Pausing a run in completed/stopped/starting states returns 409."""
        for status in ("completed", "stopped", "starting"):
            slot = _make_slot(run_id=f"run-{status}", status=status)
            mock_manager.get_slot_by_run_id.return_value = slot

            resp = await client.post(f"/parallel/runs/run-{status}/pause")
            assert resp.status_code == 409, f"Expected 409 for status={status}"
            assert status in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_inject_empty_payload(self, client, mock_manager):
        """Inject with no payload returns 400."""
        slot = _make_slot(run_id="inject-run", status="running")
        mock_manager.get_slot_by_run_id.return_value = slot

        resp = await client.post("/parallel/runs/inject-run/inject", json={})
        assert resp.status_code == 400
        assert "Payload" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_kill_already_killed(self, client, mock_manager):
        """Kill always attempts force-remove even if run is already killed."""
        slot = _make_slot(run_id="killed-run", status="killed")
        mock_manager.get_slot_by_run_id.return_value = slot
        mock_manager.kill_run = AsyncMock(return_value={"ok": True, "signal": "kill"})

        resp = await client.post("/parallel/runs/killed-run/kill")
        # Kill endpoint has no status guard — it always calls through
        assert resp.status_code == 200
        mock_manager.kill_run.assert_awaited_once_with(slot.container_name)

    @pytest.mark.asyncio
    async def test_double_stop_signal(self, client, mock_manager):
        """First stop succeeds; second stop on the same run returns 409."""
        slot = _make_slot(run_id="double-stop-run", status="running")
        mock_manager.get_slot_by_run_id.return_value = slot
        mock_manager.stop_run = AsyncMock(return_value={"ok": True, "signal": "stop"})

        # First stop
        resp = await client.post("/parallel/runs/double-stop-run/stop", json={})
        assert resp.status_code == 200

        # Simulate transition
        slot.status = "stopped"

        # Second stop — status is now stopped → 409
        resp = await client.post("/parallel/runs/double-stop-run/stop", json={})
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_cleanup_with_no_finished_runs(self, client, mock_manager):
        """Cleanup when all runs are active returns cleaned=0."""
        active_slots = [
            _make_slot(run_id=f"active-{i}", container_name=f"improve-worker-a{i:07x}", status="running")
            for i in range(3)
        ]
        mock_manager.get_all_slots.return_value = active_slots
        mock_manager.cleanup_all_finished = MagicMock()

        resp = await client.post("/parallel/cleanup")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["cleaned"] == 0

    @pytest.mark.asyncio
    async def test_cleanup_with_mixed_states(self, client, mock_manager):
        """Only finished runs count toward cleaned; active runs are untouched."""
        slots = [
            _make_slot(run_id="mix-running", container_name="improve-worker-r0000001", status="running"),
            _make_slot(run_id="mix-starting", container_name="improve-worker-r0000002", status="starting"),
            _make_slot(run_id="mix-completed", container_name="improve-worker-r0000003", status="completed"),
            _make_slot(run_id="mix-stopped", container_name="improve-worker-r0000004", status="stopped"),
            _make_slot(run_id="mix-error", container_name="improve-worker-r0000005", status="error"),
        ]
        mock_manager.get_all_slots.return_value = slots
        mock_manager.cleanup_all_finished = MagicMock()

        resp = await client.post("/parallel/cleanup")
        assert resp.status_code == 200
        # 3 non-active: completed, stopped, error
        assert resp.json()["cleaned"] == 3

    @pytest.mark.asyncio
    async def test_status_reflects_active_count(self, client, mock_manager):
        """After stopping one of 3 runs, status active count drops to 2."""
        slots = [
            _make_slot(run_id=f"cnt-{i}", container_name=f"improve-worker-n{i:07x}", status="running")
            for i in range(3)
        ]
        mock_manager.get_slot_by_run_id.side_effect = lambda rid: next(
            (s for s in slots if s.run_id == rid), None
        )
        mock_manager.stop_run = AsyncMock(return_value={"ok": True})

        resp = await client.post("/parallel/runs/cnt-0/stop", json={})
        assert resp.status_code == 200
        slots[0].status = "stopped"

        mock_manager.get_all_slots.return_value = slots
        mock_manager.active_count.return_value = 2

        resp = await client.get("/parallel/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] == 2
        assert data["total_slots"] == 3


# ---------------------------------------------------------------------------
# Class: TestSimplePromptVariations
# ---------------------------------------------------------------------------

class TestSimplePromptVariations:
    """Tests that start parameters are forwarded correctly to RunManager."""

    @pytest.mark.asyncio
    async def test_start_with_no_prompt(self, client, mock_manager):
        """Starting with no prompt succeeds and passes None prompt to manager."""
        slot = _make_slot(run_id="no-prompt-run", status="running", prompt=None)
        mock_manager.start_run = AsyncMock(return_value=slot)

        with patch.object(RunManager, "to_dict", return_value=_slot_dict(slot)):
            resp = await client.post("/parallel/start", json={})

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        call_kwargs = mock_manager.start_run.call_args
        assert call_kwargs.kwargs.get("prompt") is None or call_kwargs.args[0] is None

    @pytest.mark.asyncio
    async def test_start_with_custom_prompt(self, client, mock_manager):
        """Starting with a specific prompt string passes it through to start_run."""
        custom = "Refactor the auth module for better readability"
        slot = _make_slot(run_id="prompt-run", status="running", prompt=custom)
        mock_manager.start_run = AsyncMock(return_value=slot)

        with patch.object(RunManager, "to_dict", return_value=_slot_dict(slot)):
            resp = await client.post("/parallel/start", json={"prompt": custom})

        assert resp.status_code == 200
        mock_manager.start_run.assert_awaited_once()
        # Verify the prompt was passed (first positional or keyword arg)
        call_args = mock_manager.start_run.call_args
        passed_prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else None)
        assert passed_prompt == custom

    @pytest.mark.asyncio
    async def test_start_with_budget_and_duration(self, client, mock_manager):
        """Budget and duration params are forwarded to start_run."""
        slot = _make_slot(run_id="budget-run", status="running", max_budget_usd=10.0, duration_minutes=60)
        mock_manager.start_run = AsyncMock(return_value=slot)

        with patch.object(RunManager, "to_dict", return_value=_slot_dict(slot)):
            resp = await client.post("/parallel/start", json={
                "max_budget_usd": 10.0,
                "duration_minutes": 60,
            })

        assert resp.status_code == 200
        mock_manager.start_run.assert_awaited_once()
        call_kwargs = mock_manager.start_run.call_args.kwargs
        assert call_kwargs.get("max_budget_usd") == 10.0
        assert call_kwargs.get("duration_minutes") == 60

    @pytest.mark.asyncio
    async def test_start_with_different_base_branches(self, client, mock_manager):
        """Each run's base_branch is forwarded to start_run independently."""
        branches = ["main", "develop", "feature/my-feature"]

        for branch in branches:
            slot = _make_slot(run_id=f"branch-run-{branch}", status="running", base_branch=branch)
            mock_manager.start_run = AsyncMock(return_value=slot)

            with patch.object(RunManager, "to_dict", return_value=_slot_dict(slot)):
                resp = await client.post("/parallel/start", json={"base_branch": branch})

            assert resp.status_code == 200
            call_kwargs = mock_manager.start_run.call_args.kwargs
            assert call_kwargs.get("base_branch") == branch


# ---------------------------------------------------------------------------
# Class: TestMonitorEndpointsRemoved
# ---------------------------------------------------------------------------

class TestMonitorEndpointsRemoved:
    """Verify old single-agent monitor endpoints are gone; new ones remain."""

    @pytest.mark.asyncio
    async def test_old_start_endpoint_gone(self, monitor_client):
        """POST /api/agent/start is not a defined route (404 or 405)."""
        resp = await monitor_client.post("/api/agent/start", json={})
        assert resp.status_code in (404, 405)

    @pytest.mark.asyncio
    async def test_old_stop_endpoint_gone(self, monitor_client):
        """POST /api/agent/stop is not a defined route (404 or 405)."""
        resp = await monitor_client.post("/api/agent/stop", json={})
        assert resp.status_code in (404, 405)

    @pytest.mark.asyncio
    async def test_old_kill_endpoint_gone(self, monitor_client):
        """POST /api/agent/kill is not a defined route (404 or 405)."""
        resp = await monitor_client.post("/api/agent/kill", json={})
        assert resp.status_code in (404, 405)

    @pytest.mark.asyncio
    async def test_old_resume_endpoint_gone(self, monitor_client):
        """POST /api/agent/resume is not a defined route (404 or 405)."""
        resp = await monitor_client.post("/api/agent/resume", json={})
        assert resp.status_code in (404, 405)

    @pytest.mark.asyncio
    async def test_health_endpoint_still_works(self, monitor_client):
        """GET /api/agent/health on the monitor still proxies to agent and returns 200."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "idle", "current_run_id": None}

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            resp = await monitor_client.get("/api/agent/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "idle"
