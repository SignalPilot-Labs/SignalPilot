from __future__ import annotations

import json
import logging
from copy import deepcopy

import httpx
import pytest

from gateway.analysis_delivery.html_orchestrator import (
    _HTML_COMPONENT_CONTRACT,
    HtmlDeliverableResult,
    HtmlOrchestrator,
    _html_orchestrator_system_prompt,
    _normalize_html_result,
    _tool_args_dict,
)
from gateway.analysis_delivery.trace_loader import DeliveryPacket
from gateway.models.deliverable_theme import (
    DEFAULT_CHART_SERIES,
    DeliverableTheme,
    ThemeColors,
    chart_series_from_positive,
)


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
        self.requests.append({"url": url, "headers": headers, "json": deepcopy(json)})
        payload = self.payloads.pop(0)
        return payload if hasattr(payload, "raise_for_status") else _Response(payload)


class _ErrorResponse:
    def __init__(self, payload, *, status_code: int = 400):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def raise_for_status(self) -> None:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(self.status_code, text=self.text, request=request)
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    def json(self):
        return self._payload


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
    assert result.html.count('id="sp-design-system"') == 1
    assert "--sp-bg: #050505" in result.html
    assert '<script type="application/json" id="sp-data">{"rows":[]}</script>' in result.html
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
    assert result.data_json == {"Revenue": {"snapshot": "Revenue", "rows": [{"revenue": 100}]}}
    assert result.html.index('id="sp-data"') < result.html.index("</body>")
    assert '{"Revenue":{"snapshot":"Revenue","rows":[{"revenue":100}]}}' in result.html
    assert json.loads(tool_result["content"]) == {
        "snapshot": "Revenue",
        "rows": [{"revenue": 100}],
    }


@pytest.mark.asyncio
async def test_fetched_snapshot_overrides_model_data_json_for_same_key() -> None:
    client = _Client(
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "fetch-1",
                    "name": "fetch_snapshot",
                    "input": {"name": "latest_financial_metrics"},
                }
            ]
        },
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "create-1",
                    "name": "create_dashboard",
                    "input": {
                        "title": "Revenue Dashboard",
                        "html": '<!doctype html><html><body><script type="application/json" id="sp-data">{}</script></body></html>',
                        "data_json": {
                            "latest_financial_metrics": {
                                "rows": [{"company_name": "Northstar", "monthly_revenue_mm": 999}]
                            }
                        },
                    },
                }
            ]
        },
    )

    async def fetch_snapshot(snapshot):
        return {
            "name": snapshot["name"],
            "rows": [{"company_name": "Northstar", "monthly_revenue_mm": 22.45}],
        }

    result = await HtmlOrchestrator(
        api_key="key",
        http_client=client,
        fetch_snapshot=fetch_snapshot,
    ).render(
        DeliveryPacket(
            user_request="Create a dashboard",
            data_snapshots=[{"name": "latest_financial_metrics", "url": "/snapshot/latest.json"}],
        )
    )

    assert result.data_json == {
        "latest_financial_metrics": {
            "name": "latest_financial_metrics",
            "rows": [{"company_name": "Northstar", "monthly_revenue_mm": 22.45}],
        }
    }
    assert "22.45" in result.html
    assert '"monthly_revenue_mm":999' not in result.html


@pytest.mark.asyncio
async def test_html_orchestrator_moves_empty_data_island_before_reader_script() -> None:
    html = """<!doctype html><html><body>
<script>const data = JSON.parse(document.getElementById('sp-data').textContent);</script>
<script type="application/json" id="sp-data">
</script>
</body></html>"""
    client = _Client(
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "fetch-1",
                    "name": "fetch_snapshot",
                    "input": {"name": "portfolio_overview"},
                }
            ]
        },
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "create-1",
                    "name": "create_dashboard",
                    "input": {
                        "title": "Portfolio Dashboard",
                        "html": html,
                    },
                }
            ]
        },
    )

    async def fetch_snapshot(snapshot):
        return [{"sector": "Software", "company_count": 1}]

    result = await HtmlOrchestrator(
        api_key="key",
        http_client=client,
        fetch_snapshot=fetch_snapshot,
    ).render(
        DeliveryPacket(
            user_request="Create a dashboard",
            data_snapshots=[{"name": "portfolio_overview", "url": "/snapshot/portfolio.json"}],
        )
    )

    assert result.html.count('id="sp-data"') == 1
    assert result.html.index('id="sp-data"') < result.html.index("JSON.parse")
    assert '"portfolio_overview":[{"sector":"Software","company_count":1}]' in result.html


