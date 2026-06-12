# Copyright 2026 SignalPilot. All rights reserved.
"""Gateway-backed storage for agent chat traces."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import httpx

from signalpilot._server.auth.session_token import load_session_jwt

if TYPE_CHECKING:
    from signalpilot._server.api.deps import AppStateBase

ChatSource = Literal["user", "notion"]
ThreadStatus = Literal["active", "done", "failed"]


@dataclass(frozen=True)
class ChatThread:
    thread_id: str
    session_id: str
    source: ChatSource
    title: str = ""
    status: ThreadStatus = "active"
    notebook_path: str = ""
    notion_request_page_id: str | None = None
    notion_discussion_id: str | None = None
    metadata: dict[str, Any] | None = None


def local_chat_db_path_for_app(app_state: AppStateBase) -> Path:
    """Return the local chat endpoint DB path.

    Trace persistence does not use this path; traces are persisted through the
    gateway API.
    """
    workspace = app_state.session_manager.workspace
    root = workspace.directory
    if root is None:
        single_file = workspace.single_file()
        if single_file is not None:
            root = str(Path(single_file.path).parent)
    root_path = Path(root) if root is not None else Path.cwd()
    return root_path / "__sp__" / "chat.sqlite"


def _gateway_auth_token() -> str:
    return load_session_jwt() or os.environ.get("SP_API_KEY", "").strip()


def _optional_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _trace_event_body(
    event: dict[str, Any], metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    body = dict(event)
    body["content"] = _optional_str(body.get("content"))
    body["tool_name"] = _optional_str(body.get("tool_name"))
    body["tool_call_id"] = _optional_str(body.get("tool_call_id"))
    body["is_error"] = bool(body.get("is_error"))
    try:
        body["turn"] = int(body.get("turn") or 0)
    except (TypeError, ValueError):
        body["turn"] = 0
    if metadata is not None:
        body["metadata"] = metadata
    return body


class GatewayTraceError(Exception):
    """Gateway trace API failed."""


class GatewayTraceNotFound(GatewayTraceError):
    """Gateway trace API returned 404."""


class GatewayChatTraceClient:
    """Async client for gateway-owned chat trace persistence."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        auth_token: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")
        ).rstrip("/")
        self.auth_token = auth_token if auth_token is not None else _gateway_auth_token()
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> GatewayChatTraceClient:
        token = _gateway_auth_token()
        if not token:
            raise GatewayTraceError(
                "Gateway chat trace persistence requires a notebook session JWT or SP_API_KEY"
            )
        return cls(auth_token=token)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method,
                    url,
                    json=body,
                    params=params,
                    headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise GatewayTraceError(str(exc)) from exc

        if response.status_code == 404:
            raise GatewayTraceNotFound(response.text[:500])
        if response.status_code >= 400:
            raise GatewayTraceError(
                f"Gateway trace API returned {response.status_code}: "
                f"{response.text[:500]}"
            )
        if not response.content:
            return None
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise GatewayTraceError("Gateway trace API returned non-JSON") from exc

    async def upsert_thread(self, thread: ChatThread) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/chat/traces/threads",
            body=asdict(thread),
        )

    async def clear_events(self, thread_id: str) -> None:
        await self._request(
            "DELETE", f"/api/chat/traces/threads/{thread_id}/events"
        )

    async def append_event(
        self,
        thread_id: str,
        event: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        body = _trace_event_body(event, metadata)
        result = await self._request(
            "POST",
            f"/api/chat/traces/threads/{thread_id}/events",
            body=body,
        )
        if not isinstance(result, dict) or "idx" not in result:
            raise GatewayTraceError("Gateway trace append did not return idx")
        return int(result["idx"])

    async def get_events(
        self, thread_id: str, after_index: int = -1
    ) -> list[dict[str, Any]]:
        result = await self._request(
            "GET",
            f"/api/chat/traces/threads/{thread_id}/events",
            params={"after_index": after_index},
        )
        if isinstance(result, dict) and isinstance(result.get("events"), list):
            return result["events"]
        raise GatewayTraceError("Gateway trace event list returned invalid body")

    async def list_threads(self, session_id: str) -> list[dict[str, Any]]:
        result = await self._request(
            "GET",
            "/api/chat/traces/threads",
            params={"session_id": session_id},
        )
        if isinstance(result, dict) and isinstance(result.get("threads"), list):
            return result["threads"]
        raise GatewayTraceError("Gateway trace thread list returned invalid body")

    async def list_threads_by_source(
        self, source: ChatSource, limit: int = 100
    ) -> list[dict[str, Any]]:
        result = await self._request(
            "GET",
            "/api/chat/traces/threads",
            params={"source": source, "limit": limit},
        )
        if isinstance(result, dict) and isinstance(result.get("threads"), list):
            return result["threads"]
        raise GatewayTraceError("Gateway trace thread source list returned invalid body")

    async def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        try:
            result = await self._request(
                "GET", f"/api/chat/traces/threads/{thread_id}"
            )
        except GatewayTraceNotFound:
            return None
        if isinstance(result, dict):
            return result
        raise GatewayTraceError("Gateway trace thread get returned invalid body")


class GatewayChatTraceStore:
    """Gateway-only trace store."""

    def __init__(
        self,
        *,
        gateway_client: GatewayChatTraceClient | None = None,
        use_env_gateway: bool = True,
    ) -> None:
        self.gateway_client = (
            GatewayChatTraceClient.from_env()
            if gateway_client is None and use_env_gateway
            else gateway_client
        )
        if self.gateway_client is None:
            raise GatewayTraceError(
                "Gateway chat trace persistence requires a GatewayChatTraceClient"
            )

    async def upsert_thread(self, thread: ChatThread) -> None:
        await self.gateway_client.upsert_thread(thread)

    async def clear_events(self, thread_id: str) -> None:
        await self.gateway_client.clear_events(thread_id)

    async def append_event(
        self,
        thread_id: str,
        event: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        return await self.gateway_client.append_event(
            thread_id, event, metadata=metadata
        )

    async def get_events(
        self, thread_id: str, after_index: int = -1
    ) -> list[dict[str, Any]]:
        return await self.gateway_client.get_events(thread_id, after_index)

    async def list_threads(self, session_id: str) -> list[dict[str, Any]]:
        return await self.gateway_client.list_threads(session_id)

    async def list_threads_by_source(
        self, source: ChatSource, limit: int = 100
    ) -> list[dict[str, Any]]:
        return await self.gateway_client.list_threads_by_source(source, limit)

    async def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        return await self.gateway_client.get_thread(thread_id)


def get_gateway_chat_trace_store() -> GatewayChatTraceStore:
    return GatewayChatTraceStore()
