"""Security contracts for standalone chat execution and publication tools."""

from __future__ import annotations

import base64
import io
import json

import pytest
from PIL import Image
from starlette.exceptions import HTTPException

from signalpilot._server.ai import claude_agent
from signalpilot._server.ai.claude_agent import _apply_auth_config
from signalpilot._server.ai.standalone_chat_chart_theme import (
    CHART_BACKGROUND,
    CHART_COLORS,
    MAX_CHART_CATEGORIES,
    MAX_CHART_SERIES,
    prepare_signalpilot_chart,
)
from signalpilot._server.ai.standalone_chat_tools import (
    _render_chart_png,
    _run_restricted_python,
)
from signalpilot._server.api.endpoints.standalone_chat import (
    STANDALONE_ALLOWED_TOOLS,
    STANDALONE_SYSTEM_PROMPT,
    _require_execution_scope,
    _runtime_auth_override,
    _scoped_gateway_mcp_config,
)


def test_restricted_python_allows_in_memory_analysis_only():
    assert _run_restricted_python(
        "result = {'total': sum(row['value'] for row in data)}",
        [{"value": 2}, {"value": 3}],
    ) == {"result": {"total": 5}}

    for source in (
        "import os\nresult = os.environ",
        "result = open('/etc/passwd').read()",
        "result = __import__('subprocess').run(['id'])",
        "result = (1).__class__",
        "while True:\n    pass\nresult = 1",
        "result = [0] * 1000000",
    ):
        with pytest.raises(ValueError):
            _run_restricted_python(source, None)


def test_ephemeral_agent_session_mapping_never_writes_to_disk(monkeypatch):
    key = "standalone:test-run"
    claude_agent._chat_sessions.pop(key, None)
    writes: list[bool] = []
    monkeypatch.setattr(
        claude_agent,
        "_save_chat_sessions",
        lambda: writes.append(True),
    )

    session_id, resumed = claude_agent._get_or_create_chat_session(
        key,
        persist=False,
    )
    assert session_id
    assert resumed is False
    claude_agent.clear_chat_session(key, persist=False)
    assert key not in claude_agent._chat_sessions
    assert writes == []


def test_runtime_auth_is_request_scoped_and_validated():
    assert _runtime_auth_override(
        {"runtime_auth": {"type": "api_key", "token": "sk-ant-test"}}
    ) == {"type": "api_key", "token": "sk-ant-test"}
    with pytest.raises(HTTPException, match="Invalid runtime credential"):
        _runtime_auth_override(
            {"runtime_auth": {"type": "api_key", "token": ""}}
        )

    process_env = {
        "CLAUDE_CODE_OAUTH_TOKEN": "old-oauth",
        "OAUTH_TOKEN": "old-alias",
    }
    execution_env = dict(process_env)
    _apply_auth_config(
        execution_env,
        {"type": "api_key", "token": "sk-ant-user"},
    )
    assert execution_env["ANTHROPIC_API_KEY"] == "sk-ant-user"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in execution_env
    assert "OAUTH_TOKEN" not in execution_env
    assert process_env == {
        "CLAUDE_CODE_OAUTH_TOKEN": "old-oauth",
        "OAUTH_TOKEN": "old-alias",
    }


def test_chart_renderer_produces_a_real_png():
    encoded = _render_chart_png(
        {
            "mark": "bar",
            "encoding": {
                "x": {"field": "month"},
                "y": {"field": "revenue"},
            },
        },
        [{"month": "Jan", "revenue": 10}, {"month": "Feb", "revenue": 14}],
    )
    assert encoded is not None
    assert base64.b64decode(encoded).startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("mark", ["bar", "line", "point"])
def test_chart_renderer_uses_the_canonical_dark_theme_for_supported_marks(
    mark,
):
    encoded = _render_chart_png(
        {
            "title": {"text": f"{mark.title()} chart", "color": "#000000"},
            "background": "#000000",
            "mark": {"type": mark, "color": "#000000"},
            "encoding": {
                "x": {"field": "month", "type": "nominal"},
                "y": {"field": "revenue", "type": "quantitative"},
                "color": {
                    "field": "region",
                    "type": "nominal",
                    "scale": {"range": ["#000000"]},
                },
            },
        },
        [
            {
                "month": "January with a long label",
                "revenue": -2_000_000,
                "region": "North",
            },
            {
                "month": "February with a long label",
                "revenue": None,
                "region": "North",
            },
            {
                "month": "March with a long label",
                "revenue": 3_500_000_000,
                "region": "North",
            },
            {
                "month": "January with a long label",
                "revenue": 1_200_000,
                "region": "South",
            },
            {
                "month": "February with a long label",
                "revenue": 2_400_000,
                "region": "South",
            },
            {
                "month": "March with a long label",
                "revenue": 2_900_000,
                "region": "South",
            },
        ],
    )
    assert encoded is not None
    image = Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")
    colors = {
        color
        for _, color in image.getcolors(maxcolors=image.width * image.height)
        or []
    }
    assert tuple(bytes.fromhex(CHART_BACKGROUND.removeprefix("#"))) in colors
    assert tuple(bytes.fromhex(CHART_COLORS[0].removeprefix("#"))) in colors
    assert tuple(bytes.fromhex(CHART_COLORS[1].removeprefix("#"))) in colors