@pytest.mark.asyncio
async def test_html_orchestrator_renders_followup_with_existing_report_payload() -> None:
    client = _Client(
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "edit-1",
                    "name": "edit_dashboard",
                    "input": {
                        "report_id": "report-1",
                        "title": "Revenue Dashboard",
                        "html": '<!doctype html><html><body><script type="application/json" id="sp-data">{}</script></body></html>',
                        "data_json": {"rows": []},
                    },
                }
            ]
        }
    )

    result = await HtmlOrchestrator(api_key="key", http_client=client).render_followup(
        instruction="Make the main chart a bar chart.",
        existing={
            "report_id": "report-1",
            "kind": "dashboard",
            "title": "Revenue Dashboard",
            "html": "<html>old</html>",
            "data_json": {"old": True},
        },
        packet=None,
        mode="edit_existing",
    )

    payload = json.loads(client.requests[0]["json"]["messages"][0]["content"])
    tool_names = {tool["name"] for tool in client.requests[0]["json"]["tools"]}
    assert result.report_id == "report-1"
    assert payload["task"] == "update_existing_html_deliverable"
    assert payload["existing"]["reportId"] == "report-1"
    assert payload["freshAnalysis"] is None
    assert "fetch_snapshot" not in tool_names
    assert client.requests[0]["json"]["tool_choice"] == {"type": "tool", "name": "edit_dashboard"}
    assert client.requests[0]["json"]["max_tokens"] == 30_000


@pytest.mark.asyncio
async def test_html_orchestrator_retries_lower_max_tokens_when_anthropic_rejects() -> None:
    client = _Client(
        _ErrorResponse(
            {
                "error": {
                    "type": "invalid_request_error",
                    "message": "max_tokens: Input should be less than or equal to 30000",
                }
            }
        ),
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "edit-1",
                    "name": "edit_dashboard",
                    "input": {
                        "report_id": "report-1",
                        "title": "Revenue Dashboard",
                        "html": '<!doctype html><html><body><script type="application/json" id="sp-data">{}</script></body></html>',
                    },
                }
            ]
        },
    )

    orchestrator = HtmlOrchestrator(api_key="key", http_client=client)
    orchestrator.max_tokens = 64_000

    result = await orchestrator.render_followup(
        instruction="Make the title shorter.",
        existing={
            "report_id": "report-1",
            "kind": "dashboard",
            "title": "Revenue Dashboard",
            "html": "<html>old</html>",
            "data_json": {},
        },
        packet=None,
        mode="edit_existing",
    )

    assert result.title == "Revenue Dashboard"
    assert [request["json"]["max_tokens"] for request in client.requests] == [64_000, 30_000]


@pytest.mark.asyncio
async def test_html_orchestrator_surfaces_and_logs_anthropic_error_body(caplog: pytest.LogCaptureFixture) -> None:
    client = _Client(
        _ErrorResponse(
            {
                "error": {
                    "type": "invalid_request_error",
                    "message": "messages.0.content: Input is too long for the model context window",
                }
            }
        )
    )

    with caplog.at_level(logging.ERROR, logger="gateway.analysis_delivery.html_orchestrator"):
        with pytest.raises(RuntimeError) as exc_info:
            await HtmlOrchestrator(api_key="key", http_client=client).render_followup(
                instruction="Make the title shorter.",
                existing={
                    "report_id": "report-1",
                    "kind": "dashboard",
                    "title": "Revenue Dashboard",
                    "html": "<html>old</html>",
                    "data_json": {},
                },
                packet=None,
                mode="edit_existing",
            )

    message = str(exc_info.value)
    assert "invalid_request_error: messages.0.content: Input is too long" in message
    assert "payload_chars=" in message
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "status=400" in log_text
    assert "model=claude-sonnet-4-5-20250929" in log_text
    assert "max_tokens=30000" in log_text
    assert "payload_chars=" in log_text
    assert "messages=1" in log_text
    assert "tool_choice=edit_dashboard" in log_text
    assert "invalid_request_error: messages.0.content: Input is too long" in log_text


