"""Delegated credentials only reach the REST adapters used by MCP tools."""

import time

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.agent_execution import auth
from gateway.api.deps import get_store
from gateway.db.models import MCPAgentThread
from gateway.http.middleware.auth import APIKeyAuthMiddleware, _agent_rest_path_allowed
from gateway.security.scope_guard import RequireScope, require_scopes


@pytest_asyncio.fixture
async def agent_client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(MCPAgentThread.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(auth, "get_session_factory", lambda: factory)
    monkeypatch.setattr(auth, "load_session_jwt_secret", lambda: "agent-rest-test-signing-secret-32bytes")
    row = MCPAgentThread(
        id="thread",
        org_id="org",
        user_id="owner",
        run_id="run",
        status="running",
        expires_at=time.time() + 600,
        lease_expires_at=time.time() + 120,
        updated_at=time.time(),
        attempt=1,
        retained_until=time.time() + 3600,
        request={"project_id": "project", "branch": "main", "connection_name": "warehouse"},
        history=[],
        result={},
        snapshot_key="snapshot",
    )
    async with factory() as db:
        db.add(row)
        await db.commit()
    app = FastAPI()
    app.add_middleware(APIKeyAuthMiddleware)

    @app.post("/api/query", dependencies=[RequireScope("query")])
    @app.post("/api/query/explain", dependencies=[RequireScope("query")])
    async def query(request: Request):
        identity = request.state.auth
        async with factory() as db:
            store = await get_store(request, identity["org_id"], identity["user_id"], db)
            return {
                "body": await request.json(),
                "connection": store.allowed_connection_name,
                "org": store.org_id,
                "identity": store.execution_identity,
            }

    @app.get("/api/connections/{name}/schema/overview", dependencies=[RequireScope("read")])
    async def schema(name: str):
        return {"connection": name}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="https://gateway.example",
        headers={"Authorization": "Bearer " + auth.mint(row, 600)},
    ) as client:
        yield client, factory
    await engine.dispose()


async def test_query_adapter_keeps_identity_and_connection_pin(agent_client):
    client, _ = agent_client
    for endpoint in ("/api/query", "/api/query/explain"):
        body = {"connection_name": "warehouse", "sql": "select 1"}
        response = await client.post(endpoint, json=body)
        assert response.status_code == 200, response.text
        assert response.json() == {"body": body, "connection": "warehouse", "org": "org", "identity": "agent:run"}
        assert (await client.post(endpoint, json={**body, "connection_name": "other"})).status_code == 403
        assert (await client.post(endpoint, json={"sql": "select 1"})).status_code == 403


async def test_schema_pin_and_unrelated_routes_are_denied(agent_client):
    client, _ = agent_client
    assert (await client.get("/api/connections/warehouse/schema/overview")).status_code == 200
    assert (await client.get("/api/connections/other/schema/overview")).status_code == 403
    for path in (
        "/api/org-secrets",
        "/api/chat",
        "/api/mcp/proxy/other/mcp",
        "/notebook/session",
        "/api/workspace-projects",
        "/api/connections/warehouse/xata/dbt-profile",
        "/api/connections/health",
    ):
        assert (await client.get(path)).status_code == 403, path


async def test_cancelled_run_cannot_call_rest_adapter(agent_client):
    client, factory = agent_client
    async with factory() as db:
        row = await db.get(MCPAgentThread, "thread")
        row.status = "cancelled"
        await db.commit()
    response = await client.post("/api/query", json={"connection_name": "warehouse", "sql": "select 1"})
    assert response.status_code == 401


async def test_expired_worker_lease_cannot_call_rest_adapter(agent_client):
    client, factory = agent_client
    async with factory() as db:
        row = await db.get(MCPAgentThread, "thread")
        row.lease_expires_at = time.time() - 1
        await db.commit()
    response = await client.post("/api/query", json={"connection_name": "warehouse", "sql": "select 1"})
    assert response.status_code == 401


@pytest.mark.parametrize("scope", ["admin", "write", "execute", "agent:run"])
def test_agent_scope_cannot_expand_even_with_claim(scope):
    from fastapi import HTTPException

    request = Request({"type": "http", "state": {"auth": {"auth_method": "mcp_agent", "scopes": [scope]}}})
    with pytest.raises(HTTPException) as error:
        require_scopes(request, scope)
    assert error.value.status_code == 403


def test_agent_rest_allowlist_does_not_match_connection_prefixes():
    assert not _agent_rest_path_allowed("GET", "/api/connections/warehouse-copy/schema", "warehouse")
    assert not _agent_rest_path_allowed("GET", "/api/connections/warehouse/schema/diff/other", "warehouse")
    assert not _agent_rest_path_allowed("POST", "/api/connections/warehouse/clone", "warehouse")


async def test_connection_health_omitted_name_respects_agent_pin(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from gateway.mcp.context import mcp_allowed_connection_var, mcp_execution_identity_var, mcp_scopes_var
    from gateway.mcp.tools.connections import connection_health

    monkeypatch.setattr("gateway.mcp.audit._audit_tool_call", AsyncMock())
    monkeypatch.setattr(
        "gateway.connectors.health_monitor.health_monitor.all_stats",
        lambda: [SimpleNamespace(connection_name="warehouse"), SimpleNamespace(connection_name="other-warehouse")],
    )
    monkeypatch.setattr("gateway.mcp.tools.connections._format_health_stats", lambda value: value.connection_name)
    variables = [
        (mcp_allowed_connection_var, "warehouse"),
        (mcp_execution_identity_var, "agent:run"),
        (mcp_scopes_var, ["query"]),
    ]
    tokens = [(var, var.set(value)) for var, value in variables]
    try:
        result = await connection_health()
        assert "warehouse" in result
        assert "other-warehouse" not in result
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)
