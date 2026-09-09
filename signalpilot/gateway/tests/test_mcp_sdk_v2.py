"""Wire-level compatibility for modern discovery, legacy fallback and HTTP errors."""

import asyncio
import json

import httpx2
import pytest
from mcp import types

from gateway.mcp_connectors.tools import tool_info_from_upstream
from gateway.mcp_connectors.upstream import UpstreamError, UpstreamSession, UpstreamSpec


def rpc_server(*, modern=True, fail_status=None):
    calls = []

    def handle(request):
        if request.method != "POST":
            return httpx2.Response(405)
        body = json.loads(request.content)
        method = body["method"]
        calls.append(method)
        if fail_status:
            return httpx2.Response(
                fail_status, headers={"www-authenticate": 'Bearer resource_metadata="https://vendor.example/meta"'}
            )
        if "id" not in body:
            return httpx2.Response(202)
        if method == "server/discover":
            if not modern:
                return httpx2.Response(404)
            result = {"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}}
        elif method == "initialize":
            assert not modern, "Modern connections must not initialize"
            result = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "vendor", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [{"name": "search", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}]
            }
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": "found"}], "isError": False}
        else:
            raise AssertionError(method)
        if modern:
            result["resultType"] = "complete"
            if method in {"server/discover", "tools/list"}:
                result.update(ttlMs=0, cacheScope="private")
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    return calls, lambda headers: httpx2.AsyncClient(transport=httpx2.MockTransport(handle), headers=headers)


@pytest.mark.parametrize("modern", [True, False])
async def test_upstream_negotiates_both_protocol_eras(modern):
    calls, factory = rpc_server(modern=modern)
    upstream = UpstreamSession(UpstreamSpec("https://vendor.example/mcp", "http"), client_factory=factory)
    await upstream.open()
    try:
        assert upstream.protocol_version == ("2026-07-28" if modern else "2025-11-25")
        tools = await upstream.list_tools()
        assert tool_info_from_upstream(tools[0])["enabled"] is True
        result = await upstream.call_tool("search", {})
        assert result.content[0].text == "found"
        assert not result.is_error
        assert ("initialize" in calls) is not modern
    finally:
        await upstream.close()
    assert not upstream.alive


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 429, 503])
async def test_upstream_preserves_http_failure_and_auth_challenge(status):
    _, factory = rpc_server(fail_status=status)
    upstream = UpstreamSession(UpstreamSpec("https://vendor.example/mcp", "http"), client_factory=factory)
    with pytest.raises(UpstreamError) as caught:
        await upstream.open()
    assert caught.value.status == status
    assert "resource_metadata" in caught.value.www_authenticate
    assert not upstream.alive


def test_sdk_annotations_keep_wire_aliases():
    tool = types.Tool(
        name="search", input_schema={"type": "object"}, annotations=types.ToolAnnotations(read_only_hint=True)
    )
    inventory = tool_info_from_upstream(tool)
    assert inventory["annotations"] == {"read_only_hint": True}
    assert inventory["enabled"]


@pytest.mark.parametrize("modern", [True, False])
async def test_probe_uses_sdk_negotiation(monkeypatch, modern):
    from gateway.mcp_connectors import probe

    async def valid(url):
        return url

    monkeypatch.setattr(probe, "validate_remote_url", valid)
    calls, factory = rpc_server(modern=modern)
    result = await probe.probe_url("https://vendor.example/mcp", client_factory=factory)
    assert result.error is None
    assert result.transport == "http"
    assert result.auth == "none"
    assert result.tools[0]["name"] == "search"
    assert calls.count("server/discover") == 1


async def test_probe_falls_back_to_verified_sse(monkeypatch):
    from unittest.mock import AsyncMock

    from gateway.mcp_connectors import probe

    monkeypatch.setattr(probe, "validate_remote_url", AsyncMock(side_effect=lambda url: url))
    list_tools = AsyncMock(side_effect=[UpstreamError("method not found", status=405), ([], "2025-11-25", "legacy")])
    monkeypatch.setattr(probe, "list_tools_via_sdk", list_tools)

    def factory(headers):
        return httpx2.AsyncClient(
            transport=httpx2.MockTransport(
                lambda request: httpx2.Response(
                    200, headers={"content-type": "text/event-stream"}, text="event: endpoint\ndata: /messages\n\n"
                )
            )
        )

    result = await probe.probe_url("https://vendor.example/sse", client_factory=factory)
    assert result.error is None
    assert result.transport == "sse"
    assert list_tools.call_args.args[0].transport == "sse"


