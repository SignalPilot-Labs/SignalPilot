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


def test_trace_messages_render_final_statement_as_user_friendly_bullets(
    monkeypatch,
) -> None:
    chat_endpoint = _load_chat_endpoint(monkeypatch)
    trace_event_messages = chat_endpoint["_trace_event_messages"]

    messages = trace_event_messages(
        [
            {"idx": 0, "type": "user", "role": "user", "content": "Analyze revenue"},
            {
                "idx": 1,
                "type": "text",
                "content": (
                    'FINAL_STATEMENT: {"statement":"Revenue increased. Costs stayed flat.",'
                    '"confidenceScore":0.8,"caveats":["Excludes refunds"],'
                    '"handoffNotes":["Used notebook SDK cells."]}'
                ),
                "created_at": 1_800_000_000,
            },
        ]
    )

    payload = json.loads(messages[-1]["content"])
    content = payload["content"]

    assert "FINAL_STATEMENT" not in content
    assert '{"statement"' not in content
    assert "Analysis complete." in content
    assert "Findings:" in content
    assert "- Revenue increased." in content
    assert "- Costs stayed flat." in content
    assert "Confidence: 0.8" in content
    assert "Gotchas / caveats:" in content
    assert "- Excludes refunds" in content
    assert "Method:" in content
    assert "- Used notebook SDK cells." in content


def test_trace_messages_render_plan_and_progress_markers_readably(
    monkeypatch,
) -> None:
    chat_endpoint = _load_chat_endpoint(monkeypatch)
    trace_event_messages = chat_endpoint["_trace_event_messages"]

    messages = trace_event_messages(
        [
            {
                "idx": 1,
                "type": "text",
                "content": (
                    "I have enough context to plan the run.\n\n"
                    'PLAN: {"steps":["Inspect schema","Run revenue query"]}\n\n'
                    'PROGRESS: {"currentStep":"Inspect schema","completedSteps":[],'
                    '"status":"Checking tables"}'
                ),
                "created_at": 1_800_000_000,
            },
        ]
    )

    payload = json.loads(messages[-1]["content"])
    content = payload["content"]

    assert "PLAN:" not in content
    assert "PROGRESS:" not in content
    assert "Plan:" in content
    assert "- Inspect schema" in content
    assert "- Run revenue query" in content
    assert "Progress:" in content
    assert "- Current: Inspect schema" in content
    assert "- Status: Checking tables" in content
