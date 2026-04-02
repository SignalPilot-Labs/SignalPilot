"""Unit tests for the self-improve agent HTTP client."""

import httpx
import pytest

from signalpilot_mcp.agent_client import AgentClient


def _mock_transport(responses: dict[str, tuple[int, dict | list]]):
    """Create a mock transport that returns canned responses by path + method."""

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        # Try exact match with method prefix
        key = f"{method}:{path}"
        if key in responses:
            status, body = responses[key]
            return httpx.Response(status, json=body)
        # Fallback to path-only match (longest prefix)
        if path in responses:
            status, body = responses[path]
            return httpx.Response(status, json=body)
        matches = [(k, v) for k, v in responses.items() if ":" not in k and path.startswith(k)]
        if matches:
            key, (status, body) = max(matches, key=lambda x: len(x[0]))
            return httpx.Response(status, json=body)
        return httpx.Response(404, json={"detail": "Not found"})

    return httpx.MockTransport(handler)


@pytest.fixture
def client():
    transport = _mock_transport({
        "/api/agent/health": (200, {
            "status": "running",
            "current_run_id": "abc-123-def",
            "elapsed_minutes": 12.5,
            "time_remaining": "17m 30s",
            "session_unlocked": False,
        }),
        "POST:/api/agent/start": (200, {
            "ok": True,
            "run_id": "new-run-id-456",
            "prompt": "fix the tests",
            "max_budget_usd": 5.0,
            "duration_minutes": 30,
            "base_branch": "main",
        }),
        "POST:/api/agent/stop": (200, {"ok": True, "signal": "stop", "delivery": "instant"}),
        "POST:/api/agent/kill": (200, {"ok": True, "signal": "kill", "run_id": "abc-123"}),
        "POST:/api/agent/resume": (200, {"ok": True, "run_id": "abc-123", "resumed": True}),
        "/api/agent/branches": (200, ["main", "staging", "feature-xyz"]),
        "/api/runs": (200, [
            {
                "id": "run-1", "status": "completed", "branch_name": "improve-run-1",
                "total_cost_usd": 1.23, "total_input_tokens": 50000,
                "total_output_tokens": 10000, "pr_url": "https://github.com/org/repo/pull/1",
            },
            {
                "id": "run-2", "status": "running", "branch_name": "improve-run-2",
                "total_cost_usd": 0.45, "total_input_tokens": 20000,
                "total_output_tokens": 5000,
            },
        ]),
        "/api/runs/run-1": (200, {
            "id": "run-1", "status": "completed", "branch_name": "improve-run-1",
            "total_cost_usd": 1.23, "pr_url": "https://github.com/org/repo/pull/1",
        }),
        "/api/runs/run-1/tools": (200, [
            {"tool_name": "Read", "status": "ok", "ts": "2024-01-01T00:00:00", "duration_ms": 5},
            {"tool_name": "Edit", "status": "ok", "ts": "2024-01-01T00:00:01", "duration_ms": 12},
        ]),
        "/api/runs/run-1/audit": (200, [
            {"event_type": "llm_text", "data": {"text": "Looking at the code...", "agent_role": "worker"}},
            {"event_type": "run_started", "data": {"branch": "improve-run-1"}},
        ]),
        "/api/runs/run-1/diff": (200, {
            "files": [
                {"file": "src/main.py", "added": 10, "removed": 3},
                {"file": "tests/test_main.py", "added": 25, "removed": 0},
            ],
            "total_files": 2,
            "total_added": 35,
            "total_removed": 3,
        }),
        "POST:/api/runs/run-2/pause": (200, {"ok": True, "signal": "pause"}),
        "POST:/api/runs/run-2/resume": (200, {"ok": True, "signal": "resume"}),
        "POST:/api/runs/run-2/inject": (200, {"ok": True, "signal": "inject", "prompt_length": 15}),
        "POST:/api/runs/run-2/stop": (200, {"ok": True, "signal": "stop", "reason": "done"}),
        "POST:/api/runs/run-2/unlock": (200, {"ok": True, "signal": "unlock"}),
    })
    c = AgentClient("http://test:3401")
    c._client = httpx.AsyncClient(transport=transport, base_url="http://test:3401")
    return c


@pytest.mark.asyncio
async def test_agent_health(client):
    data = await client.agent_health()
    assert data["status"] == "running"
    assert data["current_run_id"] == "abc-123-def"


@pytest.mark.asyncio
async def test_start_run(client):
    data = await client.start_run(prompt="fix the tests", duration_minutes=30, max_budget_usd=5.0)
    assert data["ok"] is True
    assert data["run_id"] == "new-run-id-456"


@pytest.mark.asyncio
async def test_stop_agent(client):
    data = await client.stop_agent()
    assert data["ok"] is True


@pytest.mark.asyncio
async def test_kill_agent(client):
    data = await client.kill_agent()
    assert data["ok"] is True
    assert data["run_id"] == "abc-123"


@pytest.mark.asyncio
async def test_resume_run(client):
    data = await client.resume_run("abc-123")
    assert data["resumed"] is True


@pytest.mark.asyncio
async def test_list_branches(client):
    branches = await client.list_branches()
    assert "main" in branches
    assert len(branches) == 3


@pytest.mark.asyncio
async def test_list_runs(client):
    runs = await client.list_runs()
    assert len(runs) == 2
    assert runs[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_get_run(client):
    run = await client.get_run("run-1")
    assert run["id"] == "run-1"
    assert run["pr_url"] == "https://github.com/org/repo/pull/1"


@pytest.mark.asyncio
async def test_get_tool_calls(client):
    calls = await client.get_tool_calls("run-1")
    assert len(calls) == 2
    assert calls[0]["tool_name"] == "Read"


@pytest.mark.asyncio
async def test_get_run_audit(client):
    entries = await client.get_run_audit("run-1")
    assert len(entries) == 2
    assert entries[0]["event_type"] == "llm_text"


@pytest.mark.asyncio
async def test_get_run_diff(client):
    diff = await client.get_run_diff("run-1")
    assert diff["total_files"] == 2
    assert diff["total_added"] == 35


@pytest.mark.asyncio
async def test_pause_run(client):
    data = await client.pause_run("run-2")
    assert data["signal"] == "pause"


@pytest.mark.asyncio
async def test_resume_run_signal(client):
    data = await client.resume_run_signal("run-2")
    assert data["signal"] == "resume"


@pytest.mark.asyncio
async def test_inject_prompt(client):
    data = await client.inject_prompt("run-2", "focus on tests")
    assert data["signal"] == "inject"
    assert data["prompt_length"] == 15


@pytest.mark.asyncio
async def test_stop_run(client):
    data = await client.stop_run("run-2", "done for now")
    assert data["signal"] == "stop"


@pytest.mark.asyncio
async def test_unlock_run(client):
    data = await client.unlock_run("run-2")
    assert data["signal"] == "unlock"
