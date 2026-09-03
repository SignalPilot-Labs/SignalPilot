"""Upstream MCP client sessions (official ``mcp`` SDK) and a small per-credential pool.

Each pooled entry keeps one initialized ``ClientSession`` alive in a background
task so the sandbox's stateless requests (initialize, tools/list, tools/call)
do not re-handshake upstream every time. Entries are keyed by connector + user
and fingerprinted by the credential headers; a changed credential replaces the
entry. Any failure evicts the entry.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from gateway.mcp_connectors.ssrf import safe_async_client

logger = logging.getLogger(__name__)

CLIENT_INFO = types.Implementation(name="signalpilot-gateway", version="1.0")
OPEN_TIMEOUT_SECONDS = 30.0
CALL_TIMEOUT_SECONDS = 120.0
IDLE_SECONDS = 300.0

ClientFactory = Callable[[dict[str, str]], httpx.AsyncClient]


class UpstreamError(RuntimeError):
    """Upstream connection failed. ``status`` carries the HTTP status when known."""

    def __init__(self, message: str, *, status: int | None = None, www_authenticate: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.www_authenticate = www_authenticate


@dataclass(frozen=True)
class UpstreamSpec:
    url: str
    transport: str  # "http" | "sse"
    headers: dict[str, str] = field(default_factory=dict)

    def fingerprint(self) -> str:
        payload = json.dumps([self.url, self.transport, sorted(self.headers.items())], sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()


def unwrap_http_error(exc: BaseException) -> httpx.HTTPStatusError | None:
    """Find an HTTPStatusError inside (nested) ExceptionGroups raised by the SDK."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            found = unwrap_http_error(inner)
            if found is not None:
                return found
    cause = exc.__cause__ or exc.__context__
    if cause is not None and cause is not exc:
        return unwrap_http_error(cause)
    return None


def _first_leaf(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _default_client_factory(headers: dict[str, str]) -> httpx.AsyncClient:
    return safe_async_client(headers=headers, timeout=httpx.Timeout(OPEN_TIMEOUT_SECONDS, read=CALL_TIMEOUT_SECONDS))


class UpstreamSession:
    """One initialized upstream session living in a background task."""

    def __init__(self, spec: UpstreamSpec, *, client_factory: ClientFactory | None = None) -> None:
        self.spec = spec
        self._client_factory = client_factory or _default_client_factory
        self.session: ClientSession | None = None
        self.protocol_version: str | None = None
        self.server_name: str | None = None
        self.last_used = time.monotonic()
        self.failure: BaseException | None = None
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._client: httpx.AsyncClient | None = None

    def _transport(self) -> AbstractAsyncContextManager[Any]:
        self._client = self._client_factory(dict(self.spec.headers))
        if self.spec.transport == "sse":
            return sse_client(
                self.spec.url,
                headers=dict(self.spec.headers),
                httpx_client_factory=lambda headers=None, timeout=None, auth=None: self._client,
            )
        return streamable_http_client(self.spec.url, http_client=self._client)

    async def _run(self, ready: asyncio.Future[None]) -> None:
        try:
            async with self._transport() as streams:
                read_stream, write_stream = streams[0], streams[1]
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=CALL_TIMEOUT_SECONDS),
                    client_info=CLIENT_INFO,
                ) as session:
                    init = await session.initialize()
                    self.session = session
                    self.protocol_version = str(init.protocolVersion)
                    self.server_name = init.serverInfo.name if init.serverInfo else None
                    if not ready.done():
                        ready.set_result(None)
                    await self._stop.wait()
        except BaseException as exc:
            self.failure = exc
            if not ready.done():
                ready.set_exception(self._as_upstream_error(exc))
        finally:
            self.session = None
            if self._client is not None:
                try:
                    await self._client.aclose()
                except Exception:
                    pass

    @staticmethod
    def _as_upstream_error(exc: BaseException) -> UpstreamError:
        http_error = unwrap_http_error(exc)
        if http_error is not None:
            response = http_error.response
            return UpstreamError(
                f"The server answered {response.status_code}",
                status=response.status_code,
                www_authenticate=response.headers.get("www-authenticate"),
            )
        leaf = _first_leaf(exc)
        if isinstance(leaf, asyncio.CancelledError):
            return UpstreamError("Connection cancelled")
        return UpstreamError(f"We couldn't reach this address ({type(leaf).__name__}: {leaf})"[:300])

    async def open(self) -> None:
        loop = asyncio.get_running_loop()
        ready: asyncio.Future[None] = loop.create_future()
        self._task = loop.create_task(self._run(ready), name=f"mcp-upstream:{self.spec.url}")
        try:
            await asyncio.wait_for(ready, timeout=OPEN_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            await self.close()
            raise UpstreamError("The server did not finish the handshake in time") from exc
        except UpstreamError:
            await self.close()
            raise

    @property
    def alive(self) -> bool:
        return self.session is not None and self.failure is None and self._task is not None and not self._task.done()

    async def close(self) -> None:
        self._stop.set()
        task = self._task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()
            except BaseException:
                pass

    def _require(self) -> ClientSession:
        if not self.alive or self.session is None:
            raise UpstreamError("Upstream session is closed")
        self.last_used = time.monotonic()
        return self.session

    async def list_tools(self) -> list[types.Tool]:
        session = self._require()
        tools: list[types.Tool] = []
        cursor: str | None = None
        for _ in range(50):
            result = await session.list_tools(cursor=cursor)
            tools.extend(result.tools)
            cursor = result.nextCursor
            if not cursor:
                break
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
        session = self._require()
        return await session.call_tool(name, arguments or {})

    def describe_failure(self) -> UpstreamError | None:
        return self._as_upstream_error(self.failure) if self.failure is not None else None


class UpstreamPool:
    """Per-(connector, user) pool of live upstream sessions."""

    def __init__(self, *, client_factory: ClientFactory | None = None, idle_seconds: float = IDLE_SECONDS) -> None:
        self._entries: dict[str, UpstreamSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._client_factory = client_factory
        self._idle_seconds = idle_seconds

    def _lock(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock

    async def acquire(self, key: str, spec: UpstreamSpec) -> UpstreamSession:
        async with self._lock(key):
            current = self._entries.get(key)
            if current is not None and current.alive and current.spec.fingerprint() == spec.fingerprint():
                current.last_used = time.monotonic()
                return current
            if current is not None:
                await current.close()
                self._entries.pop(key, None)
            session = UpstreamSession(spec, client_factory=self._client_factory)
            await session.open()
            self._entries[key] = session
            return session

    async def evict(self, key: str) -> None:
        session = self._entries.pop(key, None)
        if session is not None:
            await session.close()

    async def evict_prefix(self, prefix: str) -> int:
        keys = [key for key in self._entries if key.startswith(prefix)]
        for key in keys:
            await self.evict(key)
        return len(keys)

    async def reap_idle(self) -> int:
        now = time.monotonic()
        stale = [key for key, entry in self._entries.items() if now - entry.last_used > self._idle_seconds or not entry.alive]
        for key in stale:
            await self.evict(key)
        return len(stale)

    async def close_all(self) -> None:
        for key in list(self._entries):
            await self.evict(key)

    def __len__(self) -> int:
        return len(self._entries)


pool = UpstreamPool()


async def open_once(spec: UpstreamSpec, *, client_factory: ClientFactory | None = None) -> UpstreamSession:
    """Open a throwaway session (probe / refresh-tools). Caller closes it."""
    session = UpstreamSession(spec, client_factory=client_factory)
    await session.open()
    return session
