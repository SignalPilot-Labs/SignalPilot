"""Unit tests for the self-improve agent MCP server tools."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from signalpilot_mcp import server


@pytest.fixture(autouse=True)
def mock_agent_client():
    """Replace the agent HTTP client with a mock for all tests."""
    mock = AsyncMock()
    with patch.object(server, "_get_agent_client", return_value=mock):
        yield mock


@pytest.mark.asyncio
async def test_agent_health_running(mock_agent_client):
    mock_agent_client.agent_health.return_value = {
        "status": "running",
        "current_run_id": "abc-123-def-456",
        "elapsed_minutes": 12.5,
        "time_remaining": "17m 30s",
        "session_unlocked": False,
    }
    result = await server.agent_health()
    assert "RUNNING" in result
    assert "abc-123-def-" in result
    assert "12m" in result
    assert "17m 30s" in result


@pytest.mark.asyncio
async def test_agent_health_idle(mock_agent_client):
    mock_agent_client.agent_health.return_value = {"status": "idle", "current_run_id": None}
    result = await server.agent_health()
    assert "IDLE" in result


@pytest.mark.asyncio
async def test_agent_health_unreachable(mock_agent_client):
    mock_agent_client.agent_health.side_effect = Exception("Connection refused")
    result = await server.agent_health()
    assert "unreachable" in result


@pytest.mark.asyncio
async def test_start_improvement_run(mock_agent_client):
    mock_agent_client.start_run.return_value = {
        "ok": True,
        "run_id": "new-run-123",
        "prompt": "improve test coverage",
        "max_budget_usd": 5.0,
        "duration_minutes": 30,
        "base_branch": "main",
    }
    result = await server.start_improvement_run(
        prompt="improve test coverage",
        duration_minutes=30,
        max_budget_usd=5.0,
    )
    assert "started" in result
    assert "new-run-123" in result
    assert "improve test coverage" in result
    assert "30m" in result


@pytest.mark.asyncio
async def test_start_run_already_running(mock_agent_client):
    mock_agent_client.start_run.side_effect = Exception("Run already in progress")
    result = await server.start_improvement_run(prompt="test")
    assert "Error" in result


@pytest.mark.asyncio
async def test_resume_improvement_run(mock_agent_client):
    mock_agent_client.resume_run.return_value = {"ok": True}
    result = await server.resume_improvement_run("run-abc-123")
    assert "run-abc-123" in result
    assert "resumed" in result


@pytest.mark.asyncio
async def test_stop_improvement_run_with_id(mock_agent_client):
    mock_agent_client.stop_run.return_value = {"ok": True, "signal": "stop"}
    result = await server.stop_improvement_run(run_id="run-123", reason="done")
    assert "Stop signal sent" in result
    mock_agent_client.stop_run.assert_called_once_with("run-123", "done")


@pytest.mark.asyncio
async def test_stop_improvement_run_instant(mock_agent_client):
    mock_agent_client.stop_agent.return_value = {"ok": True}
    result = await server.stop_improvement_run()
    assert "Stop signal sent" in result
    mock_agent_client.stop_agent.assert_called_once()


@pytest.mark.asyncio
async def test_kill_improvement_run(mock_agent_client):
    mock_agent_client.kill_agent.return_value = {"ok": True, "run_id": "abc-123-456"}
    result = await server.kill_improvement_run()
    assert "killed" in result
    assert "No PR" in result


@pytest.mark.asyncio
async def test_list_improvement_runs(mock_agent_client):
    mock_agent_client.list_runs.return_value = [
        {"id": "run-1", "status": "completed", "branch_name": "br-1", "total_cost_usd": 1.23, "pr_url": "https://github.com/org/repo/pull/1"},
        {"id": "run-2", "status": "running", "branch_name": "br-2", "total_cost_usd": 0.5},
    ]
    result = await server.list_improvement_runs()
    assert "run-1" in result
    assert "COMPLETED" in result
    assert "$1.23" in result
    assert "run-2" in result
    assert "RUNNING" in result


@pytest.mark.asyncio
async def test_list_improvement_runs_empty(mock_agent_client):
    mock_agent_client.list_runs.return_value = []
    result = await server.list_improvement_runs()
    assert "No improvement runs" in result


@pytest.mark.asyncio
async def test_get_improvement_run(mock_agent_client):
    mock_agent_client.get_run.return_value = {
        "id": "run-1", "status": "completed", "branch_name": "br-1",
        "total_cost_usd": 1.23, "pr_url": "https://github.com/org/repo/pull/1",
    }
    result = await server.get_improvement_run("run-1")
    assert "run-1" in result
    assert "$1.23" in result
    assert "github.com" in result


@pytest.mark.asyncio
async def test_get_run_tool_calls(mock_agent_client):
    mock_agent_client.get_tool_calls.return_value = [
        {"tool_name": "Read", "status": "ok", "duration_ms": 5},
        {"tool_name": "Edit", "status": "ok", "duration_ms": 12},
    ]
    result = await server.get_run_tool_calls("run-1")
    assert "Read" in result
    assert "Edit" in result
    assert "5ms" in result


@pytest.mark.asyncio
async def test_get_run_tool_calls_empty(mock_agent_client):
    mock_agent_client.get_tool_calls.return_value = []
    result = await server.get_run_tool_calls("run-1")
    assert "No tool calls" in result


@pytest.mark.asyncio
async def test_get_run_output(mock_agent_client):
    mock_agent_client.get_run_audit.return_value = [
        {"event_type": "llm_text", "data": {"text": "Looking at the code...", "agent_role": "worker"}},
        {"event_type": "run_started", "data": {"branch": "br-1"}},
        {"event_type": "usage", "data": {"total_input_tokens": 50000, "total_output_tokens": 10000}},
    ]
    result = await server.get_run_output("run-1")
    assert "[worker]" in result
    assert "Looking at the code" in result
    assert "50,000 in" in result


@pytest.mark.asyncio
async def test_get_run_output_empty(mock_agent_client):
    mock_agent_client.get_run_audit.return_value = []
    result = await server.get_run_output("run-1")
    assert "No audit entries" in result


@pytest.mark.asyncio
async def test_get_run_diff(mock_agent_client):
    mock_agent_client.get_run_diff.return_value = {
        "files": [
            {"file": "src/main.py", "added": 10, "removed": 3},
            {"file": "tests/test_main.py", "added": 25, "removed": 0},
        ],
        "total_files": 2,
        "total_added": 35,
        "total_removed": 3,
    }
    result = await server.get_run_diff("run-1")
    assert "src/main.py" in result
    assert "+35/-3" in result


@pytest.mark.asyncio
async def test_get_run_diff_empty(mock_agent_client):
    mock_agent_client.get_run_diff.return_value = {"files": []}
    result = await server.get_run_diff("run-1")
    assert "No changes" in result


@pytest.mark.asyncio
async def test_pause_improvement_run(mock_agent_client):
    mock_agent_client.pause_run.return_value = {"ok": True}
    result = await server.pause_improvement_run("run-123")
    assert "paused" in result


@pytest.mark.asyncio
async def test_resume_improvement_signal(mock_agent_client):
    mock_agent_client.resume_run_signal.return_value = {"ok": True}
    result = await server.resume_improvement_signal("run-123")
    assert "resumed" in result


@pytest.mark.asyncio
async def test_inject_agent_prompt(mock_agent_client):
    mock_agent_client.inject_prompt.return_value = {"ok": True, "prompt_length": 20}
    result = await server.inject_agent_prompt("run-123", "focus on security")
    assert "injected" in result
    assert "20 chars" in result


@pytest.mark.asyncio
async def test_inject_agent_prompt_empty(mock_agent_client):
    result = await server.inject_agent_prompt("run-123", "")
    assert "Error" in result


@pytest.mark.asyncio
async def test_unlock_improvement_run(mock_agent_client):
    mock_agent_client.unlock_run.return_value = {"ok": True}
    result = await server.unlock_improvement_run("run-123")
    assert "unlocked" in result


@pytest.mark.asyncio
async def test_list_agent_branches(mock_agent_client):
    mock_agent_client.list_branches.return_value = ["main", "staging", "feature-xyz"]
    result = await server.list_agent_branches()
    assert "main" in result
    assert "staging" in result
    assert "feature-xyz" in result


@pytest.mark.asyncio
async def test_list_agent_branches_empty(mock_agent_client):
    mock_agent_client.list_branches.return_value = []
    result = await server.list_agent_branches()
    assert "No branches" in result


# ── Edge cases ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_run_null_run_id(mock_agent_client):
    """When the agent hasn't initialized yet, run_id is None."""
    mock_agent_client.start_run.return_value = {
        "ok": True,
        "run_id": None,
        "prompt": "test",
        "max_budget_usd": 0,
        "duration_minutes": 30,
        "base_branch": "main",
    }
    result = await server.start_improvement_run(prompt="test")
    assert "started" in result
    assert "initializing" in result
    assert "agent_health" in result


