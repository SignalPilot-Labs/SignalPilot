from __future__ import annotations

from typing import Any

import httpx
import pytest

from signalpilot._server.ai.chat_store import (
    ChatThread,
    GatewayChatTraceClient,
    GatewayChatTraceStore,
    GatewayTraceError,
)


@pytest.mark.asyncio
async def test_gateway_trace_client_uses_expected_endpoints_and_bearer_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def request(
            self,
            method: str,
            url: str,
            *,
            json: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None,
        ) -> httpx.Response:
            calls.append(
                {
                    "method": method,
                    "url": url,
                    "json": json,
                    "params": params,
                    "headers": headers,
                }
            )
            if url.endswith("/events") and method == "POST":
                return httpx.Response(200, json={"idx": 2})
            if url.endswith("/events") and method == "GET":
                return httpx.Response(200, json={"events": [{"idx": 2, "type": "text"}]})
            if url.endswith("/threads") and method == "GET":
                return httpx.Response(200, json={"threads": []})
            return httpx.Response(200, json={"thread_id": "thread-1"})

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    client = GatewayChatTraceClient(
        base_url="http://gateway:3300", auth_token="session-jwt"
    )

    await client.upsert_thread(
        ChatThread(thread_id="thread-1", session_id="session-1", source="notion")
    )
    idx = await client.append_event(
        "thread-1",
        {
            "type": "text",
            "content": "hello",
            "tool_name": None,
            "tool_call_id": None,
            "is_error": None,
            "turn": None,
        },
    )
    events = await client.get_events("thread-1", after_index=1)
    await client.list_threads_by_source("notion")

    assert idx == 2
    assert events == [{"idx": 2, "type": "text"}]
    assert [call["method"] for call in calls] == ["POST", "POST", "GET", "GET"]
    assert calls[0]["url"] == "http://gateway:3300/api/chat/traces/threads"
    assert calls[1]["url"] == "http://gateway:3300/api/chat/traces/threads/thread-1/events"
    assert calls[1]["json"]["tool_name"] == ""
    assert calls[1]["json"]["tool_call_id"] == ""
    assert calls[1]["json"]["is_error"] is False
    assert calls[1]["json"]["turn"] == 0
    assert calls[2]["params"] == {"after_index": 1}
    assert calls[3]["params"] == {"source": "notion", "limit": 100}
    assert all(
        call["headers"]["Authorization"] == "Bearer session-jwt" for call in calls
    )


class FailingGatewayClient:
    async def upsert_thread(self, _thread: ChatThread) -> dict[str, Any]:
        raise GatewayTraceError("unavailable")

    async def clear_events(self, _thread_id: str) -> None:
        raise GatewayTraceError("unavailable")

    async def append_event(
        self,
        _thread_id: str,
        _event: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        _ = metadata
        raise GatewayTraceError("unavailable")

    async def list_threads(self, _session_id: str) -> list[dict[str, Any]]:
        raise GatewayTraceError("unavailable")

    async def list_threads_by_source(
        self, _source: str, _limit: int = 100
    ) -> list[dict[str, Any]]:
        raise GatewayTraceError("unavailable")

    async def get_thread(self, _thread_id: str) -> dict[str, Any] | None:
        raise GatewayTraceError("unavailable")

    async def get_events(
        self, _thread_id: str, _after_index: int = -1
    ) -> list[dict[str, Any]]:
        raise GatewayTraceError("unavailable")


@pytest.mark.asyncio
async def test_gateway_trace_store_delegates_to_gateway_client() -> None:
    class RecordingGatewayClient:
        def __init__(self) -> None:
            self.thread: ChatThread | None = None
            self.cleared: list[str] = []

        async def upsert_thread(self, thread: ChatThread) -> dict[str, Any]:
            self.thread = thread
            return {"thread_id": thread.thread_id}

        async def clear_events(self, thread_id: str) -> None:
            self.cleared.append(thread_id)

        async def append_event(
            self,
            thread_id: str,
            event: dict[str, Any],
            *,
            metadata: dict[str, Any] | None = None,
        ) -> int:
            assert thread_id == "thread-1"
            assert event["content"] == "Analyze"
            assert metadata is None
            return 3

        async def list_threads(self, session_id: str) -> list[dict[str, Any]]:
            return [{"thread_id": "thread-1", "session_id": session_id}]

        async def list_threads_by_source(
            self, source: str, limit: int = 100
        ) -> list[dict[str, Any]]:
            return [{"thread_id": "thread-1", "source": source, "limit": limit}]

        async def get_thread(self, thread_id: str) -> dict[str, Any] | None:
            return {"thread_id": thread_id}

        async def get_events(
            self, thread_id: str, after_index: int = -1
        ) -> list[dict[str, Any]]:
            return [{"thread_id": thread_id, "after_index": after_index}]

    client = RecordingGatewayClient()
    store = GatewayChatTraceStore(gateway_client=client)  # type: ignore[arg-type]

    await store.upsert_thread(
        ChatThread(
            thread_id="thread-1",
            session_id="session-1",
            source="notion",
            title="Notion analysis",
        )
    )
    idx = await store.append_event(
        "thread-1", {"type": "user", "role": "user", "content": "Analyze"}
    )

    await store.clear_events("thread-1")

    assert idx == 3
    assert client.thread is not None
    assert client.thread.thread_id == "thread-1"
    assert client.cleared == ["thread-1"]
    assert [thread["thread_id"] for thread in await store.list_threads("session-1")] == [
        "thread-1"
    ]
    assert [event["thread_id"] for event in await store.get_events("thread-1")] == [
        "thread-1"
    ]


@pytest.mark.asyncio
async def test_gateway_trace_store_does_not_fallback() -> None:
    store = GatewayChatTraceStore(gateway_client=FailingGatewayClient())  # type: ignore[arg-type]

    with pytest.raises(GatewayTraceError):
        await store.list_threads("session-1")


def test_gateway_trace_store_requires_gateway_client_when_env_disabled() -> None:
    with pytest.raises(GatewayTraceError):
        GatewayChatTraceStore(use_env_gateway=False)
