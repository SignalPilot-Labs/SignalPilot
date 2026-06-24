from __future__ import annotations

import asyncio
import json
import runpy
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def _load_chat_endpoint(monkeypatch: pytest.MonkeyPatch) -> dict:
    deps_stub = types.ModuleType("signalpilot._server.api.deps")
    deps_stub.AppState = object
    monkeypatch.setitem(sys.modules, "signalpilot._server.api.deps", deps_stub)
    chat_path = (
        Path(__file__).parents[3]
        / "signalpilot"
        / "_server"
        / "api"
        / "endpoints"
        / "chat.py"
    )
    return runpy.run_path(str(chat_path))


def test_list_conversations_supports_slack_trace_source(monkeypatch) -> None:
    chat_endpoint = _load_chat_endpoint(monkeypatch)
    calls: list[str] = []

    class FakeTraceStore:
        async def list_threads_by_source(self, source: str) -> list[dict]:
            calls.append(source)
            return [
                {
                    "thread_id": "session-slack-eb0e7e662d365b53",
                    "session_id": "session-slack-eb0e7e662d365b53",
                    "source": "slack",
                    "title": "Say hi",
                    "status": "done",
                    "notebook_path": "notebooks/slack/say-hi-365b53.py",
                    "created_at": 1_800_000_000,
                    "updated_at": 1_800_000_001,
                }
            ]

    list_conversations = chat_endpoint["list_conversations"]
    list_conversations.__globals__["_trace_store"] = lambda _request: FakeTraceStore()

    response = asyncio.run(
        list_conversations(SimpleNamespace(query_params={"source": "slack"}))
    )
    body = json.loads(response.body)

    assert calls == ["slack"]
    assert body == {
        "conversations": [
            {
                "id": "session-slack-eb0e7e662d365b53",
                "title": "Say hi",
                "source": "slack",
                "status": "done",
                "notebook_path": "notebooks/slack/say-hi-365b53.py",
                "created_at": 1_800_000_000,
                "updated_at": 1_800_000_001,
            }
        ]
    }


def test_slack_trace_source_gets_source_specific_default_title(
    monkeypatch,
) -> None:
    chat_endpoint = _load_chat_endpoint(monkeypatch)

    class FakeTraceStore:
        async def list_threads_by_source(self, source: str) -> list[dict]:
            return [
                {
                    "thread_id": "session-slack-empty-title",
                    "session_id": "session-slack-empty-title",
                    "source": source,
                    "title": "",
                    "created_at": 1_800_000_000,
                    "updated_at": 1_800_000_001,
                }
            ]

    list_conversations = chat_endpoint["list_conversations"]
    list_conversations.__globals__["_trace_store"] = lambda _request: FakeTraceStore()

    response = asyncio.run(
        list_conversations(SimpleNamespace(query_params={"source": "slack"}))
    )
    body = json.loads(response.body)

    assert body["conversations"][0]["title"] == "Slack analysis"