@pytest.mark.asyncio
async def test_html_orchestrator_logs_loop_limit_context(caplog: pytest.LogCaptureFixture) -> None:
    client = _Client(
        {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "edit-1",
                    "name": "edit_dashboard",
                    "input": {
                        "report_id": "report-1",
                        "title": "Revenue Dashboard",
                        "html": "",
                        "data_json": {},
                    },
                }
            ],
        },
        {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "edit-2",
                    "name": "edit_dashboard",
                    "input": {
                        "report_id": "report-1",
                        "title": "Revenue Dashboard",
                        "data_json": {},
                    },
                }
            ],
        },
    )
    orchestrator = HtmlOrchestrator(api_key="key", http_client=client)
    orchestrator.tool_loop_limit = 2

    with caplog.at_level(logging.INFO, logger="gateway.analysis_delivery.html_orchestrator"):
        with pytest.raises(TimeoutError):
            await orchestrator.render_followup(
                instruction="Make the title shorter.",
                existing={
                    "report_id": "report-1",
                    "kind": "dashboard",
                    "title": "Revenue Dashboard",
                    "html": "<html>old</html>",
                    "data_json": {},
                },
                packet=None,
                mode="edit_existing",
            )

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "HTML orchestrator iteration did not produce deliverable; sending tool feedback" in log_text
    assert "iteration=1/2" in log_text
    assert "tool_choice=edit_dashboard" in log_text
    assert "content_types=tool_use:1" in log_text
    assert "tool_uses=edit_dashboard(title=True,html_chars=0,data_json=True,report_id=True)" in log_text
    assert "tool_results=edit-1:error" in log_text
    assert "HTML orchestrator exceeded tool loop limit" in log_text
    assert "loop_limit=2" in log_text
    assert "last_tool_uses=edit_dashboard(title=True,html_chars=0,data_json=True,report_id=True)" in log_text


def test_malformed_tool_args_return_none() -> None:
    assert _tool_args_dict({"type": "tool_use", "input": "not-json"}) is None


def test_html_system_contract_bans_audit_language() -> None:
    prompt = _html_orchestrator_system_prompt()

    assert "Do not use CDNs" in prompt
    assert "target under 3.5 MB" in prompt
    assert "never exceed 4 MB" in prompt
    assert "5 MB hard cap" in prompt
    assert "confidence score" in prompt
    assert "audit notes" in prompt
    assert "trail links" in prompt


def test_html_system_contract_requires_design_tokens() -> None:
    prompt = _html_orchestrator_system_prompt()

    assert "var(--sp-bg)" in prompt
    assert "Never use hex" in prompt
    assert "sp-delta-up" in prompt
    assert "Chart colors are rank encoding" in prompt
    assert "var(--sp-chart-1) for the greatest value" in prompt
    assert "Slice paths must be mathematically circular" in prompt


def test_default_chart_series_is_ranked_green_scale() -> None:
    assert DEFAULT_CHART_SERIES == [
        "#087a3d",
        "#0fa45a",
        "#35c978",
        "#8eeaa8",
        "#c8f8d4",
        "#e7fcec",
    ]


def test_html_orchestrator_injects_custom_theme_and_replaces_stale_style() -> None:
    html = """<!doctype html><html><head>
<style id="sp-design-system">:root { --sp-bg: #ff0000; }</style>
</head><body><main class="sp-report">Report</main></body></html>"""
    theme = DeliverableTheme(
        colors=ThemeColors(bg="#101010", text="#fafafa", positive="#12ab34"),
        chart_series=["#123456", "#abcdef", "#fedcba"],
    )

    result = _normalize_html_result(
        HtmlDeliverableResult(kind="report", title="Report", html=html),
        {},
        theme=theme,
    )

    assert result.html.count('id="sp-design-system"') == 1
    assert "--sp-bg: #101010" in result.html
    assert "--sp-positive: #12ab34" in result.html
    assert "--sp-chart-2: #0f8c2b" in result.html
    assert "#abcdef" not in result.html
    assert "#ff0000" not in result.html


