from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.analysis_delivery import (
    AnalysisPreflightKind,
    DeliveryRenderer,
    classify_analysis_request,
    delivery_api_key_for_user,
    delivery_result_to_status,
    load_delivery_packet,
    load_delivery_packet_from_events,
    render_slack_final_message,
    render_slack_progress_message,
)
from gateway.analysis_delivery import credentials as credentials_module
from gateway.analysis_delivery import trace_loader as trace_loader_module
from gateway.analysis_delivery.renderer import fallback_delivery
from gateway.trace_markers import redact_trace_control_markers


def test_preflight_gates_greetings_and_ambiguous_data_prompts() -> None:
    assert classify_analysis_request("hi").kind == AnalysisPreflightKind.DIRECT
    assert classify_analysis_request("hello").kind == AnalysisPreflightKind.DIRECT
    assert classify_analysis_request("thanks").kind == AnalysisPreflightKind.DIRECT

    ambiguous = classify_analysis_request("revenue")

    assert ambiguous.kind == AnalysisPreflightKind.AMBIGUOUS
    assert "fresh, specific analysis request" in (ambiguous.response or "")
    assert classify_analysis_request("Analyze revenue by product for Q2").kind == AnalysisPreflightKind.ANALYZE


def test_trace_loader_extracts_latest_worker_plan_progress_and_final_statement() -> None:
    packet = load_delivery_packet_from_events(
        [
            {"idx": 0, "type": "user", "content": "Analyze revenue"},
            {"idx": 1, "type": "text", "content": 'PLAN: {"steps":["Inspect schema","Run revenue query"]}'},
            {
                "idx": 2,
                "type": "text",
                "content": 'PROGRESS: {"currentStep":"Inspect schema","completedSteps":[],"status":"checking tables"}',
            },
            {
                "idx": 3,
                "type": "text",
                "content": 'PLAN: {"steps":["Inspect schema","Run revenue query","Validate totals"]}',
            },
            {
                "idx": 4,
                "type": "text",
                "content": (
                    'FINAL_STATEMENT: {"statement":"Revenue increased.","confidenceScore":"high",'
                    '"caveats":["Excludes refunds"],"handoffNotes":["Used notebook SDK."]}'
                ),
            },
            {
                "idx": 5,
                "type": "done",
                "metadata": {
                    "result": {
                        "notion_charts": [
                            {
                                "title": "Revenue trend",
                                "url": "/api/notion-analysis/chart/req/revenue.png",
                            }
                        ]
                    }
                },
            },
        ],
        status_payload={"status": "Done"},
    )

    assert packet.user_request == "Analyze revenue"
    assert packet.plan is not None
    assert packet.plan.steps == ["Inspect schema", "Run revenue query", "Validate totals"]
    assert packet.latest_progress is not None
    assert packet.latest_progress.current_step == "Inspect schema"
    assert packet.final_statement is not None
    assert packet.final_statement.statement == "Revenue increased."
    assert packet.final_statement.confidence_score == "high"
    assert packet.charts[0]["title"] == "Revenue trend"
    assert packet.status == "done"


def test_trace_loader_drops_numeric_confidence_score() -> None:
    packet = load_delivery_packet_from_events(
        [
            {
                "idx": 1,
                "type": "text",
                "content": (
                    'FINAL_STATEMENT: {"statement":"Revenue increased.",'
                    '"confidenceScore":0.8,"caveats":[],"handoffNotes":[]}'
                ),
            }
        ],
        status_payload={"status": "Done"},
    )

    assert packet.final_statement is not None
    assert packet.final_statement.confidence_score is None

    delivery = fallback_delivery(packet)
    status = delivery_result_to_status(delivery, packet)

    assert "confidenceScore" not in status


@pytest.mark.asyncio
async def test_load_delivery_packet_reuses_loaded_trace_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    async def get_thread(*args, **kwargs):
        calls.append(("get_thread", kwargs))
        return SimpleNamespace(status="done")

    async def get_events(*args, **kwargs):
        calls.append(("get_events", kwargs))
        return []

    monkeypatch.setattr(trace_loader_module.chat_traces, "get_thread", get_thread)
    monkeypatch.setattr(trace_loader_module.chat_traces, "get_events", get_events)

    packet = await load_delivery_packet(
        AsyncMock(),
        org_id="org-1",
        user_id="user-1",
        thread_id="thread-1",
    )

    assert packet.status == "done"
    assert calls == [
        (
            "get_thread",
            {"org_id": "org-1", "user_id": "user-1", "thread_id": "thread-1"},
        ),
        (
            "get_events",
            {
                "org_id": "org-1",
                "user_id": "user-1",
                "thread_id": "thread-1",
                "require_thread": False,
            },
        ),
    ]


