"""Unit tests for the SignalPilot MCP HTTP client."""

import json

import httpx
import pytest

from signalpilot_mcp.client import SignalPilotClient


def _mock_transport(responses: dict[str, tuple[int, dict]]):
    """Create a mock transport that returns canned responses by path."""

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        # Try exact match first
        if path in responses:
            status, body = responses[path]
            return httpx.Response(status, json=body)
        # Then longest prefix match
        matches = [(k, v) for k, v in responses.items() if path.startswith(k)]
        if matches:
            key, (status, body) = max(matches, key=lambda x: len(x[0]))
            return httpx.Response(status, json=body)
        return httpx.Response(404, json={"detail": "Not found"})

    return httpx.MockTransport(handler)


@pytest.fixture
def client():
    transport = _mock_transport({
        "/health": (200, {"status": "healthy", "connections": 2}),
        "/api/connections": (200, [
            {"name": "prod", "db_type": "postgres", "host": "db.example.com", "port": 5432, "database": "app"},
        ]),
        "/api/query": (200, {
            "rows": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
            "row_count": 2,
            "tables": ["users"],
            "execution_ms": 12.5,
            "sql_executed": "SELECT * FROM users LIMIT 1000",
            "cache_hit": False,
        }),
        "/api/audit": (200, {"entries": [
            {"event_type": "query", "connection_name": "prod", "sql": "SELECT 1"},
        ], "total": 1}),
        "/api/cache/stats": (200, {
            "entries": 5, "max_entries": 1000, "ttl_seconds": 300,
            "hits": 10, "misses": 40, "hit_rate": 0.2,
        }),
        "/api/settings": (200, {
            "sandbox_manager_url": "http://localhost:8180",
            "default_row_limit": 10000,
            "default_budget_usd": 10.0,
        }),
        "/api/connections/health": (200, {"connections": [
            {"connection_name": "prod", "db_type": "postgres", "status": "healthy",
             "latency_p50_ms": 5, "latency_p95_ms": 12, "latency_p99_ms": 25,
             "error_rate": 0.01, "sample_count": 100, "window_seconds": 300,
             "successes": 99, "failures": 1},
        ]}),
        "/api/sandboxes": (200, []),
        "/api/budget/default": (200, {
            "session_id": "default", "budget_usd": 10.0,
            "spent_usd": 0.5, "remaining_usd": 9.5, "query_count": 15,
        }),
    })
    c = SignalPilotClient("http://test:3300")
    c._client = httpx.AsyncClient(transport=transport, base_url="http://test:3300")
    return c


@pytest.mark.asyncio
async def test_health(client):
    data = await client.health()
    assert data["status"] == "healthy"
    assert data["connections"] == 2


@pytest.mark.asyncio
async def test_list_connections(client):
    conns = await client.list_connections()
    assert len(conns) == 1
    assert conns[0]["name"] == "prod"
    assert conns[0]["db_type"] == "postgres"


@pytest.mark.asyncio
async def test_query(client):
    data = await client.query("prod", "SELECT * FROM users")
    assert data["row_count"] == 2
    assert len(data["rows"]) == 2
    assert data["rows"][0]["name"] == "Alice"
    assert data["cache_hit"] is False


@pytest.mark.asyncio
async def test_audit_log_unwraps_entries(client):
    entries = await client.audit_log(limit=5)
    assert len(entries) == 1
    assert entries[0]["event_type"] == "query"


@pytest.mark.asyncio
async def test_cache_stats(client):
    data = await client.cache_stats()
    assert data["entries"] == 5
    assert data["hit_rate"] == 0.2


@pytest.mark.asyncio
async def test_settings(client):
    data = await client.get_settings()
    assert data["default_row_limit"] == 10000


@pytest.mark.asyncio
async def test_all_health_unwraps_connections(client):
    data = await client.get_all_health()
    assert len(data) == 1
    assert data[0]["status"] == "healthy"


@pytest.mark.asyncio
async def test_list_sandboxes(client):
    data = await client.list_sandboxes()
    assert data == []


@pytest.mark.asyncio
async def test_budget(client):
    data = await client.get_budget("default")
    assert data["spent_usd"] == 0.5
    assert data["remaining_usd"] == 9.5


@pytest.mark.asyncio
async def test_api_key_header():
    """Verify that the API key is sent as a Bearer token."""
    captured_headers = {}

    async def capture_handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(capture_handler)
    c = SignalPilotClient("http://test:3300", api_key="sk-test-123")
    c._client = httpx.AsyncClient(
        transport=transport,
        base_url="http://test:3300",
        headers={"Authorization": "Bearer sk-test-123"},
    )

    await c.health()
    assert captured_headers.get("authorization") == "Bearer sk-test-123"
    await c.close()