def test_html_orchestrator_derives_chart_scale_from_positive_color() -> None:
    html = '<!doctype html><html><head></head><body><main class="sp-report">Report</main></body></html>'
    theme = DeliverableTheme(
        colors=ThemeColors(positive="#3366ff"),
        chart_series=["#111111", "#222222", "#333333"],
    )

    result = _normalize_html_result(
        HtmlDeliverableResult(kind="report", title="Report", html=html),
        {},
        theme=theme,
    )

    expected = chart_series_from_positive("#3366ff")
    assert f"--sp-chart-1: {expected[0]}" in result.html
    assert f"--sp-chart-6: {expected[5]}" in result.html
    assert "#111111" not in result.html


def test_html_orchestrator_preserves_existing_data_island_when_data_json_omitted() -> None:
    html = """<!doctype html><html><head></head><body>
<script type="application/json" id="sp-data">{"rows":[{"revenue":100}]}</script>
<main class="sp-report">Report</main>
</body></html>"""

    result = _normalize_html_result(
        HtmlDeliverableResult(kind="report", title="Report", html=html),
        {},
    )

    assert result.data_json is None
    assert result.html.count('id="sp-data"') == 1
    assert '{"rows":[{"revenue":100}]}' in result.html
    assert '<script type="application/json" id="sp-data">{}</script>' not in result.html


def test_html_orchestrator_stabilizes_generated_bar_chart_layout() -> None:
    html = """<!doctype html><html><head></head><body>
<div class="chart-container">
  <div class="bar-chart">
    <div class="bar-group">
      <div class="bar" style="height: 80%;"></div>
      <div class="bar-label">Revenue</div>
    </div>
  </div>
</div>
</body></html>"""

    result = _normalize_html_result(
        HtmlDeliverableResult(kind="dashboard", title="Revenue", html=html),
        {},
    )

    assert 'id="sp-bar-chart-layout-guard"' in result.html
    assert ".bar-chart .bar-group" in result.html
    assert "flex-direction: row !important;" in result.html
    assert "grid-template-rows: 1.4rem minmax(0, 1fr) 3.2rem;" in result.html
    assert ".bar-chart .bar {\n    grid-row: 2;" in result.html
    assert result.html.index('id="sp-bar-chart-layout-guard"') < result.html.index("</head>")


def test_html_orchestrator_supports_horizontal_pipeline_bars() -> None:
    html = """<!doctype html><html><head></head><body>
<div class="sp-chart-card">
  <h3>Pipeline by Stage</h3>
  <div class="sp-chart">
    <div class="sp-bar-chart">
      <div class="sp-bar-group">
        <div class="bar-label">Legal review</div>
        <div class="bar-track"><div class="sp-bar" style="width: 100%;"></div></div>
        <div class="bar-value">$1.25M</div>
      </div>
    </div>
  </div>
</div>
</body></html>"""

    result = _normalize_html_result(
        HtmlDeliverableResult(kind="dashboard", title="Pipeline", html=html),
        {},
    )

    assert ".sp-horizontal-bar-chart" in result.html
    assert '.sp-bar-chart:has(.bar-track .sp-bar[style*="width"])' in result.html
    assert "flex-direction: column !important;" in result.html
    assert "grid-template-columns: minmax(7.5rem, 11rem) minmax(0, 1fr) max-content;" in result.html
    assert "do not render pipeline stages as vertical columns" in _HTML_COMPONENT_CONTRACT


def test_html_orchestrator_keeps_height_based_tracked_column_chart_visible() -> None:
    html = """<!doctype html><html><head></head><body>
<div class="sp-chart-card">
  <h3>Revenue by Company</h3>
  <div class="sp-chart sp-bar-chart">
    <div class="chart-content">
      <div class="sp-bar-group">
        <div class="bar-value">$22.5M</div>
        <div class="bar-track">
          <div class="sp-bar sp-chart-rank-1" style="height: 100%;"></div>
        </div>
        <div class="bar-label">Northstar Logistics</div>
      </div>
      <div class="sp-bar-group">
        <div class="bar-value">$16.5M</div>
        <div class="bar-track">
          <div class="sp-bar sp-chart-rank-2" style="height: 73%;"></div>
        </div>
        <div class="bar-label">TrueNorth Healthcare</div>
      </div>
    </div>
  </div>
</div>
</body></html>"""

    result = _normalize_html_result(
        HtmlDeliverableResult(kind="dashboard", title="Revenue by Company", html=html),
        {},
    )

    assert ".sp-bar-chart > .chart-content" in result.html
    assert ".sp-bar-chart .bar-track" in result.html
    assert ".bar-chart .sp-bar-track {\n    grid-row: 2;" in result.html
    assert ".sp-bar-chart:has(.bar-track),\n" not in result.html
    assert '.sp-bar-chart:has(.bar-track .sp-bar[style*="width"])' in result.html
    assert "Do not wrap vertical column bars in .bar-track" in _HTML_COMPONENT_CONTRACT


