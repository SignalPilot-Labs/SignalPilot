"""Tests for the --check and --version CLI modes."""

import asyncio
from io import StringIO
from unittest.mock import AsyncMock, patch

import pytest

from signalpilot_mcp import server, __version__


@pytest.fixture
def mock_clients():
    """Mock both gateway and agent clients."""
    gw = AsyncMock()
    ag = AsyncMock()
    with patch.object(server, "_get_client", return_value=gw), \
         patch.object(server, "_get_agent_client", return_value=ag):
        yield gw, ag


@pytest.mark.asyncio
async def test_check_all_pass(mock_clients, capsys):
    gw, ag = mock_clients
    gw.health.return_value = {"status": "healthy"}
    gw.list_connections.return_value = [{"name": "prod"}]
    ag.agent_health.return_value = {"status": "idle", "current_run_id": None}
    ag.list_runs.return_value = [{"id": "run-1"}, {"id": "run-2"}]

    ok = await server._run_check()

    assert ok is True
    out = capsys.readouterr().out
    assert "All 4 checks passed" in out
    assert "[PASS] Gateway health: healthy" in out
    assert "[PASS] Gateway connections: 1 configured" in out
    assert "[PASS] Agent health: idle" in out
    assert "[PASS] Monitor runs: 2 in history" in out


@pytest.mark.asyncio
async def test_check_all_fail(mock_clients, capsys):
    gw, ag = mock_clients
    gw.health.side_effect = Exception("Connection refused")
    gw.list_connections.side_effect = Exception("Connection refused")
    ag.agent_health.side_effect = Exception("Connection refused")
    ag.list_runs.side_effect = Exception("Connection refused")

    ok = await server._run_check()

    assert ok is False
    out = capsys.readouterr().out
    assert "0 passed, 4 failed" in out
    assert "[FAIL] Gateway health" in out
    assert "[FAIL] Gateway connections" in out
    assert "[FAIL] Agent health" in out
    assert "[FAIL] Monitor runs" in out


@pytest.mark.asyncio
async def test_check_partial_failure(mock_clients, capsys):
    gw, ag = mock_clients
    gw.health.return_value = {"status": "healthy"}
    gw.list_connections.return_value = []
    ag.agent_health.side_effect = Exception("Connection refused")
    ag.list_runs.side_effect = Exception("Connection refused")

    ok = await server._run_check()

    assert ok is False
    out = capsys.readouterr().out
    assert "2 passed, 2 failed" in out
    assert "[PASS] Gateway health" in out
    assert "[FAIL] Agent health" in out


@pytest.mark.asyncio
async def test_check_shows_running_agent(mock_clients, capsys):
    gw, ag = mock_clients
    gw.health.return_value = {"status": "healthy"}
    gw.list_connections.return_value = []
    ag.agent_health.return_value = {
        "status": "running",
        "current_run_id": "abc-123-def-456-ghi",
    }
    ag.list_runs.return_value = [{"id": "abc-123"}]

    ok = await server._run_check()

    assert ok is True
    out = capsys.readouterr().out
    assert "running (run abc-123-def-" in out


@pytest.mark.asyncio
async def test_check_shows_config(mock_clients, capsys):
    gw, ag = mock_clients
    gw.health.return_value = {"status": "healthy"}
    gw.list_connections.return_value = []
    ag.agent_health.return_value = {"status": "idle"}
    ag.list_runs.return_value = []

    await server._run_check()

    out = capsys.readouterr().out
    assert "Gateway URL:" in out
    assert "Monitor URL:" in out
    assert "Tools:" in out
    assert "37" in out  # current tool count


def test_version_flag(capsys):
    """Test that --version prints the version and returns."""
    with patch("sys.argv", ["signalpilot-mcp-remote", "--version"]):
        server.main()
    out = capsys.readouterr().out
    assert f"signalpilot-mcp {__version__}" in out


def test_check_flag_exit_code_success(mock_clients):
    """Test that --check exits with code 0 on success."""
    gw, ag = mock_clients
    gw.health.return_value = {"status": "healthy"}
    gw.list_connections.return_value = []
    ag.agent_health.return_value = {"status": "idle"}
    ag.list_runs.return_value = []

    with patch("sys.argv", ["signalpilot-mcp-remote", "--check"]):
        with pytest.raises(SystemExit) as exc_info:
            server.main()
        assert exc_info.value.code == 0


def test_check_flag_exit_code_failure(mock_clients):
    """Test that --check exits with code 1 on failure."""
    gw, ag = mock_clients
    gw.health.side_effect = Exception("down")
    gw.list_connections.side_effect = Exception("down")
    ag.agent_health.side_effect = Exception("down")
    ag.list_runs.side_effect = Exception("down")

    with patch("sys.argv", ["signalpilot-mcp-remote", "--check"]):
        with pytest.raises(SystemExit) as exc_info:
            server.main()
        assert exc_info.value.code == 1
