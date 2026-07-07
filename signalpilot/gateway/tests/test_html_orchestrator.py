from __future__ import annotations

import json

import pytest

from gateway.analysis_delivery.html_orchestrator import (
    HtmlOrchestrator,
    _html_orchestrator_system_prompt,
    _tool_args_dict,
)
from gateway.analysis_delivery.trace_loader import DeliveryPacket


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.requests = []

    async def post(self, url, *, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return _Response(self.payloads.pop(0))


@pytest.mark.asyncio
async def test_html_orchestrator_creates_dashboard_from_tool_use() -> None:
    client = _Client(
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "create_dashboard",
                    "input": {
                        "title": "Revenue Dashboard",
                        "html": '<!doctype html><html><body><script type="application/json" id="sp-data">{}</script></body></html>',
                        "data_json": {"rows": []},
                    },
                }
            ]
        }
    )
    result = await HtmlOrchestrator(api_key="key", http_client=client).render(
        DeliveryPacket(user_request="Build a revenue dashboard")
    )

    assert result.kind == "dashboard"
    assert result.title == "Revenue Dashboard"
    assert result.data_json == {"rows": []}
    assert client.requests[0]["json"]["system"] == _html_orchestrator_system_prompt()


@pytest.mark.asyncio
async def test_html_orchestrator_fetches_snapshot_then_creates_report() -> None:
    client = _Client(
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "fetch-1",
                    "name": "fetch_snapshot",
                    "input": {"name": "Revenue"},
                }
            ]
        },
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "create-1",
                    "name": "create_report",
                    "input": {
                        "title": "Revenue Report",
                        "html": '<!doctype html><html><body><script type="application/json" id="sp-data">{}</script></body></html>',
                    },
                }
            ]
        },
    )

    async def fetch_snapshot(snapshot):
        return {"snapshot": snapshot["name"], "rows": [{"revenue": 100}]}

    packet = DeliveryPacket(
        user_request="Create a report",
        data_snapshots=[{"name": "Revenue", "url": "/snapshot/revenue.json"}],
    )
    result = await HtmlOrchestrator(
        api_key="key",
        http_client=client,
        fetch_snapshot=fetch_snapshot,
    ).render(packet)

    tool_result = client.requests[1]["json"]["messages"][2]["content"][0]
    assert result.kind == "report"
    assert json.loads(tool_result["content"]) == {
        "snapshot": "Revenue",
        "rows": [{"revenue": 100}],
    }


def test_malformed_tool_args_return_none() -> None:
    assert _tool_args_dict({"type": "tool_use", "input": "not-json"}) is None


def test_html_system_contract_bans_audit_language() -> None:
    prompt = _html_orchestrator_system_prompt()

    assert "Do not use CDNs" in prompt
    assert "confidence score" in prompt
    assert "audit notes" in prompt
    assert "trail links" in prompt


def test_html_orchestrator_timeout_defaults_to_long_dashboard_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALPILOT_ORCHESTRATOR_TIMEOUT_SECONDS", raising=False)

    assert HtmlOrchestrator(api_key="key").timeout_seconds == 90.0


def test_html_orchestrator_timeout_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALPILOT_ORCHESTRATOR_TIMEOUT_SECONDS", "120")

    assert HtmlOrchestrator(api_key="key").timeout_seconds == 120.0
