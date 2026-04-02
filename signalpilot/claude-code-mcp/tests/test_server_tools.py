"""Unit tests for the MCP server tool functions."""

import json
from unittest.mock import AsyncMock, patch

import pytest

# Patch the client before importing server tools
from signalpilot_mcp import server


@pytest.fixture(autouse=True)
def mock_client():
    """Replace the HTTP client with a mock for all tests."""
    mock = AsyncMock()
    with patch.object(server, "_get_client", return_value=mock):
        yield mock


@pytest.mark.asyncio
async def test_signalpilot_health_ok(mock_client):
    mock_client.health.return_value = {"status": "healthy", "connections": 3}
    result = await server.signalpilot_health()
    assert "healthy" in result
    assert "Connections: 3" in result


@pytest.mark.asyncio
async def test_signalpilot_health_unreachable(mock_client):
    mock_client.health.side_effect = Exception("Connection refused")
    result = await server.signalpilot_health()
    assert "unreachable" in result


@pytest.mark.asyncio
async def test_query_database_formats_table(mock_client):
    mock_client.query.return_value = {
        "rows": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
        "row_count": 2,
        "execution_ms": 8.3,
        "cache_hit": False,
    }
    result = await server.query_database("prod", "SELECT * FROM users")
    assert "Alice" in result
    assert "Bob" in result
    assert "2 rows" in result
    assert "8ms" in result


@pytest.mark.asyncio
async def test_query_database_cache_hit(mock_client):
    mock_client.query.return_value = {
        "rows": [{"count": 42}],
        "row_count": 1,
        "execution_ms": 0.1,
        "cache_hit": True,
    }
    result = await server.query_database("prod", "SELECT count(*) FROM t")
    assert "cache hit" in result


@pytest.mark.asyncio
async def test_list_connections_empty(mock_client):
    mock_client.list_connections.return_value = []
    result = await server.list_connections()
    assert "No database connections" in result


@pytest.mark.asyncio
async def test_list_connections_with_data(mock_client):
    mock_client.list_connections.return_value = [
        {"name": "prod", "db_type": "postgres", "host": "db.example.com", "port": 5432, "database": "app"},
    ]
    result = await server.list_connections()
    assert "prod" in result
    assert "postgres" in result


@pytest.mark.asyncio
async def test_add_connection(mock_client):
    mock_client.create_connection.return_value = {"name": "staging", "db_type": "postgres"}
    result = await server.add_connection("staging", "postgres", "db.local", 5432, "app", "user", "pass")
    assert "staging" in result
    assert "created" in result


@pytest.mark.asyncio
async def test_remove_connection(mock_client):
    mock_client.delete_connection.return_value = {}
    result = await server.remove_connection("old-db")
    assert "old-db" in result
    assert "removed" in result


@pytest.mark.asyncio
async def test_test_connection(mock_client):
    mock_client.test_connection.return_value = {"status": "ok", "latency_ms": 5.2}
    result = await server.test_connection("prod")
    assert "prod" in result
    assert "ok" in result


@pytest.mark.asyncio
async def test_audit_log_empty(mock_client):
    mock_client.audit_log.return_value = []
    result = await server.audit_log()
    assert "No audit entries" in result


@pytest.mark.asyncio
async def test_audit_log_with_entries(mock_client):
    mock_client.audit_log.return_value = [
        {"event_type": "query", "connection_name": "prod", "sql": "SELECT 1", "blocked": False},
        {"event_type": "block", "connection_name": "prod", "sql": "DROP TABLE users", "blocked": True},
    ]
    result = await server.audit_log()
    assert "[query]" in result
    assert "[BLOCKED]" in result
    assert "DROP TABLE" in result


@pytest.mark.asyncio
async def test_check_budget(mock_client):
    mock_client.get_budget.return_value = {
        "session_id": "default",
        "budget_usd": 10.0,
        "spent_usd": 1.5,
        "remaining_usd": 8.5,
        "query_count": 25,
    }
    result = await server.check_budget()
    assert "$10.00" in result
    assert "$1.5000" in result
    assert "25" in result


@pytest.mark.asyncio
async def test_cache_stats(mock_client):
    mock_client.cache_stats.return_value = {
        "entries": 12, "max_entries": 1000,
        "ttl_seconds": 300, "hits": 50, "misses": 150, "hit_rate": 0.25,
    }
    result = await server.cache_stats()
    assert "12 / 1000" in result
    assert "25.0%" in result


@pytest.mark.asyncio
async def test_get_settings(mock_client):
    mock_client.get_settings.return_value = {
        "default_row_limit": 10000,
        "sandbox_manager_url": "http://localhost:8180",
    }
    result = await server.get_settings()
    assert "default_row_limit" in result
    assert "10000" in result


@pytest.mark.asyncio
async def test_update_settings(mock_client):
    mock_client.update_settings.return_value = {"default_row_limit": 5000}
    result = await server.update_settings('{"default_row_limit": 5000}')
    assert "updated" in result.lower()
    assert "5000" in result


@pytest.mark.asyncio
async def test_update_settings_invalid_json(mock_client):
    result = await server.update_settings("not json")
    assert "Invalid JSON" in result


@pytest.mark.asyncio
async def test_list_sandboxes_empty(mock_client):
    mock_client.list_sandboxes.return_value = []
    result = await server.list_sandboxes()
    assert "No active sandboxes" in result


@pytest.mark.asyncio
async def test_connection_health_single(mock_client):
    mock_client.get_connection_health.return_value = {
        "connection_name": "prod", "db_type": "postgres", "status": "healthy",
        "latency_p50_ms": 5, "latency_p95_ms": 12, "latency_p99_ms": 25,
        "error_rate": 0.01,
    }
    result = await server.connection_health("prod")
    assert "prod" in result
    assert "HEALTHY" in result
    assert "p50=5ms" in result
