"""Tests for the monitor's parallel run proxy endpoints (/api/parallel/*)."""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from httpx import ASGITransport

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def client():
    """Create an async test client for the monitor FastAPI app."""
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


@pytest.fixture
def mock_agent():
    """Mock outgoing HTTP calls to the agent container."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        yield mock_client, mock_response


# ---------------------------------------------------------------------------
# List parallel runs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_parallel_runs_success(client, mock_agent):
    """Proxies GET /parallel/runs to agent and returns the response."""
    mock_client, mock_response = mock_agent
    mock_response.json.return_value = {"runs": [{"id": "run-1", "status": "running"}]}

    resp = await client.get("/api/parallel/runs")

    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert data["runs"][0]["id"] == "run-1"
    mock_client.get.assert_called_once()
    call_url = mock_client.get.call_args[0][0]
    assert "/parallel/runs" in call_url


@pytest.mark.asyncio
async def test_list_parallel_runs_agent_down(client):
    """Returns an error dict (not a 5xx) when the agent is unreachable."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = await client.get("/api/parallel/runs")

    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert data["runs"] == []


# ---------------------------------------------------------------------------
# Start parallel run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_parallel_run_success(client, mock_agent):
    """Decrypts credentials from settings DB and forwards to agent."""
    mock_client, mock_response = mock_agent
    mock_response.status_code = 200
    mock_response.json.return_value = {"run_id": "par-abc", "status": "started"}

    # Simulate settings rows returning a credential value
    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value={"value": "plaintext-token", "encrypted": 0})

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_cursor)

    with patch("monitor.app._get_db", new_callable=AsyncMock, return_value=mock_conn):
        resp = await client.post(
            "/api/parallel/start",
            json={"prompt": "improve tests", "max_budget_usd": 1.0, "base_branch": "main"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "par-abc"
    mock_client.post.assert_called_once()
    posted_url = mock_client.post.call_args[0][0]
    assert "/parallel/start" in posted_url


@pytest.mark.asyncio
async def test_start_parallel_run_agent_error(client):
    """Returns 502 when the agent raises a connection error."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = await client.post("/api/parallel/start", json={})

    assert resp.status_code == 502
    assert "unreachable" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_start_parallel_run_conflict(client):
    """Returns 409 when the agent reports a run is already in progress."""
    mock_response = MagicMock()
    mock_response.status_code = 409
    mock_response.json.return_value = {"detail": "Run already in progress"}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = await client.post("/api/parallel/start", json={})

    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Parallel status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parallel_status_success(client, mock_agent):
    """Returns the status payload from the agent."""
    mock_client, mock_response = mock_agent
    mock_response.json.return_value = {"status": "idle", "slots": 4, "active": 1}

    resp = await client.get("/api/parallel/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "idle"
    assert data["slots"] == 4
    mock_client.get.assert_called_once()
    assert "/parallel/status" in mock_client.get.call_args[0][0]


@pytest.mark.asyncio
async def test_parallel_status_agent_down(client):
    """Returns an unreachable status dict when the agent cannot be reached."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = await client.get("/api/parallel/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unreachable"
    assert "error" in data


# ---------------------------------------------------------------------------
# Run operations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_parallel_run(client, mock_agent):
    """Proxies stop signal to agent for the given run ID."""
    mock_client, mock_response = mock_agent
    mock_response.json.return_value = {"ok": True, "run_id": "run-1"}

    resp = await client.post("/api/parallel/runs/run-1/stop", json={"payload": "test stop"})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_client.post.assert_called_once()
    posted_url = mock_client.post.call_args[0][0]
    assert "run-1/stop" in posted_url


@pytest.mark.asyncio
async def test_kill_parallel_run(client, mock_agent):
    """Proxies kill signal to agent for the given run ID."""
    mock_client, mock_response = mock_agent
    mock_response.json.return_value = {"ok": True}

    resp = await client.post("/api/parallel/runs/run-2/kill")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    posted_url = mock_client.post.call_args[0][0]
    assert "run-2/kill" in posted_url


@pytest.mark.asyncio
async def test_pause_parallel_run(client, mock_agent):
    """Proxies pause signal to agent for the given run ID."""
    mock_client, mock_response = mock_agent
    mock_response.json.return_value = {"ok": True, "signal": "pause"}

    resp = await client.post("/api/parallel/runs/run-3/pause")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    posted_url = mock_client.post.call_args[0][0]
    assert "run-3/pause" in posted_url


@pytest.mark.asyncio
async def test_resume_parallel_run(client, mock_agent):
    """Proxies resume signal to agent for the given run ID."""
    mock_client, mock_response = mock_agent
    mock_response.json.return_value = {"ok": True, "signal": "resume"}

    resp = await client.post("/api/parallel/runs/run-4/resume")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    posted_url = mock_client.post.call_args[0][0]
    assert "run-4/resume" in posted_url


@pytest.mark.asyncio
async def test_inject_parallel_run(client, mock_agent):
    """Proxies inject with payload to agent for the given run ID."""
    mock_client, mock_response = mock_agent
    mock_response.json.return_value = {"ok": True, "signal": "inject"}

    resp = await client.post(
        "/api/parallel/runs/run-5/inject",
        json={"payload": "please focus on performance"},
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_client.post.assert_called_once()
    posted_url = mock_client.post.call_args[0][0]
    assert "run-5/inject" in posted_url
    posted_body = mock_client.post.call_args.kwargs.get("json", {})
    assert posted_body.get("payload") == "please focus on performance"


@pytest.mark.asyncio
async def test_inject_parallel_run_no_payload(client, mock_agent):
    """Returns 400 when inject is called without a payload."""
    resp = await client.post("/api/parallel/runs/run-5/inject", json={})

    assert resp.status_code == 400
    assert "payload" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_unlock_parallel_run(client, mock_agent):
    """Proxies unlock signal to agent for the given run ID."""
    mock_client, mock_response = mock_agent
    mock_response.json.return_value = {"ok": True, "signal": "unlock"}

    resp = await client.post("/api/parallel/runs/run-6/unlock")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    posted_url = mock_client.post.call_args[0][0]
    assert "run-6/unlock" in posted_url


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cleanup_parallel(client, mock_agent):
    """Proxies cleanup request to agent and returns its response."""
    mock_client, mock_response = mock_agent
    mock_response.json.return_value = {"cleaned": 3, "remaining": 1}

    resp = await client.post("/api/parallel/cleanup")

    assert resp.status_code == 200
    data = resp.json()
    assert data["cleaned"] == 3
    mock_client.post.assert_called_once()
    posted_url = mock_client.post.call_args[0][0]
    assert "/parallel/cleanup" in posted_url
