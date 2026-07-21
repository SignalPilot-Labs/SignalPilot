from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from gateway.analysis_delivery import intake_actions as intake_actions_module
from gateway.analysis_delivery.intake_actions import (
    IntakeActionValidationError,
    analysis_status_for_source_thread,
    validate_terminal_action,
)
from gateway.analysis_delivery.intake_agent import (
    IntakeAgent,
    IntakeAgentError,
    IntakeSession,
    _intake_system_prompt,
)


class FakeToolRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        args = dict(arguments or {})
        self.calls.append((name, args))
        return json.dumps({"ok": True, "tool": name}, ensure_ascii=True)


def _session(**overrides: Any) -> IntakeSession:
    values: dict[str, Any] = {
        "source": "slack",
        "surface": "slack_mention",
        "org_id": "org-1",
        "user_id": "user-1",
        "prompt": "Which databases are connected?",
        "source_thread_id": "slack:T1:C1:1.0",
        "available_terminal_actions": (
            "respond_to_user",
            "react_or_ignore",
            "start_notebook_analysis",
            "update_notebook_analysis",
        ),
    }
    values.update(overrides)
    return IntakeSession(**values)


def _client_for_responses(responses: list[dict[str, Any]], requests: list[dict[str, Any]] | None = None):
    async def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json=responses.pop(0))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_intake_agent_runs_read_tool_then_single_terminal_action() -> None:
    requests: list[dict[str, Any]] = []
    client = _client_for_responses(
        [
            {
                "content": [
                    {"type": "tool_use", "id": "toolu-1", "name": "get_current_conversation", "input": {}}
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu-2",
                        "name": "respond_to_user",
                        "input": {"text": "Two database connections are configured."},
                    }
                ],
                "stop_reason": "tool_use",
            },
        ],
        requests,
    )
    runner = FakeToolRunner()
    try:
        result = await IntakeAgent(api_key="sk-ant-test", http_client=client).run(_session(), runner)  # type: ignore[arg-type]
    finally:
        await client.aclose()

    assert runner.calls == [("get_current_conversation", {})]
    assert result.action.name == "respond_to_user"
    assert result.action.text == "Two database connections are configured."
    tool_names = {tool["name"] for tool in requests[0]["tools"]}
    assert "get_current_conversation" in tool_names
    assert "query_database" not in tool_names


@pytest.mark.asyncio
async def test_intake_agent_rejects_multiple_terminal_actions() -> None:
    client = _client_for_responses(
        [
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu-1",
                        "name": "respond_to_user",
                        "input": {"text": "ok"},
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu-2",
                        "name": "start_notebook_analysis",
                        "input": {"prompt": "Analyze revenue", "output_mode": "answer"},
                    },
                ],
                "stop_reason": "tool_use",
            }
        ]
    )
    try:
        with pytest.raises(IntakeAgentError, match="more than one terminal"):
            await IntakeAgent(api_key="sk-ant-test", http_client=client).run(_session(), FakeToolRunner())  # type: ignore[arg-type]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_intake_agent_rejects_unavailable_terminal_action() -> None:
    client = _client_for_responses(
        [
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu-1",
                        "name": "respond_to_user",
                        "input": {"text": "ok"},
                    }
                ],
                "stop_reason": "tool_use",
            }
        ]
    )
    try:
        with pytest.raises(IntakeActionValidationError, match="not available"):
            await IntakeAgent(api_key="sk-ant-test", http_client=client).run(  # type: ignore[arg-type]
                _session(available_terminal_actions=("start_notebook_analysis",)),
                FakeToolRunner(),
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_intake_agent_rejects_non_allowlisted_read_tool() -> None:
    client = _client_for_responses(
        [
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu-1",
                        "name": "query_database",
                        "input": {"connection_name": "prod", "sql": "select 1"},
                    }
                ],
                "stop_reason": "tool_use",
            }
        ]
    )
    runner = FakeToolRunner()
    try:
        with pytest.raises(IntakeAgentError, match="did not call a terminal action"):
            await IntakeAgent(api_key="sk-ant-test", http_client=client).run(_session(), runner)  # type: ignore[arg-type]
    finally:
        await client.aclose()

    assert runner.calls == []


def test_terminal_action_validation_rejects_invalid_args() -> None:
    with pytest.raises(IntakeActionValidationError, match="requires data_instruction"):
        validate_terminal_action(
            "update_notion_deliverable",
            {"mode": "refresh_data", "render_instruction": "Refresh the dashboard"},
        )

    with pytest.raises(IntakeActionValidationError, match="requires output_mode"):
        validate_terminal_action("start_notebook_analysis", {"prompt": "Analyze revenue"})

    with pytest.raises(IntakeActionValidationError, match="fresh must be a boolean"):
        validate_terminal_action(
            "start_notebook_analysis",
            {"prompt": "Analyze revenue", "output_mode": "answer", "fresh": "yes"},
        )


def test_start_notebook_action_exposes_explicit_fresh_semantics() -> None:
    action = validate_terminal_action(
        "start_notebook_analysis",
        {"prompt": "Analyze revenue", "output_mode": "answer", "fresh": True},
    )

    assert action.fresh is True


def test_intake_prompt_routes_followups_to_update_unless_fresh_is_explicit() -> None:
    prompt = _intake_system_prompt(_session())

    assert "rerun with latest data" in prompt
    assert "choose update_notebook_analysis when a safe trail exists" in prompt
    assert "start_notebook_analysis with fresh=true" in prompt


@pytest.mark.asyncio
async def test_analysis_status_for_source_thread_reports_not_found_busy_and_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(intake_actions_module.analysis_trails, "latest_trail_for_source_thread_id", lookup)

    missing = await analysis_status_for_source_thread(
        "db",  # type: ignore[arg-type]
        org_id="org-1",
        source="slack",
        source_thread_id="slack:T1:C1:1.0",
        active_stale_seconds=1800,
    )
    assert missing.status == "not_found"

    lookup.return_value = SimpleNamespace(status="active", updated_at=time.time())
    busy = await analysis_status_for_source_thread(
        "db",  # type: ignore[arg-type]
        org_id="org-1",
        source="slack",
        source_thread_id="slack:T1:C1:1.0",
        active_stale_seconds=1800,
    )
    assert busy.status == "busy"

    lookup.return_value = SimpleNamespace(status="done", updated_at=time.time())
    safe = await analysis_status_for_source_thread(
        "db",  # type: ignore[arg-type]
        org_id="org-1",
        source="slack",
        source_thread_id="slack:T1:C1:1.0",
        active_stale_seconds=1800,
    )
    assert safe.status == "safe_to_update"
