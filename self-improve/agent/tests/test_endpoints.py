"""Unit tests for agent/endpoints.py — HTTP route handlers.

Covers:
- GET /health  (idle vs running states)
- POST /start  (success, 409 if run in progress, credential injection)
- POST /resume (success, 409 if run in progress)
- POST /pause  (success with correct signal, 409 if no run)
- POST /resume_signal (success with correct signal, 409 if no run)
- POST /inject (success with payload, 409 if no run)
- POST /unlock (success with correct signal, 409 if no run)
- POST /stop   (success with correct signal, 409 if no run)
- POST /kill   (cancels task + DB update, 409 if no run)
- GET /branches (success + failure fallback)
- GET /diff/live (idle vs running, error fallback)
- GET /diff/{branch} (success, error fallback)
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Make the agent package importable from the tests sub-directory
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import the real module — all its dependencies are importable.
from agent import endpoints  # noqa: E402


# ---------------------------------------------------------------------------
# App and client — built once for the module, safe because mocks are injected
# at the attribute level before each test via the autouse fixture below.
# ---------------------------------------------------------------------------

_app = FastAPI()
_app.include_router(endpoints.router)
_client = TestClient(_app)


# ---------------------------------------------------------------------------
# Autouse fixture — patches all five heavy dependencies on the endpoints
# module for every test, then restores them automatically (monkeypatch scope).
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_deps(monkeypatch):
    db_mock = MagicMock()
    db_mock.finish_run = AsyncMock()
    db_mock.get_db = MagicMock()

    signals_mock = MagicMock()
    signals_mock.current_run_id = None
    signals_mock.current_task = None

    session_gate_mock = MagicMock()
    runner_mock = MagicMock()
    git_ops_mock = MagicMock()

    monkeypatch.setattr(endpoints, "db", db_mock)
    monkeypatch.setattr(endpoints, "signals", signals_mock)
    monkeypatch.setattr(endpoints, "session_gate", session_gate_mock)
    monkeypatch.setattr(endpoints, "runner", runner_mock)
    monkeypatch.setattr(endpoints, "git_ops", git_ops_mock)

    return {
        "db": db_mock,
        "signals": signals_mock,
        "session_gate": session_gate_mock,
        "runner": runner_mock,
        "git_ops": git_ops_mock,
    }


# ---------------------------------------------------------------------------
# Helpers — reference endpoints.signals so they always use the current mock.
# ---------------------------------------------------------------------------

def _set_idle():
    """Simulate no active run."""
    endpoints.signals.current_run_id = None
    endpoints.signals.current_task = None


def _set_running(run_id: str = "run-abc-123"):
    """Simulate an active run with a cancellable task mock."""
    endpoints.signals.current_run_id = run_id
    mock_task = MagicMock()
    mock_task.cancel = MagicMock()
    endpoints.signals.current_task = mock_task


# ===========================================================================
# GET /health
# ===========================================================================

class TestHealth:
    def test_idle_status(self):
        _set_idle()
        resp = _client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "idle"
        assert data["current_run_id"] is None
        assert data["elapsed_minutes"] is None
        assert data["time_remaining"] is None
        assert data["session_unlocked"] is None

    def test_running_status(self):
        _set_running("run-xyz")
        endpoints.session_gate.elapsed_minutes.return_value = 5.0
        endpoints.session_gate.time_remaining_str.return_value = "25m"
        endpoints.session_gate.is_unlocked.return_value = False

        resp = _client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["current_run_id"] == "run-xyz"
        assert data["elapsed_minutes"] == 5.0
        assert data["time_remaining"] == "25m"
        assert data["session_unlocked"] is False

    def test_running_session_unlocked(self):
        _set_running("run-xyz")
        endpoints.session_gate.elapsed_minutes.return_value = 31.0
        endpoints.session_gate.time_remaining_str.return_value = "0m"
        endpoints.session_gate.is_unlocked.return_value = True

        resp = _client.get("/health")
        data = resp.json()
        assert data["session_unlocked"] is True

    def test_elapsed_rounded_to_one_decimal(self):
        _set_running("run-round")
        endpoints.session_gate.elapsed_minutes.return_value = 7.555
        endpoints.session_gate.time_remaining_str.return_value = "22m"
        endpoints.session_gate.is_unlocked.return_value = False

        resp = _client.get("/health")
        # round(..., 1) applied in the endpoint
        assert resp.json()["elapsed_minutes"] == 7.6


# ===========================================================================
# POST /start
# ===========================================================================

class TestStart:
    def setup_method(self):
        _set_idle()

    def test_start_returns_ok_when_idle(self):
        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()
        endpoints.runner.run_agent = AsyncMock(return_value=None)

        with patch("asyncio.create_task", return_value=mock_task), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            resp = _client.post("/start", json={})

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_start_returns_prompt_and_budget(self):
        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()
        endpoints.runner.run_agent = AsyncMock(return_value=None)

        with patch("asyncio.create_task", return_value=mock_task), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            resp = _client.post("/start", json={
                "prompt": "improve tests",
                "max_budget_usd": 5.0,
                "duration_minutes": 30.0,
                "base_branch": "dev",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["prompt"] == "improve tests"
        assert data["max_budget_usd"] == 5.0
        assert data["duration_minutes"] == 30.0
        assert data["base_branch"] == "dev"

    def test_start_409_when_run_in_progress(self):
        _set_running("run-existing")
        resp = _client.post("/start", json={})
        assert resp.status_code == 409
        assert "run-existing" in resp.json()["detail"]

    def test_start_registers_done_callback(self):
        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()

        with patch("asyncio.create_task", return_value=mock_task), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            _client.post("/start", json={})

        mock_task.add_done_callback.assert_called_once_with(endpoints._on_task_done)

    def test_start_injects_claude_token(self):
        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()

        with patch("asyncio.create_task", return_value=mock_task), \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("os.environ", {}) as env:
            _client.post("/start", json={"claude_token": "tok-abc"})
            assert env.get("CLAUDE_CODE_OAUTH_TOKEN") == "tok-abc"

    def test_start_injects_git_token(self):
        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()

        with patch("asyncio.create_task", return_value=mock_task), \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("os.environ", {}) as env:
            _client.post("/start", json={"git_token": "ghp-xyz"})
            assert env.get("GIT_TOKEN") == "ghp-xyz"

    def test_start_injects_github_repo(self):
        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()

        with patch("asyncio.create_task", return_value=mock_task), \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("os.environ", {}) as env:
            _client.post("/start", json={"github_repo": "org/repo"})
            assert env.get("GITHUB_REPO") == "org/repo"

    def test_start_null_prompt_returns_none(self):
        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()

        with patch("asyncio.create_task", return_value=mock_task), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            resp = _client.post("/start", json={})

        assert resp.json()["prompt"] is None


# ===========================================================================
# POST /resume
# ===========================================================================

class TestResume:
    def setup_method(self):
        _set_idle()

    def test_resume_returns_ok_when_idle(self):
        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()

        with patch("asyncio.create_task", return_value=mock_task), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            resp = _client.post("/resume", json={"run_id": "run-prev-1"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["run_id"] == "run-prev-1"
        assert data["resumed"] is True

    def test_resume_409_when_run_in_progress(self):
        _set_running("run-active")
        resp = _client.post("/resume", json={"run_id": "run-prev-1"})
        assert resp.status_code == 409
        assert "run-active" in resp.json()["detail"]

    def test_resume_registers_done_callback(self):
        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()

        with patch("asyncio.create_task", return_value=mock_task), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            _client.post("/resume", json={"run_id": "run-prev-2"})

        mock_task.add_done_callback.assert_called_once_with(endpoints._on_task_done)

    def test_resume_injects_credentials(self):
        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()

        with patch("asyncio.create_task", return_value=mock_task), \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("os.environ", {}) as env:
            _client.post("/resume", json={
                "run_id": "run-prev-3",
                "claude_token": "ct",
                "git_token": "gt",
                "github_repo": "org/r",
            })
            assert env.get("CLAUDE_CODE_OAUTH_TOKEN") == "ct"
            assert env.get("GIT_TOKEN") == "gt"
            assert env.get("GITHUB_REPO") == "org/r"


# ===========================================================================
# Signal endpoints — shared helpers
# ===========================================================================

_SIGNAL_ENDPOINTS = [
    ("/pause",          "pause",   None),
    ("/resume_signal",  "resume",  None),
    ("/unlock",         "unlock",  None),
    ("/stop",           "stop",    "Operator stop via API"),
]


class TestSignalEndpointsNoRun:
    """All signal POST endpoints return 409 when no run is in progress."""

    @pytest.mark.parametrize("path,_sig,_payload", _SIGNAL_ENDPOINTS)
    def test_409_when_idle(self, path, _sig, _payload):
        _set_idle()
        resp = _client.post(path)
        assert resp.status_code == 409
        assert resp.json()["detail"] == "No run in progress"


class TestSignalEndpointsWithRun:
    """All signal POST endpoints push the correct signal when a run is active."""

    def setup_method(self):
        _set_running()
        endpoints.signals.push_signal.reset_mock()

    @pytest.mark.parametrize("path,expected_signal,expected_payload", _SIGNAL_ENDPOINTS)
    def test_pushes_correct_signal(self, path, expected_signal, expected_payload):
        resp = _client.post(path)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["signal"] == expected_signal
        assert data["delivery"] == "instant"

        if expected_payload is None:
            endpoints.signals.push_signal.assert_called_once_with(expected_signal)
        else:
            endpoints.signals.push_signal.assert_called_once_with(expected_signal, expected_payload)


# ===========================================================================
# POST /inject
# ===========================================================================

class TestInject:
    def setup_method(self):
        endpoints.signals.push_signal.reset_mock()

    def test_inject_409_when_idle(self):
        _set_idle()
        resp = _client.post("/inject", json={"payload": "do something"})
        assert resp.status_code == 409
        assert resp.json()["detail"] == "No run in progress"

    def test_inject_with_payload(self):
        _set_running()
        resp = _client.post("/inject", json={"payload": "refactor the auth module"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["signal"] == "inject"
        assert data["delivery"] == "instant"
        endpoints.signals.push_signal.assert_called_once_with("inject", "refactor the auth module")

    def test_inject_with_null_payload(self):
        _set_running()
        resp = _client.post("/inject", json={})
        assert resp.status_code == 200
        endpoints.signals.push_signal.assert_called_once_with("inject", None)

    def test_inject_no_body(self):
        """Omitting the body entirely uses the default InjectRequest (payload=None)."""
        _set_running()
        resp = _client.post("/inject")
        assert resp.status_code == 200
        endpoints.signals.push_signal.assert_called_once_with("inject", None)


# ===========================================================================
# POST /kill
# ===========================================================================

class TestKill:
    def setup_method(self):
        endpoints.db.finish_run.reset_mock()

    def test_kill_409_when_no_task(self):
        _set_idle()
        resp = _client.post("/kill")
        assert resp.status_code == 409
        assert resp.json()["detail"] == "No run in progress"

    def test_kill_409_when_task_but_no_run_id(self):
        endpoints.signals.current_task = MagicMock()
        endpoints.signals.current_run_id = None
        resp = _client.post("/kill")
        assert resp.status_code == 409

    def test_kill_cancels_task_and_returns_run_id(self):
        run_id = "run-kill-me"
        mock_task = MagicMock()
        mock_task.cancel = MagicMock()
        endpoints.signals.current_task = mock_task
        endpoints.signals.current_run_id = run_id

        with patch("asyncio.sleep", new_callable=AsyncMock):
            resp = _client.post("/kill")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["signal"] == "kill"
        assert data["run_id"] == run_id
        mock_task.cancel.assert_called_once()

    def test_kill_calls_db_finish_run(self):
        run_id = "run-db-finish"
        mock_task = MagicMock()
        mock_task.cancel = MagicMock()
        endpoints.signals.current_task = mock_task
        endpoints.signals.current_run_id = run_id

        with patch("asyncio.sleep", new_callable=AsyncMock):
            _client.post("/kill")

        endpoints.db.finish_run.assert_awaited_once_with(run_id=run_id, status="killed")

    def test_kill_clears_run_id(self):
        endpoints.signals.current_run_id = "run-clear"
        endpoints.signals.current_task = MagicMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            _client.post("/kill")

        assert endpoints.signals.current_run_id is None

    def test_kill_tolerates_db_failure(self):
        """If finish_run raises, the endpoint still returns 200 (best-effort)."""
        endpoints.db.finish_run.side_effect = Exception("db unavailable")
        run_id = "run-db-err"
        endpoints.signals.current_run_id = run_id
        endpoints.signals.current_task = MagicMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            resp = _client.post("/kill")

        assert resp.status_code == 200


# ===========================================================================
# GET /branches
# ===========================================================================

class TestBranches:
    def test_returns_sorted_unique_branches(self):
        endpoints.git_ops.setup_git_auth = MagicMock()
        endpoints.git_ops._run_git.return_value = (
            "origin/main\n"
            "origin/feature-a\n"
            "origin/feature-b\n"
            "origin/HEAD -> origin/main\n"
        )

        resp = _client.get("/branches")
        assert resp.status_code == 200
        branches = resp.json()
        assert "main" in branches
        assert "feature-a" in branches
        assert "feature-b" in branches
        # HEAD lines should be filtered out
        assert not any("HEAD" in b for b in branches)
        # Should be sorted
        assert branches == sorted(branches)

    def test_deduplicates_branches(self):
        endpoints.git_ops.setup_git_auth = MagicMock()
        endpoints.git_ops._run_git.return_value = "origin/main\norigin/main\n"

        resp = _client.get("/branches")
        branches = resp.json()
        assert branches.count("main") == 1

    def test_fallback_to_main_on_exception(self):
        endpoints.git_ops.setup_git_auth = MagicMock()
        endpoints.git_ops._run_git.side_effect = Exception("git not available")

        resp = _client.get("/branches")
        assert resp.status_code == 200
        assert resp.json() == ["main"]

    def test_fallback_on_auth_failure(self):
        endpoints.git_ops.setup_git_auth.side_effect = Exception("auth failed")

        resp = _client.get("/branches")
        assert resp.status_code == 200
        assert resp.json() == ["main"]


# ===========================================================================
# GET /diff/live
# ===========================================================================

class TestDiffLive:
    def setup_method(self):
        endpoints.git_ops.setup_git_auth = MagicMock()
        endpoints.git_ops.setup_git_auth.side_effect = None
        endpoints.git_ops.get_branch_diff_live.reset_mock()
        endpoints.git_ops.get_branch_diff_live.side_effect = None

    def test_idle_uses_main_as_base(self):
        _set_idle()
        endpoints.git_ops.get_branch_diff_live.return_value = [
            {"file": "a.py", "added": 10, "removed": 2},
        ]

        resp = _client.get("/diff/live")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_files"] == 1
        assert data["total_added"] == 10
        assert data["total_removed"] == 2
        endpoints.git_ops.get_branch_diff_live.assert_called_with("main")

    def test_running_queries_base_branch_from_db(self):
        _set_running("run-diff-live")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_row = {"base_branch": "develop"}
        mock_cursor.fetchone = AsyncMock(return_value=mock_row)
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        endpoints.db.get_db.return_value = mock_conn

        endpoints.git_ops.get_branch_diff_live.return_value = [
            {"file": "b.py", "added": 5, "removed": 1},
        ]

        resp = _client.get("/diff/live")
        assert resp.status_code == 200
        endpoints.git_ops.get_branch_diff_live.assert_called_with("develop")

    def test_running_falls_back_to_main_if_no_db_row(self):
        _set_running("run-no-row")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        endpoints.db.get_db.return_value = mock_conn

        endpoints.git_ops.get_branch_diff_live.return_value = []

        resp = _client.get("/diff/live")
        endpoints.git_ops.get_branch_diff_live.assert_called_with("main")

    def test_error_returns_fallback_payload(self):
        _set_idle()
        endpoints.git_ops.get_branch_diff_live.side_effect = Exception("git error")

        resp = _client.get("/diff/live")
        assert resp.status_code == 200
        data = resp.json()
        assert data["files"] == []
        assert "error" in data

    def test_totals_are_summed_correctly(self):
        _set_idle()
        endpoints.git_ops.get_branch_diff_live.return_value = [
            {"file": "x.py", "added": 3, "removed": 1},
            {"file": "y.py", "added": 7, "removed": 4},
        ]

        resp = _client.get("/diff/live")
        data = resp.json()
        assert data["total_added"] == 10
        assert data["total_removed"] == 5
        assert data["total_files"] == 2


# ===========================================================================
# GET /diff/{branch}
# ===========================================================================

class TestDiffBranch:
    def setup_method(self):
        endpoints.git_ops.setup_git_auth = MagicMock()
        endpoints.git_ops.setup_git_auth.side_effect = None
        endpoints.git_ops.get_branch_diff.reset_mock()
        endpoints.git_ops.get_branch_diff.side_effect = None

    def test_returns_diff_stats_for_branch(self):
        endpoints.git_ops.get_branch_diff.return_value = [
            {"file": "main.py", "added": 20, "removed": 5},
        ]

        resp = _client.get("/diff/my-feature")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_files"] == 1
        assert data["total_added"] == 20
        assert data["total_removed"] == 5
        endpoints.git_ops.get_branch_diff.assert_called_with("my-feature", "main")

    def test_uses_custom_base_query_param(self):
        endpoints.git_ops.get_branch_diff.return_value = []

        _client.get("/diff/my-feature?base=develop")
        endpoints.git_ops.get_branch_diff.assert_called_with("my-feature", "develop")

    def test_error_returns_fallback_payload(self):
        endpoints.git_ops.get_branch_diff.side_effect = Exception("no such branch")

        resp = _client.get("/diff/nonexistent-branch")
        assert resp.status_code == 200
        data = resp.json()
        assert data["files"] == []
        assert "error" in data

    def test_totals_are_summed_correctly(self):
        endpoints.git_ops.get_branch_diff.return_value = [
            {"file": "a.py", "added": 1, "removed": 0},
            {"file": "b.py", "added": 2, "removed": 3},
            {"file": "c.py", "added": 4, "removed": 5},
        ]

        resp = _client.get("/diff/some-branch")
        data = resp.json()
        assert data["total_added"] == 7
        assert data["total_removed"] == 8
        assert data["total_files"] == 3

    def test_branch_name_with_slash_is_not_routed(self):
        """FastAPI's {branch} path param does not capture slashes.

        A URL like /diff/user/topic-branch does not match the /diff/{branch}
        route because the second slash creates an unrecognised path segment.
        The endpoint returns 404 for such URLs — this documents the limitation
        so any future addition of a `path` type annotation is intentional.
        """
        endpoints.git_ops.get_branch_diff.return_value = []

        resp = _client.get("/diff/user/topic-branch")
        # The route is NOT matched; FastAPI returns 404 for multi-segment paths.
        assert resp.status_code == 404
        endpoints.git_ops.get_branch_diff.assert_not_called()


# ===========================================================================
# _on_task_done callback (unit test of the helper itself)
# ===========================================================================

class TestOnTaskDone:
    def test_clears_current_run_id_on_normal_completion(self):
        endpoints.signals.current_run_id = "run-done"
        task = MagicMock()
        task.exception.return_value = None

        endpoints._on_task_done(task)

        assert endpoints.signals.current_run_id is None

    def test_clears_current_run_id_on_exception(self):
        endpoints.signals.current_run_id = "run-crash"
        task = MagicMock()
        task.exception.return_value = RuntimeError("boom")

        endpoints._on_task_done(task)

        assert endpoints.signals.current_run_id is None

    def test_clears_current_run_id_on_cancellation(self):
        endpoints.signals.current_run_id = "run-cancelled"
        task = MagicMock()
        task.exception.side_effect = asyncio.CancelledError()

        endpoints._on_task_done(task)

        assert endpoints.signals.current_run_id is None
