"""The proxy: one logical MCP server per connector, served over the SDK's Streamable HTTP transport.

The sandbox talks to ``POST /api/mcp/proxy/{connector_id}/mcp``. Each request
is served statelessly across modern and handshake-era clients (the
transport is created per request with no session id). ``tools/list`` and
``tools/call`` delegate to a pooled upstream client session that carries the
caller's credential. Every ``tools/call`` is re-authorized and audited (R5).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from mcp import types
from mcp.server.lowlevel.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from gateway.db.models import GatewayMcpConnector, GatewayMcpMemberState
from gateway.mcp_connectors import oauth as oauth_mod
from gateway.mcp_connectors import policy as policy_mod
from gateway.mcp_connectors.upstream import UpstreamError, UpstreamPool, UpstreamSpec
from gateway.mcp_connectors.upstream import pool as default_pool
from gateway.store.mcp import connectors as connector_store
from gateway.store.mcp import members as member_store
from gateway.store.mcp import tool_calls as audit_store

logger = logging.getLogger(__name__)

REASON_MESSAGES = {
    "disabled": 'Connector "{name}" was turned off by your organization',
    "off_for_me": 'Connector "{name}" is turned off in Chat settings',
    "personal_not_allowed": "Your organization does not allow personal connectors",
    "host_not_allowed": 'Your organization does not allow the host of connector "{name}"',
    "needs_sign_in": 'Connector "{name}" needs you to sign in again from Chat settings',
    "needs_key": 'Connector "{name}" needs a key from Chat settings',
    "no_tools": 'Connector "{name}" has no tools turned on',
    "tool_off": 'Tool "{tool}" on connector "{name}" is turned off in Chat settings',
}


@dataclass(frozen=True)
class ProxyCaller:
    org_id: str
    user_id: str
    run_id: str | None
    conversation_id: str | None
    run_origin: str = "user"


def _message(reason: str, *, name: str, tool: str = "") -> str:
    template = REASON_MESSAGES.get(reason) or 'Connector "{name}" is not available ({reason})'
    return template.format(name=name, tool=tool, reason=reason)


def _error_result(message: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=message)], isError=True)


class ConnectorProxy:
    """Per-request proxy bound to a connector, a caller and a DB session."""

    def __init__(
        self,
        session: AsyncSession,
        connector: GatewayMcpConnector,
        caller: ProxyCaller,
        *,
        pool: UpstreamPool | None = None,
    ) -> None:
        self.session = session
        self.connector = connector
        self.caller = caller
        self.pool = pool or default_pool

    @property
    def pool_key(self) -> str:
        return f"{self.connector.id}:{self.caller.user_id}"

    def build_server(self) -> Server:
        proxy = self

        async def _list_tools(ctx, params) -> types.ListToolsResult:
            return types.ListToolsResult(tools=await proxy.list_tools())

        async def _call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
            return await proxy.call_tool(params.name, params.arguments)

        return Server(name=self.connector.slug, version="1.0", on_list_tools=_list_tools, on_call_tool=_call_tool)

    async def _access(self) -> tuple[policy_mod.Access, GatewayMcpMemberState | None]:
        await self.session.refresh(self.connector)
        access, member, _ = await policy_mod.access_for_call(
            self.session,
            connector=self.connector,
            user_id=self.caller.user_id,
            run_origin=self.caller.run_origin,
        )
        return access, member

    async def _upstream(self, member: GatewayMcpMemberState | None):
        if self.connector.auth == "oauth" and member is not None:
            await self._refresh_if_expiring(member)
        spec = UpstreamSpec(
            url=self.connector.url or "",
            transport="sse" if self.connector.transport == "sse" else "http",
            headers=policy_mod.upstream_headers(self.connector, member),
        )
        return await self.pool.acquire(self.pool_key, spec)

    async def _refresh_if_expiring(self, member: GatewayMcpMemberState) -> bool:
        tokens = member_store.oauth_tokens(member)
        if not tokens or not oauth_mod.token_expiring(tokens):
            return False
        return await self.refresh_tokens(member)

    async def refresh_tokens(self, member: GatewayMcpMemberState) -> bool:
        """Single-flight refresh; on failure the member is signed out (R6)."""
        async with oauth_mod.refresh_locks.for_key(self.pool_key):
            await self.session.refresh(member)
            tokens = member_store.oauth_tokens(member)
            if not tokens:
                return False
            try:
                fresh = await oauth_mod.refresh_tokens(
                    dict(self.connector.oauth_json or {}),
                    connector_store.oauth_client_secret(self.connector),
                    tokens,
                )
            except oauth_mod.OAuthError as exc:
                logger.info("Connector %s refresh failed for %s: %s", self.connector.id, self.caller.user_id, exc)
                member_store.set_oauth_tokens(member, None)
                if self.connector.scope == "personal":
                    self.connector.status = "needs_sign_in"
                    self.connector.status_detail = "Sign in again"
                await self.session.commit()
                await self.pool.evict(self.pool_key)
                return False
            member_store.set_oauth_tokens(member, fresh)
            await self.session.commit()
            return True

    async def list_tools(self) -> list[types.Tool]:
        access, member = await self._access()
        if not access.usable:
            return []
        allowed = set(access.allowed_tools)
        try:
            upstream = await self._upstream(member)
            live = await upstream.list_tools()
        except UpstreamError as exc:
            logger.info("Connector %s tools/list fell back to the stored inventory: %s", self.connector.id, exc)
            live = None
        if live is not None:
            return [tool for tool in live if tool.name in allowed]
        return [
            types.Tool(
                name=tool["name"],
                description=tool.get("description") or None,
                inputSchema=dict(tool.get("input_schema") or {"type": "object"}),
            )
            for tool in (self.connector.tools_json or [])
            if tool["name"] in allowed
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
        started = time.monotonic()
        access, member = await self._access()
        if not access.usable:
            return await self._deny(name, access.reason or "denied", started)
        if name not in access.allowed_tools:
            return await self._deny(name, "tool_off", started)
        try:
            result = await self._call_with_retry(name, arguments, member)
        except UpstreamError as exc:
            message = await self._upstream_failure_message(exc, member)
            await self._audit(name, "error", started, message)
            return _error_result(message)
        except Exception as exc:
            logger.exception("Connector %s tools/call %s failed", self.connector.id, name)
            message = f'Tool "{name}" failed: {type(exc).__name__}'
            await self._audit(name, "error", started, message)
            return _error_result(message)
        await self._audit(name, "error" if result.is_error else "ok", started, None)
        return result

    async def _call_with_retry(
        self, name: str, arguments: dict[str, Any] | None, member: GatewayMcpMemberState | None
    ) -> types.CallToolResult:
        try:
            upstream = await self._upstream(member)
            return await upstream.call_tool(name, arguments)
        except UpstreamError as exc:
            await self.pool.evict(self.pool_key)
            if exc.status == 401 and self.connector.auth == "oauth" and member is not None:
                if not await self.refresh_tokens(member):
                    raise
            upstream = await self._upstream(member)
            return await upstream.call_tool(name, arguments)
        except Exception:
            await self.pool.evict(self.pool_key)
            upstream = await self._upstream(member)
            return await upstream.call_tool(name, arguments)

    async def _upstream_failure_message(self, exc: UpstreamError, member: GatewayMcpMemberState | None) -> str:
        if exc.status == 401:
            if self.connector.auth == "oauth":
                if member is not None and member_store.oauth_tokens(member):
                    member_store.set_oauth_tokens(member, None)
                    await self.session.commit()
                return _message("needs_sign_in", name=self.connector.name)
            return f'Connector "{self.connector.name}": the provider rejected the key'
        if exc.status == 403:
            return f'Connector "{self.connector.name}": the provider refused this call (403)'
        if exc.status == 429:
            return f'Connector "{self.connector.name}": the provider is rate limiting (429). Try again later'
        return f'Connector "{self.connector.name}": {exc}'

    async def _deny(self, name: str, reason: str, started: float) -> types.CallToolResult:
        message = _message(reason, name=self.connector.name, tool=name)
        await self._audit(name, "denied", started, message)
        return _error_result(message)

    async def _audit(self, tool: str, outcome: str, started: float, error: str | None) -> None:
        try:
            await audit_store.record_call(
                self.session,
                org_id=self.caller.org_id,
                connector_id=self.connector.id,
                user_id=self.caller.user_id,
                tool=tool,
                outcome=outcome,
                duration_ms=int((time.monotonic() - started) * 1000),
                run_id=self.caller.run_id,
                conversation_id=self.caller.conversation_id,
                error=error,
            )
            if outcome == "ok":
                await connector_store.touch_last_used(self.session, self.connector)
        except Exception:
            logger.exception("Could not write connector audit row")


async def serve_stateless(server: Server, scope: Scope, receive: Receive, send: Send) -> None:
    """Serve one HTTP request with a fresh stateless Streamable HTTP transport."""
    manager = StreamableHTTPSessionManager(server, stateless=True, json_response=True)
    async with manager.run():
        await manager.handle_request(scope, receive, send)


class McpProxyResponse(Response):
    """Starlette response that hands the raw ASGI request to the MCP transport."""

    def __init__(self, server: Server) -> None:
        super().__init__(content=b"")
        self._server = server

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await serve_stateless(self._server, scope, receive, send)