def test_html_orchestrator_injects_ranked_chart_and_pie_styles() -> None:
    html = """<!doctype html><html><head></head><body>
<main class="sp-report">
  <section class="sp-chart-card">
    <h3>Enterprise Customers</h3>
    <div class="sp-chart">
      <div class="sp-pie-chart">
        <svg class="sp-pie-graphic" viewBox="0 0 200 200"></svg>
      </div>
    </div>
  </section>
</main>
</body></html>"""

    result = _normalize_html_result(
        HtmlDeliverableResult(kind="dashboard", title="Customers", html=html),
        {},
    )

    assert ".sp-chart-rank-1" in result.html
    assert ".sp-pie-graphic" in result.html
    assert "aspect-ratio: 1 / 1;" in result.html
    assert ".sp-pie-slice-label" in result.html


def test_html_orchestrator_normalizes_generated_pie_slice_geometry() -> None:
    html = """<!doctype html><html><head></head><body>
<main class="sp-report">
  <section class="sp-chart-card">
    <div class="sp-chart sp-pie-chart">
      <div class="sp-pie-graphic">
        <svg viewBox="0 0 200 200" preserveAspectRatio="xMidYMid meet">
          <path d="M 100 100 L 100 10 A 90 90 0 0 1 177.94 64.95 Z" style="fill: var(--sp-chart-1);"></path>
          <path d="M 100 100 L 177.94 64.95 A 90 90 0 0 1 164.95 157.94 Z" style="fill: var(--sp-chart-2);"></path>
          <path d="M 100 100 L 164.95 157.94 A 90 90 0 0 1 35.05 157.94 Z" style="fill: var(--sp-chart-3);"></path>
          <path d="M 100 100 L 35.05 157.94 A 90 90 0 0 1 100 10 Z" style="fill: var(--sp-chart-4);"></path>
        </svg>
      </div>
      <div class="legend">
        <div class="legend-item"><div class="legend-value">35%</div></div>
        <div class="legend-item"><div class="legend-value">28%</div></div>
        <div class="legend-item"><div class="legend-value">22%</div></div>
        <div class="legend-item"><div class="legend-value">15%</div></div>
      </div>
    </div>
  </section>
</main>
</body></html>"""

    result = _normalize_html_result(
        HtmlDeliverableResult(kind="dashboard", title="Customers", html=html),
        {},
    )

    assert "L 177.94 64.95" not in result.html
    assert "M 100 100 L 100 10 A 90 90 0 0 1 172.81 152.9 Z" in result.html
    assert 'style="fill: var(--sp-chart-1);"' in result.html


def test_html_orchestrator_default_max_tokens_uses_fixed_output_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALPILOT_ORCHESTRATOR_MAX_TOKENS", raising=False)

    assert HtmlOrchestrator(api_key="key").max_tokens == 30_000


def test_html_orchestrator_ignores_env_max_tokens_for_fixed_output_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALPILOT_ORCHESTRATOR_MAX_TOKENS", "20000")

    assert HtmlOrchestrator(api_key="key").max_tokens == 30_000


def test_html_orchestrator_timeout_defaults_to_long_dashboard_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALPILOT_ORCHESTRATOR_TIMEOUT_SECONDS", raising=False)

    assert HtmlOrchestrator(api_key="key").timeout_seconds == 240.0


def test_html_orchestrator_timeout_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALPILOT_ORCHESTRATOR_TIMEOUT_SECONDS", "120")

    assert HtmlOrchestrator(api_key="key").timeout_seconds == 120.0


def test_html_orchestrator_tool_loop_limit_defaults_to_eight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALPILOT_ORCHESTRATOR_TOOL_LOOP_LIMIT", raising=False)

    assert HtmlOrchestrator(api_key="key").tool_loop_limit == 8


def test_html_orchestrator_tool_loop_limit_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALPILOT_ORCHESTRATOR_TOOL_LOOP_LIMIT", "12")

    assert HtmlOrchestrator(api_key="key").tool_loop_limit == 12
