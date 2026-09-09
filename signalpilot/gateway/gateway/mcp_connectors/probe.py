"""Probe a URL or command: transport, auth mode, server name, tools.

The SDK negotiates modern discovery or the legacy handshake over HTTP.
400/404/405 may fall back to legacy SSE. A 401 runs OAuth discovery;
without OAuth metadata it is a key-protected server.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
from dataclasses import dataclass, field
from typing import Any

import httpx2 as httpx

from gateway.mcp_connectors import oauth as oauth_mod
from gateway.mcp_connectors.ssrf import (
    PROBE_TIMEOUT_SECONDS,
    safe_async_client,
    validate_remote_url,
)
from gateway.mcp_connectors.tools import tool_info_from_upstream
from gateway.mcp_connectors.upstream import ClientFactory, UpstreamError, UpstreamSpec, open_once

logger = logging.getLogger(__name__)

_SSE_FALLBACK_STATUSES = {400, 404, 405}
_BLOCKED_COMMANDS = {"docker", "podman", "sudo", "su"}
_UNREACHABLE = "We couldn't reach this address. Check the URL or ask the provider if it needs a key."


@dataclass
class ProbeResult:
    transport: str  # "http" | "sse" | "stdio"
    auth: str = "unknown"  # "none" | "oauth" | "key" | "unknown"
    server_name: str | None = None
    protocol_version: str | None = None
    tools: list[dict[str, Any]] | None = None
    oauth: dict[str, Any] | None = None
    error: str | None = None
    discovery: oauth_mod.OAuthDiscovery | None = field(default=None, repr=False)
    www_authenticate: str | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        from gateway.mcp_connectors.tools import public_tool_info

        payload: dict[str, Any] = {"transport": self.transport, "auth": self.auth}
        if self.server_name:
            payload["server_name"] = self.server_name
        if self.protocol_version:
            payload["protocol_version"] = self.protocol_version
        if self.tools is not None:
            payload["tools"] = [public_tool_info(tool) for tool in self.tools]
        if self.oauth:
            payload["oauth"] = self.oauth
        if self.error:
            payload["error"] = self.error
        return payload


async def _looks_like_legacy_sse(client: httpx.AsyncClient, url: str) -> bool:
    """GET expecting an SSE stream whose first event is ``endpoint``."""
    try:
        async with client.stream("GET", url, headers={"Accept": "text/event-stream"}) as response:
            if response.status_code != 200:
                return False
            if not response.headers.get("content-type", "").startswith("text/event-stream"):
                return False

            async def _first_event() -> bool:
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        return line.split(":", 1)[1].strip() == "endpoint"
                return False

            return await asyncio.wait_for(_first_event(), timeout=PROBE_TIMEOUT_SECONDS)
    except (httpx.HTTPError, TimeoutError):
        return False


async def list_tools_via_sdk(
    spec: UpstreamSpec, *, client_factory: ClientFactory | None = None
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Initialize + tools/list through the SDK. Returns (tools, protocol_version, server_name)."""
    session = await open_once(spec, client_factory=client_factory)
    try:
        upstream_tools = await session.list_tools()
        return (
            [tool_info_from_upstream(tool) for tool in upstream_tools],
            session.protocol_version,
            session.server_name,
        )
    finally:
        await session.close()


async def probe_url(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    client_factory: ClientFactory | None = None,
    transport_hint: str | None = None,
) -> ProbeResult:
    """Probe a remote server. Never raises for reachability problems; SSRF errors do raise."""
    normalized = await validate_remote_url(url)
    factory = client_factory or (lambda h: safe_async_client(headers=h, timeout=httpx.Timeout(PROBE_TIMEOUT_SECONDS)))
    transport = transport_hint or "http"
    spec = UpstreamSpec(url=normalized, transport=transport, headers=dict(headers or {}))
    try:
        tools, protocol_version, server_name = await list_tools_via_sdk(spec, client_factory=client_factory)
    except UpstreamError as exc:
        if exc.status == 401:
            return await _classify_401(normalized, exc.www_authenticate, None, transport)
        if exc.status == 403:
            return ProbeResult(transport=transport, auth="key")
        if exc.status not in _SSE_FALLBACK_STATUSES or transport_hint is not None:
            return ProbeResult(transport=transport, auth="unknown", error=str(exc) or _UNREACHABLE)
        async with factory(dict(headers or {})) as client:
            legacy_sse = await _looks_like_legacy_sse(client, normalized)
        if not legacy_sse:
            return ProbeResult(
                transport=transport, auth="unknown", error="This address does not answer like an MCP server."
            )
        transport = "sse"
        spec = UpstreamSpec(url=normalized, transport=transport, headers=dict(headers or {}))
        try:
            tools, protocol_version, server_name = await list_tools_via_sdk(spec, client_factory=client_factory)
        except UpstreamError as sse_exc:
            if sse_exc.status == 401:
                return await _classify_401(normalized, sse_exc.www_authenticate, None, transport)
            return ProbeResult(transport=transport, auth="unknown", error=str(sse_exc) or _UNREACHABLE)
    return ProbeResult(
        transport=transport,
        auth="key" if headers else "none",
        server_name=server_name,
        protocol_version=protocol_version,
        tools=tools,
    )


async def _classify_401(
    url: str,
    www_authenticate: str | None,
    client: httpx.AsyncClient | None,
    transport_hint: str | None,
) -> ProbeResult:
    try:
        discovery = await oauth_mod.discover(url, www_authenticate, client=client)
    except oauth_mod.OAuthError as exc:
        return ProbeResult(transport=transport_hint or "http", auth="oauth", error=str(exc))
    if discovery is None:
        return ProbeResult(transport=transport_hint or "http", auth="key", www_authenticate=www_authenticate)
    return ProbeResult(
        transport=transport_hint or "http",
        auth="oauth",
        oauth={"authorization_server": discovery.issuer, "registration": discovery.registration},
        discovery=discovery,
        www_authenticate=www_authenticate,
    )


def parse_command(command: str, args: list[str] | None = None) -> tuple[str, list[str]]:
    """Split a pasted command line into (command, args); explicit args win."""
    text = (command or "").strip()
    if not text:
        raise ValueError("Enter a command")
    if args:
        return text, [str(a) for a in args]
    try:
        parts = shlex.split(text, posix=True)
    except ValueError as exc:
        raise ValueError("The command has unbalanced quotes") from exc
    if not parts:
        raise ValueError("Enter a command")
    return parts[0], parts[1:]


def probe_command(command: str, args: list[str] | None = None) -> ProbeResult:
    """Sandbox connectors start inside the agent sandbox; the gateway only validates the shape."""
    try:
        executable, argv = parse_command(command, args)
    except ValueError as exc:
        return ProbeResult(transport="stdio", auth="none", error=str(exc))
    base = executable.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    if base in _BLOCKED_COMMANDS:
        return ProbeResult(
            transport="stdio",
            auth="none",
            error=f"{base} is not available inside the sandbox. Use npx or uvx to start the server.",
        )
    return ProbeResult(transport="stdio", auth="none", server_name=base, tools=None)


def is_probably_url(value: str) -> bool:
    text = (value or "").strip().lower()
    return text.startswith(("http://", "https://"))


def summarize_probe(result: ProbeResult) -> str:
    return json.dumps(result.to_dict(), sort_keys=True)[:500]