def test_fallback_delivery_strips_placeholder_chart_labels() -> None:
    packet = load_delivery_packet_from_events(
        [],
        status_payload={
            "status": "Done",
            "notionCharts": [
                {
                    "title": "Chart 1",
                    "caption": "Notebook image 1",
                    "url": "/api/notion-analysis/chart/req/image-1.png",
                }
            ],
        },
    )

    result = fallback_delivery(packet)

    assert result.notion_charts == [
        {
            "title": "",
            "caption": "",
            "url": "/api/notion-analysis/chart/req/image-1.png",
        }
    ]


def test_trace_control_markers_are_redacted_into_metadata_for_delivery() -> None:
    content, metadata = redact_trace_control_markers(
        "- Revenue increased.\n"
        "- Costs stayed flat.\n\n"
        'FINAL_STATEMENT: {"statement":"Revenue increased. Costs stayed flat.",'
        '"confidenceScore":"medium","caveats":["Excludes refunds"],'
        '"handoffNotes":["Used notebook SDK."]}'
    )

    assert "FINAL_STATEMENT" not in content
    assert content == "- Revenue increased.\n- Costs stayed flat."

    packet = load_delivery_packet_from_events(
        [
            {
                "idx": 1,
                "type": "text",
                "content": content,
                "metadata": metadata,
            }
        ],
        status_payload={"status": "Done"},
    )

    assert packet.final_statement is not None
    assert packet.final_statement.statement == "Revenue increased. Costs stayed flat."
    assert packet.final_statement.confidence_score == "medium"
    assert packet.final_statement.caveats == ["Excludes refunds"]
    assert packet.final_statement.handoff_notes == ["Used notebook SDK."]


def test_slack_progress_waits_for_worker_plan_then_uses_exact_steps() -> None:
    no_plan = load_delivery_packet_from_events([], user_request="Analyze revenue")

    assert render_slack_progress_message(no_plan) == "Analyzing your request..."

    packet = load_delivery_packet_from_events(
        [
            {"idx": 1, "type": "text", "content": 'PLAN: {"steps":["Inspect schema","Run revenue query"]}'},
            {
                "idx": 2,
                "type": "text",
                "content": (
                    'PROGRESS: {"currentStep":"Run revenue query",'
                    '"completedSteps":["Inspect schema"],"status":"querying fin-db"}'
                ),
            },
        ],
    )

    rendered = render_slack_progress_message(packet)

    assert "- [x] Inspect schema" in rendered
    assert "- [ ] Run revenue query (current)" in rendered
    assert "querying fin-db" in rendered


@pytest.mark.asyncio
async def test_delivery_api_key_for_user_reads_stored_account_key(monkeypatch: pytest.MonkeyPatch) -> None:
    get_user_anthropic_key = AsyncMock(return_value="sk-ant-user")
    monkeypatch.setattr(credentials_module.user_secrets_store, "get_user_anthropic_key", get_user_anthropic_key)

    api_key = await delivery_api_key_for_user(AsyncMock(), org_id="org-1", user_id="user-1")

    assert api_key == "sk-ant-user"
    get_user_anthropic_key.assert_awaited_once()
    assert get_user_anthropic_key.await_args.args[1:] == ("org-1", "user-1")


@pytest.mark.asyncio
async def test_delivery_api_key_for_user_disables_model_delivery_without_account_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_user_anthropic_key = AsyncMock(return_value=None)
    monkeypatch.setattr(credentials_module.user_secrets_store, "get_user_anthropic_key", get_user_anthropic_key)

    api_key = await delivery_api_key_for_user(AsyncMock(), org_id="org-1", user_id="user-1")

    assert api_key == ""


@pytest.mark.asyncio
async def test_delivery_renderer_falls_back_to_final_statement_without_model() -> None:
    packet = load_delivery_packet_from_events(
        [
            {
                "idx": 1,
                "type": "text",
                "content": (
                    'FINAL_STATEMENT: {"statement":"Revenue increased.","confidenceScore":"high",'
                    '"caveats":["Excludes refunds"],"handoffNotes":["Used notebook SDK."]}'
                ),
            }
        ],
        status_payload={"status": "Done"},
        trail_url="https://app.test/projects?file=analysis.py",
    )

    delivery = await DeliveryRenderer(model="", api_key="").render(packet)
    status = delivery_result_to_status(delivery, packet)
    slack_text = render_slack_final_message(packet, delivery)

    assert delivery.slack_message == "- Revenue increased."
    assert status["finalAnswer"] == "- Revenue increased."
    assert status["confidenceScore"] == "high"
    assert "*Analysis complete*" in slack_text
    assert "- Revenue increased." in slack_text
    assert "*Confidence:* high" in slack_text
    assert "<https://app.test/projects?file=analysis.py|Open authenticated notebook>" in slack_text