@pytest.mark.asyncio
async def test_start_run_missing_run_id(mock_agent_client):
    """When run_id key is absent entirely."""
    mock_agent_client.start_run.return_value = {"ok": True}
    result = await server.start_improvement_run()
    assert "initializing" in result


@pytest.mark.asyncio
async def test_resume_latest_run_finds_stopped(mock_agent_client):
    mock_agent_client.list_runs.return_value = [
        {"id": "run-3", "status": "running"},
        {"id": "run-2", "status": "stopped", "custom_prompt": "fix tests"},
        {"id": "run-1", "status": "completed"},
    ]
    mock_agent_client.resume_run.return_value = {"ok": True}
    result = await server.resume_latest_run()
    assert "run-2" in result
    assert "stopped" in result
    assert "fix tests" in result
    mock_agent_client.resume_run.assert_called_once_with("run-2", 0)


@pytest.mark.asyncio
async def test_resume_latest_run_finds_rate_limited(mock_agent_client):
    mock_agent_client.list_runs.return_value = [
        {"id": "run-5", "status": "rate_limited", "custom_prompt": ""},
        {"id": "run-4", "status": "completed"},
    ]
    mock_agent_client.resume_run.return_value = {"ok": True}
    result = await server.resume_latest_run()
    assert "run-5" in result
    assert "rate_limited" in result


@pytest.mark.asyncio
async def test_resume_latest_run_no_resumable(mock_agent_client):
    mock_agent_client.list_runs.return_value = [
        {"id": "run-1", "status": "completed"},
        {"id": "run-2", "status": "error"},
    ]
    result = await server.resume_latest_run()
    assert "No resumable runs" in result
    assert "completed" in result


@pytest.mark.asyncio
async def test_resume_latest_run_empty(mock_agent_client):
    mock_agent_client.list_runs.return_value = []
    result = await server.resume_latest_run()
    assert "No resumable runs" in result


@pytest.mark.asyncio
async def test_resume_latest_run_with_budget(mock_agent_client):
    mock_agent_client.list_runs.return_value = [
        {"id": "run-7", "status": "stopped"},
    ]
    mock_agent_client.resume_run.return_value = {"ok": True}
    result = await server.resume_latest_run(max_budget_usd=10.0)
    mock_agent_client.resume_run.assert_called_once_with("run-7", 10.0)