def test_agent_chart_styles_cannot_override_theme_or_density_limits():
    rows = [
        {
            "category": f"Category {category}",
            "value": category,
            "series": f"Series {series}",
        }
        for category in range(MAX_CHART_CATEGORIES + 1)
        for series in range(MAX_CHART_SERIES + 1)
    ]
    spec, display_rows, display = prepare_signalpilot_chart(
        {
            "background": "#000000",
            "mark": {"type": "bar", "color": "#000000"},
            "config": {"axis": {"labelColor": "#000000"}},
            "encoding": {
                "x": {"field": "category", "type": "nominal"},
                "y": {"field": "value", "type": "quantitative"},
                "color": {
                    "field": "series",
                    "type": "nominal",
                    "scale": {"range": ["#000000"]},
                },
            },
        },
        rows,
    )

    assert spec["background"] == CHART_BACKGROUND
    assert spec["config"]["range"]["category"] == list(CHART_COLORS)
    assert "#000000" not in str(spec)
    assert len(display_rows) == MAX_CHART_CATEGORIES * MAX_CHART_SERIES
    assert display["limited"] is True


def test_horizontal_bar_renderer_handles_long_categories_and_negative_values():
    encoded = _render_chart_png(
        {
            "title": "Net revenue by account segment",
            "mark": "bar",
            "encoding": {
                "x": {"field": "revenue", "type": "quantitative"},
                "y": {"field": "segment", "type": "nominal"},
            },
        },
        [
            {"segment": "Large enterprise accounts", "revenue": 3_500_000_000},
            {"segment": "Recently refunded accounts", "revenue": -900_000_000},
            {"segment": "Accounts without measurements", "revenue": None},
        ],
    )
    assert encoded is not None
    image = Image.open(io.BytesIO(base64.b64decode(encoded)))
    assert image.size == (1_200, 750)


def test_execution_scope_is_frozen_to_claimed_run(monkeypatch):
    monkeypatch.setenv("SP_CHAT_RUN_ID", "run-12345678")
    monkeypatch.setenv("SP_CHAT_PROJECT_ID", "project-a")
    monkeypatch.setenv("SP_CHAT_BRANCH", "main")
    monkeypatch.setenv("SP_CHAT_CONNECTION_NAME", "production")

    assert _require_execution_scope(
        {
            "run_id": "run-12345678",
            "project_id": "project-a",
            "branch": "main",
            "connection_name": "production",
        }
    ) == ("run-12345678", "project-a", "main", "production")
    with pytest.raises(HTTPException, match="Execution scope mismatch"):
        _require_execution_scope(
            {
                "run_id": "run-12345678",
                "project_id": "project-a",
                "branch": "main",
                "connection_name": "another-connection",
            }
        )


def test_gateway_mcp_uses_the_per_run_read_only_identity(monkeypatch):
    claims = {
        "execution_identity": "chat:run-12345678",
        "project_id": "project-a",
        "branch": "main",
        "connection_name": "production",
        "scopes": ["read", "query", "execute"],
    }
    payload = (
        base64.urlsafe_b64encode(json.dumps(claims).encode())
        .decode()
        .rstrip("=")
    )
    token = f"header.{payload}.signature"
    monkeypatch.setenv("SP_GATEWAY_INTERNAL_URL", "http://gateway:3300")
    config = _scoped_gateway_mcp_config(
        {"gateway_session_token": token},
        run_id="run-12345678",
        project_id="project-a",
        branch="main",
        connection_name="production",
    )
    server = config["mcpServers"]["signalpilot"]
    assert server["url"] == "http://gateway:3300/mcp"
    assert server["headers"]["Authorization"] == f"Bearer {token}"

    claims["connection_name"] = "another-connection"
    bad_payload = (
        base64.urlsafe_b64encode(json.dumps(claims).encode())
        .decode()
        .rstrip("=")
    )
    with pytest.raises(
        HTTPException, match="Scoped gateway identity mismatch"
    ):
        _scoped_gateway_mcp_config(
            {"gateway_session_token": f"header.{bad_payload}.signature"},
            run_id="run-12345678",
            project_id="project-a",
            branch="main",
            connection_name="production",
        )


def test_agent_contract_excludes_mutating_and_external_tools():
    assert "English only" in STANDALONE_SYSTEM_PROMPT
    assert "Never guess" in STANDALONE_SYSTEM_PROMPT
    assert "chain-of-thought" in STANDALONE_SYSTEM_PROMPT
    assert all(
        "notion" not in tool.lower() for tool in STANDALONE_ALLOWED_TOOLS
    )
    assert all(
        "github" not in tool.lower() for tool in STANDALONE_ALLOWED_TOOLS
    )
    assert all(
        forbidden not in STANDALONE_ALLOWED_TOOLS
        for forbidden in ("Bash", "Write", "Edit", "WebFetch", "WebSearch")
    )