@pytest.mark.asyncio
async def test_delivery_renderer_empty_api_key_ignores_server_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-ant-key")
    packet = load_delivery_packet_from_events(
        [
            {
                "idx": 1,
                "type": "text",
                "content": (
                    'FINAL_STATEMENT: {"statement":"Revenue increased.",'
                    '"confidenceScore":"high","caveats":[],"handoffNotes":[]}'
                ),
            }
        ],
        status_payload={"status": "Done"},
    )

    class FailingClient:
        async def post(self, *_args, **_kwargs):
            raise AssertionError("server env key should not trigger model rendering")

    delivery = await DeliveryRenderer(
        model="claude-haiku-test",
        api_key="",
        http_client=FailingClient(),
    ).render(packet)  # type: ignore[arg-type]

    assert delivery.slack_message == "- Revenue increased."


@pytest.mark.asyncio
async def test_delivery_renderer_defaults_to_sonnet_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALPILOT_DELIVERY_MODEL", raising=False)
    packet = load_delivery_packet_from_events(
        [
            {
                "idx": 1,
                "type": "text",
                "content": (
                    'FINAL_STATEMENT: {"statement":"Revenue increased.",'
                    '"confidenceScore":"high","caveats":[],"handoffNotes":[]}'
                ),
            }
        ],
        status_payload={"status": "Done"},
    )
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "summary": "Revenue increased.",
                                "slackMessage": "- Revenue increased.",
                                "notionComment": "- Revenue increased.",
                                "finalAnswer": "- Revenue increased.",
                                "gotchas": [],
                                "analysisMethod": "Notebook SDK.",
                                "notionCharts": [],
                            }
                        ),
                    }
                ]
            }

    class FakeClient:
        async def post(self, _url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            del headers
            captured["json"] = json
            return FakeResponse()

    await DeliveryRenderer(api_key="test-key", http_client=FakeClient()).render(packet)  # type: ignore[arg-type]

    request_json = captured["json"]
    assert isinstance(request_json, dict)
    assert request_json["model"] == "claude-sonnet-4-5-20250929"


@pytest.mark.asyncio
async def test_delivery_renderer_preserves_packet_charts_when_model_returns_empty_chart_list() -> None:
    packet = load_delivery_packet_from_events(
        [],
        status_payload={
            "status": "Done",
            "notionCharts": [
                {"title": "Revenue trend", "url": "/api/notion-analysis/chart/req/revenue.png"},
                {"title": "Margin ranking", "url": "/api/notion-analysis/chart/req/margin.png"},
            ],
        },
    )

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "summary": "Revenue increased.",
                                "slackMessage": "- Revenue increased.",
                                "notionComment": "- Revenue increased.",
                                "finalAnswer": "- Revenue increased.",
                                "gotchas": [],
                                "analysisMethod": "Notebook SDK.",
                                "notionCharts": [],
                            }
                        ),
                    }
                ]
            }

    class FakeClient:
        async def post(self, _url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            del headers, json
            return FakeResponse()

    delivery = await DeliveryRenderer(model="claude-haiku-test", api_key="test-key", http_client=FakeClient()).render(
        packet
    )  # type: ignore[arg-type]
    status = delivery_result_to_status(delivery, packet)

    assert [chart["title"] for chart in delivery.notion_charts] == ["Revenue trend", "Margin ranking"]
    assert [chart["title"] for chart in status["notionCharts"]] == ["Revenue trend", "Margin ranking"]


@pytest.mark.asyncio
async def test_delivery_renderer_prompt_requires_separate_bullet_lines() -> None:
    packet = load_delivery_packet_from_events(
        [
            {
                "idx": 1,
                "type": "text",
                "content": (
                    'FINAL_STATEMENT: {"statement":"Revenue increased. Costs stayed flat.",'
                    '"confidenceScore":"high","caveats":[],"handoffNotes":[]}'
                ),
            }
        ],
        status_payload={"status": "Done"},
    )
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "summary": "Revenue increased.",
                                "slackMessage": "- Revenue increased.\n- Costs stayed flat.",
                                "notionComment": "- Revenue increased.\n- Costs stayed flat.",
                                "finalAnswer": "- Revenue increased.\n- Costs stayed flat.",
                                "gotchas": [],
                                "analysisMethod": "Notebook SDK.",
                                "notionCharts": [],
                            }
                        ),
                    }
                ]
            }

    class FakeClient:
        async def post(self, _url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    await DeliveryRenderer(model="claude-haiku-test", api_key="test-key", http_client=FakeClient()).render(packet)  # type: ignore[arg-type]

    request_json = captured["json"]
    assert isinstance(request_json, dict)
    system_prompt = request_json["system"]
    assert isinstance(system_prompt, str)
    assert "Each bullet must be on its own line and must start with '- '" in system_prompt
    assert "do not keep them inside one bullet" in system_prompt