async def test_auth_context_is_clean_and_restored_after_failure(monkeypatch):
    from gateway.auth.mcp_api_key import MCPAuthMiddleware
    from gateway.mcp.context import mcp_eval_connection_var, mcp_org_id_var

    middleware = MCPAuthMiddleware(None)

    async def authenticate(scope, receive, send):
        assert mcp_eval_connection_var.get() is None
        assert mcp_org_id_var.get() is None
        mcp_org_id_var.set("request-org")
        raise asyncio.CancelledError

    monkeypatch.setattr(middleware, "_authenticate", authenticate)
    org_token = mcp_org_id_var.set("caller-org")
    eval_token = mcp_eval_connection_var.set("caller-eval")
    try:
        with pytest.raises(asyncio.CancelledError):
            await middleware({"type": "http"}, None, None)
        assert mcp_org_id_var.get() == "caller-org"
        assert mcp_eval_connection_var.get() == "caller-eval"
    finally:
        mcp_org_id_var.reset(org_token)
        mcp_eval_connection_var.reset(eval_token)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_gateway_agent_schema_and_injected_context_when_disabled(monkeypatch, mode):
    from unittest.mock import AsyncMock

    from mcp.client import Client

    from gateway.mcp import mcp
    from gateway.mcp.context import mcp_org_id_var, mcp_scopes_var, mcp_user_id_var

    monkeypatch.setenv("SP_FEATURE_MCP_AGENT", "false")
    monkeypatch.setattr("gateway.agent_execution.service.get_session_factory", lambda: object())
    monkeypatch.setattr("gateway.mcp.audit._audit_tool_call", AsyncMock())
    tokens = [
        (variable, variable.set(value))
        for variable, value in (
            (mcp_org_id_var, "example-org"),
            (mcp_user_id_var, "example-user"),
            (mcp_scopes_var, ["agent:run"]),
        )
    ]
    try:
        async with Client(mcp, mode=mode) as client:
            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            assert {
                "run_signalpilot_agent",
                "continue_signalpilot_agent",
                "get_signalpilot_agent",
                "cancel_signalpilot_agent",
            } <= tools.keys()
            assert "ctx" not in tools["run_signalpilot_agent"].input_schema["properties"]
            result = await client.call_tool(
                "run_signalpilot_agent",
                {
                    "task": "Inspect my_orders",
                    "project_id": "example-project",
                    "revision": 1,
                    "connection_name": "example-db",
                },
            )
            assert result.is_error
            assert "delegation is disabled" in result.content[0].text
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_nested_agent_catalog_matches_execution_policy_without_mutating_outer(mode):
    from mcp.client import Client

    from gateway.mcp import mcp
    from gateway.mcp.audit import STANDALONE_CHAT_TOOL_ALLOWLIST
    from gateway.mcp.context import mcp_execution_identity_var

    async def catalog(identity):
        token = mcp_execution_identity_var.set(identity)
        try:
            async with Client(mcp, mode=mode, cache=None) as client:
                return {tool.name for tool in (await client.list_tools()).tools}
        finally:
            mcp_execution_identity_var.reset(token)

    outer = await catalog(None)
    assert "run_signalpilot_agent" in outer
    chat = await catalog("chat:example-run")
    assert chat == outer & STANDALONE_CHAT_TOOL_ALLOWLIST
    assert (
        not {"run_signalpilot_agent", "continue_signalpilot_agent", "get_signalpilot_agent", "cancel_signalpilot_agent"}
        & chat
    )
    assert "query_database" in chat
    assert await catalog(None) == outer


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_chat_cannot_call_agent_controls_even_with_agent_scope(monkeypatch, mode):
    from unittest.mock import AsyncMock, Mock

    from mcp.client import Client

    from gateway.mcp import mcp
    from gateway.mcp.context import mcp_execution_identity_var, mcp_org_id_var, mcp_scopes_var, mcp_user_id_var

    service = Mock(side_effect=AssertionError("Chat must not instantiate AgentService"))
    monkeypatch.setattr("gateway.mcp.tools.agent.AgentService", service)
    monkeypatch.setattr("gateway.mcp.audit._audit_tool_call", AsyncMock())
    tokens = [
        (var, var.set(value))
        for var, value in (
            (mcp_execution_identity_var, "chat:example-run"),
            (mcp_org_id_var, "example-org"),
            (mcp_user_id_var, "example-user"),
            (mcp_scopes_var, ["agent:run", "read", "query", "write", "execute", "admin"]),
        )
    ]
    try:
        async with Client(mcp, mode=mode) as client:
            for name, arguments in {
                "run_signalpilot_agent": {
                    "task": "Inspect my_orders",
                    "project_id": "project",
                    "revision": 1,
                    "connection_name": "warehouse",
                },
                "continue_signalpilot_agent": {"thread_id": "thread", "task": "Continue"},
                "get_signalpilot_agent": {"thread_id": "thread"},
                "cancel_signalpilot_agent": {"thread_id": "thread"},
                "wait_signalpilot_agent": {"thread_id": "thread", "wait_seconds": 0},
            }.items():
                result = await client.call_tool(name, arguments)
                assert "unavailable in standalone data chat" in result.content[0].text
        service.assert_not_called()
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)
