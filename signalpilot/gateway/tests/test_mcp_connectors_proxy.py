"""Injection (§4) and the proxy enforcement point (R1/R5/R7)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import Depends, Request
from fastapi.testclient import TestClient
from mcp import types
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.auth.notebook_jwt import mint_session_jwt
from gateway.db.models import GatewayBase, GatewayMcpToolCall, GatewayWorkspaceProject
from gateway.mcp_connectors import policy as policy_mod
from gateway.mcp_connectors.proxy_server import ConnectorProxy, ProxyCaller
from gateway.mcp_connectors.upstream import UpstreamError
from gateway.standalone_chat import execution as chat_execution
from gateway.store import standalone_chat as chat_store
from gateway.store.mcp import ConnectorDraft
from gateway.store.mcp import connectors as connector_store
from gateway.store.mcp import members as member_store
from gateway.store.mcp import policy as policy_store

from .mcp_connectors_support import isolated_app

_TEST_SECRET = "test-secret-for-connector-proxy"


def _tools(*names: str, enabled: bool = True) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "title": None,
            "description": f"{name} desc",
            "annotations": {"read_only_hint": True},
            "input_schema": {"type": "object", "properties": {}},
            "enabled": enabled,
            "policy": "auto" if enabled else "off",
            "discovered_at": "2026-09-01T00:00:00+00:00",
            "is_new": False,
        }
        for name in names
    ]


def _patch_crypto(monkeypatch, tmp_path) -> None:
    import gateway.store.crypto as crypto

    monkeypatch.setenv("SP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("SP_ENCRYPTION_KEY_OLD", raising=False)
    monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
    monkeypatch.delenv("SP_FEATURE_CHAT_MCP_CONNECTORS", raising=False)
    monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    _patch_crypto(monkeypatch, tmp_path)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _connector(db: AsyncSession, *, scope: str = "personal", owner: str | None = "user-a", **overrides):
    draft = ConnectorDraft(
        scope=scope,
        name=overrides.pop("name", "Vendor"),
        transport=overrides.pop("transport", "http"),
        created_by=owner or "admin-a",
        owner_user_id=owner if scope == "personal" else None,
        url=overrides.pop("url", "https://mcp.vendor.example/mcp"),
        command=overrides.pop("command", None),
        args=overrides.pop("args", []),
        env=overrides.pop("env", []),
        auth=overrides.pop("auth", "none"),
        headers=overrides.pop("headers", None),
    )
    connector = await connector_store.create_connector(db, org_id="org-a", draft=draft)
    tools = overrides.pop("tools", _tools("search") + _tools("delete", enabled=False))
    await connector_store.update_connector(db, connector, tools_json=tools, status="connected", **overrides)
    return connector


# ── Injection payload (§4) ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_injection_shapes_remote_and_sandbox_entries(db: AsyncSession) -> None:
    remote = await _connector(db)
    sandbox = await _connector(
        db,
        name="GitHub",
        transport="stdio",
        url=None,
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env=[{"name": "GITHUB_TOKEN", "secret": True, "member_supplied": False}, {"name": "REGION", "value": "us", "secret": False}],
        tools=_tools("create_issue"),
    )
    member = await member_store.ensure_member_state(db, org_id="org-a", connector_id=sandbox.id, user_id="user-a")
    member_store.set_member_secrets(member, env={"GITHUB_TOKEN": "ghp_secret"})
    await db.commit()
    entries = await policy_mod.resolve_injection(
        db, org_id="org-a", user_id="user-a", run_origin="user", proxy_base_url="http://gateway:3300/"
    )
    assert entries == [
        {"slug": "github", "kind": "sandbox", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
         "env": {"REGION": "us", "GITHUB_TOKEN": "ghp_secret"}, "allowed_tools": ["create_issue"]},
        {"slug": "vendor", "kind": "remote", "url": f"http://gateway:3300/api/mcp/proxy/{remote.id}/mcp",
         "allowed_tools": ["search"]},
    ]
    # Another user gets nothing (personal), and a sandbox connector without the member's key is skipped.
    assert await policy_mod.resolve_injection(db, org_id="org-a", user_id="user-b", run_origin="user", proxy_base_url="x") == []


@pytest.mark.asyncio
async def test_injection_honors_org_policy_member_switch_and_run_origin(db: AsyncSession) -> None:
    personal = await _connector(db)
    org = await _connector(db, scope="org", owner=None, name="Jira", url="https://mcp.jira.example/mcp",
                           tools=[*_tools("read_issue"), {**_tools("comment")[0], "policy": "ask"}])

    def slugs(entries):
        return [e["slug"] for e in entries]

    base = {"org_id": "org-a", "user_id": "user-a", "proxy_base_url": "http://gw"}
    assert slugs(await policy_mod.resolve_injection(db, run_origin="user", **base)) == ["jira", "vendor"]
    await policy_store.upsert_policy(db, org_id="org-a", allow_personal=True, allowed_hosts=["*.jira.example"])
    assert slugs(await policy_mod.resolve_injection(db, run_origin="user", **base)) == ["jira"]
    await policy_store.upsert_policy(db, org_id="org-a", allow_personal=False, allowed_hosts=[])
    assert slugs(await policy_mod.resolve_injection(db, run_origin="user", **base)) == ["jira"]
    await policy_store.upsert_policy(db, org_id="org-a", allow_personal=True, allowed_hosts=[])
    await member_store.set_member_switch(db, org_id="org-a", connector_id=org.id, user_id="user-a", enabled=False)
    assert slugs(await policy_mod.resolve_injection(db, run_origin="user", **base)) == ["vendor"]
    await member_store.set_member_switch(db, org_id="org-a", connector_id=org.id, user_id="user-a", enabled=True,
                                         disabled_tools=["read_issue"])
    user_entries = await policy_mod.resolve_injection(db, run_origin="user", **base)
    assert {e["slug"]: e["allowed_tools"] for e in user_entries} == {"jira": ["comment"], "vendor": ["search"]}
    # Unattended runs never receive "ask" tools -> jira has nothing left and is dropped.
    assert slugs(await policy_mod.resolve_injection(db, run_origin="improvement", **base)) == ["vendor"]
    await connector_store.update_connector(db, personal, enabled=False)
    assert slugs(await policy_mod.resolve_injection(db, run_origin="user", **base)) == ["jira"]


@pytest.mark.asyncio
async def test_personal_slug_colliding_with_later_org_slug_is_disambiguated_at_injection(db: AsyncSession) -> None:
    await _connector(db, name="GitHub", url="https://a.example/mcp")
    await _connector(db, scope="org", owner=None, name="GitHub", url="https://b.example/mcp")
    entries = await policy_mod.resolve_injection(db, org_id="org-a", user_id="user-a", run_origin="user", proxy_base_url="x")
    assert [e["slug"] for e in entries] == ["github", "github_mine"]


@pytest.mark.asyncio
async def test_prepare_execution_payload_carries_connectors_capability_and_flag(db: AsyncSession, monkeypatch) -> None:
    db.add(GatewayWorkspaceProject(
        id="project-a", org_id="org-a", name="rev", display_name="Rev", description="", connection_name="production",
        source="managed", status="active", settings={}, file_count=0, total_bytes=0, default_branch="main",
        created_at=1.0, updated_at=1.0,
    ))
    await db.commit()
    project = await db.get(GatewayWorkspaceProject, "project-a")
    _, run = await chat_store.create_conversation_with_run(
        db, org_id="org-a", user_id="user-a", project=project, branch="main", message="hi", commit_sha="a" * 40,
    )
    connector = await _connector(db)
    minted: dict[str, Any] = {}

    def fake_mint(**kwargs):
        minted.update(kwargs)
        return "session-jwt"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server")
    monkeypatch.setenv("SP_PUBLIC_GATEWAY_URL", "https://gw.example.com")
    monkeypatch.setattr(chat_execution, "ensure_execution_runtime", AsyncMock(return_value=SimpleNamespace(
        session_id="session-a", internal_base_url="http://notebook.internal", access_token=None)))
    monkeypatch.setattr(chat_execution, "mint_session_jwt", fake_mint)
    monkeypatch.setattr(chat_execution, "get_gateway_settings", lambda: SimpleNamespace(sp_session_jwt_ttl_seconds=300))
    from gateway.config import gateway as gateway_config

    gateway_config.get_gateway_settings.cache_clear() if hasattr(gateway_config.get_gateway_settings, "cache_clear") else None
    prepared = await chat_execution.prepare_execution(
        db, run=run, worker_id="w", branch="main", connection_name="production", commit_sha="a" * 40,
        prompt="p", messages=[], warm_context={},
    )
    assert "mcp_proxy" in minted["capabilities"]
    assert prepared.payload["features"]["mcp_connectors"] is True
    assert prepared.payload["mcp_connectors"] == [
        {"slug": "vendor", "kind": "remote", "url": f"https://gw.example.com/api/mcp/proxy/{connector.id}/mcp",
         "allowed_tools": ["search"]}
    ]
    monkeypatch.setenv("SP_FEATURE_CHAT_MCP_CONNECTORS", "0")
    prepared_off = await chat_execution.prepare_execution(
        db, run=run, worker_id="w", branch="main", connection_name="production", commit_sha="a" * 40,
        prompt="p", messages=[], warm_context={},
    )
    assert prepared_off.payload["mcp_connectors"] == [] and prepared_off.payload["features"]["mcp_connectors"] is False
    assert "mcp_proxy" not in minted["capabilities"]


# ── Proxy: deny + audit (R5), refresh on 401 (R6) ────────────────────────────


class FakeUpstream:
    def __init__(self, fail: UpstreamError | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail

    async def list_tools(self):
        return [types.Tool(name=n, inputSchema={"type": "object"}) for n in ("search", "delete", "hidden")]

    async def call_tool(self, name, arguments):
        if self.fail is not None:
            raise self.fail
        self.calls.append((name, arguments or {}))
        return types.CallToolResult(content=[types.TextContent(type="text", text=f"{name} ok")])


@pytest.mark.asyncio
async def test_proxy_denies_off_tool_and_writes_denied_audit_row(db: AsyncSession, monkeypatch) -> None:
    connector = await _connector(db)
    upstream = FakeUpstream()
    caller = ProxyCaller(org_id="org-a", user_id="user-a", run_id="run-1", conversation_id="conv-1")
    proxy = ConnectorProxy(db, connector, caller)
    monkeypatch.setattr(proxy, "_upstream", AsyncMock(return_value=upstream))

    listed = await proxy.list_tools()
    assert [t.name for t in listed] == ["search"]

    denied = await proxy.call_tool("delete", {"id": 1})
    assert denied.isError and 'Tool "delete" on connector "Vendor" is turned off' in denied.content[0].text
    ok = await proxy.call_tool("search", {"q": "x"})
    assert not ok.isError and upstream.calls == [("search", {"q": "x"})]

    rows = list((await db.execute(select(GatewayMcpToolCall).order_by(GatewayMcpToolCall.called_at))).scalars())
    assert [(r.tool, r.outcome, r.run_id, r.conversation_id, r.user_id) for r in rows] == [
        ("delete", "denied", "run-1", "conv-1", "user-a"),
        ("search", "ok", "run-1", "conv-1", "user-a"),
    ]
    await db.refresh(connector)
    assert connector.last_used_at is not None

    # Org turn-off is enforced per call, even mid-run.
    await connector_store.update_connector(db, connector, enabled=False)
    off = await proxy.call_tool("search", {})
    assert off.isError and "turned off by your organization" in off.content[0].text
    assert await proxy.list_tools() == []


@pytest.mark.asyncio
async def test_proxy_401_without_refresh_signs_member_out(db: AsyncSession, monkeypatch) -> None:
    connector = await _connector(db, auth="oauth")
    member = await member_store.ensure_member_state(db, org_id="org-a", connector_id=connector.id, user_id="user-a")
    member_store.set_oauth_tokens(member, {"access_token": "at", "refresh_token": None, "expires_at": None})
    await db.commit()
    proxy = ConnectorProxy(db, connector, ProxyCaller(org_id="org-a", user_id="user-a", run_id=None, conversation_id=None))
    monkeypatch.setattr(proxy, "_upstream", AsyncMock(return_value=FakeUpstream(fail=UpstreamError("401", status=401))))
    result = await proxy.call_tool("search", {})
    assert result.isError and result.content[0].text == 'Connector "Vendor" needs you to sign in again from Chat settings'
    await db.refresh(member)
    assert member_store.oauth_tokens(member) is None
    rows = list((await db.execute(select(GatewayMcpToolCall))).scalars())
    assert [(r.tool, r.outcome) for r in rows] == [("search", "error")]


# ── Proxy over HTTP with a run session token ─────────────────────────────────


def _jsonrpc(method: str, params: dict | None = None, id: int = 1) -> dict:
    body = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def test_proxy_http_endpoint_authenticates_run_token_and_enforces_capability(tmp_path, monkeypatch) -> None:
    _patch_crypto(monkeypatch, tmp_path)
    monkeypatch.setattr("gateway.auth.notebook_jwt.load_session_jwt_secret", lambda: _TEST_SECRET)
    monkeypatch.setattr("gateway.auth.jwt_secret._cached_secret", _TEST_SECRET)

    async def _make():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(GatewayBase.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            connector = await _connector(session, owner="local")
            return engine, factory, connector.id

    engine, Session, connector_id = asyncio.run(_make())
    upstream = FakeUpstream()
    monkeypatch.setattr(ConnectorProxy, "_upstream", AsyncMock(return_value=upstream))

    from gateway.api.deps import get_store
    from gateway.db.engine import get_db
    from gateway.store import Store

    async def _db():
        async with Session() as session:
            yield session

    async def _store(request: Request, db: AsyncSession = Depends(get_db)):
        auth = getattr(request.state, "auth", None) or {}
        return Store(db, org_id=auth.get("org_id", "local"), user_id=auth.get("user_id", "local"))

    def token(capabilities: list[str]) -> str:
        return mint_session_jwt(
            user_id="local", org_id="org-a", session_id="sess-1", project_id="project-a", branch="main",
            connection_name="production", commit_sha="a" * 40, capabilities=capabilities,
            execution_identity="chat:run-1", scopes=["read", "query", "execute", "write"], ttl=600,
        )

    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    url = f"/api/mcp/proxy/{connector_id}/mcp"
    with isolated_app(monkeypatch, session_factory=Session) as app:
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_store] = _store
        client = TestClient(app)
        no_cap = client.post(url, json=_jsonrpc("tools/list"), headers={**headers, "Authorization": f"Bearer {token(['query:read'])}"})
        assert no_cap.status_code == 403
        auth = {**headers, "Authorization": f"Bearer {token(['query:read', 'mcp_proxy'])}"}

        init = client.post(url, json=_jsonrpc("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}), headers=auth)
        assert init.status_code == 200, init.text
        assert init.json()["result"]["serverInfo"]["name"] == "vendor"
        assert init.json()["result"]["protocolVersion"] == "2025-06-18"

        listed = client.post(url, json=_jsonrpc("tools/list", id=2), headers=auth)
        assert listed.status_code == 200, listed.text
        assert [t["name"] for t in listed.json()["result"]["tools"]] == ["search"]

        called = client.post(url, json=_jsonrpc("tools/call", {"name": "search", "arguments": {"q": "x"}}, id=3), headers=auth)
        assert called.status_code == 200, called.text
        assert called.json()["result"]["content"][0]["text"] == "search ok" and called.json()["result"]["isError"] is False

        denied = client.post(url, json=_jsonrpc("tools/call", {"name": "delete", "arguments": {}}, id=4), headers=auth)
        assert denied.json()["result"]["isError"] is True and "turned off" in denied.json()["result"]["content"][0]["text"]

        assert client.post(url, json=_jsonrpc("tools/list"), headers=headers).status_code in (401, 403)

    async def _audit():
        async with Session() as session:
            rows = list((await session.execute(select(GatewayMcpToolCall).order_by(GatewayMcpToolCall.called_at))).scalars())
            return [(r.tool, r.outcome, r.run_id) for r in rows]

    assert asyncio.run(_audit()) == [("search", "ok", "run-1"), ("delete", "denied", "run-1")]
    asyncio.run(engine.dispose())
