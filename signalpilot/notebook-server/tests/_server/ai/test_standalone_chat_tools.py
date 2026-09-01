"""Security contracts for standalone chat execution and publication tools."""

from __future__ import annotations

import base64
import io
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    ListToolsRequest,
    TextContent,
)
from PIL import Image
from starlette.exceptions import HTTPException

if TYPE_CHECKING:
    from pathlib import Path

from signalpilot._server.ai import claude_agent
from signalpilot._server.ai.chat_runtime_output import (
    ChatRuntimeSessionScopeError,
    authorize_chat_runtime_session,
    compact_chat_runtime_output,
    notebook_server_headers,
)
from signalpilot._server.ai.claude_agent import _apply_auth_config
from signalpilot._server.ai.standalone_chat_chart_theme import (
    CHART_BACKGROUND,
    CHART_COLORS,
    MAX_CHART_CATEGORIES,
    MAX_CHART_SERIES,
    prepare_signalpilot_chart,
)
from signalpilot._server.ai.standalone_chat_tools import (
    StandaloneArtifactCollector,
    StandaloneNotebookLifecycle,
    _render_chart_png,
    build_standalone_chat_mcp_server,
)
from signalpilot._server.api.endpoints.standalone_chat import (
    IMPROVEMENT_EXTRA_TOOLS,
    STANDALONE_ALLOWED_TOOLS,
    STANDALONE_DISALLOWED_MCP_TOOLS,
    STANDALONE_SYSTEM_PROMPT,
    _runtime_auth_override,
)
from signalpilot._server.api.endpoints.standalone_chat_prompt import (
    _execution_prompt_values,
)


def test_chat_runtime_notebook_outputs_are_redacted_and_preview_bounded():
    payload = json.dumps(
        {
            "rows": [
                {"token": "secret-token", "value": value}
                for value in range(100)
            ]
        }
    )
    rendered = compact_chat_runtime_output(
        payload,
        mimetype="application/json",
        redactions=("secret-token",),
    )

    assert "secret-token" not in rendered
    assert "[REDACTED]" in rendered
    assert "__omitted_items__" in rendered
    assert len(rendered) <= 4_024


def test_chat_runtime_notebook_tools_are_bound_to_the_current_kernel():
    def authorize(session_id: str) -> bool:
        return session_id == "run-kernel"

    authorize_chat_runtime_session(
        "run_cells", {"session_id": "run-kernel"}, authorize
    )
    with pytest.raises(
        ChatRuntimeSessionScopeError, match="NOTEBOOK_SESSION_SCOPE_MISMATCH"
    ):
        authorize_chat_runtime_session(
            "run_cells", {"session_id": "other-kernel"}, authorize
        )
    with pytest.raises(
        ChatRuntimeSessionScopeError, match="NOTEBOOK_SESSION_SCOPE_MISMATCH"
    ):
        authorize_chat_runtime_session("start_notebook_session", {}, authorize)


def test_internal_notebook_http_headers_include_both_auth_tokens():
    assert notebook_server_headers(
        auth_token="session-token",
        server_token="server-token",
        session_id="session-a",
    ) == {
        "Authorization": "Bearer session-token",
        "Content-Type": "application/json",
        "Sp-Server-Token": "server-token",
        "Sp-Session-Id": "session-a",
    }


@pytest.mark.asyncio
async def test_publication_failures_are_mcp_tool_errors():
    config = build_standalone_chat_mcp_server(StandaloneArtifactCollector())
    server = config["instance"]
    response = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="publish_table",
                arguments={"filename": "revenue.csv", "result_id": "missing"},
            )
        )
    )

    assert response.root.isError is True
    assert (
        "governed structured result ID is required"
        in response.root.content[0].text
    )


@pytest.mark.asyncio
async def test_report_tools_require_a_complete_catalog_scan_and_one_valid_proposal():
    collector = StandaloneArtifactCollector(
        artifacts=[
            {
                "kind": "table",
                "filename": "revenue.csv",
                "payload": {
                    "columns": [{"name": "revenue"}],
                    "rows": [{"revenue": 100}],
                    "completeness": "complete",
                    "truncated": False,
                },
            }
        ]
    )

    async def load_catalog(cursor: str | None) -> dict[str, Any]:
        return {
            "items": [],
            "next_cursor": "page-2" if cursor is None else None,
            "catalog_revision": "revision-a",
            "total_reports": 51,
            "proactive_creation_allowed": True,
        }

    config = build_standalone_chat_mcp_server(
        collector,
        report_catalog_loader=load_catalog,
    )
    server = config["instance"]
    await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="list_saved_report_catalog",
                arguments={},
            )
        )
    )
    incomplete = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "create",
                    "artifact_kind": "table",
                    "artifact_filename": "revenue.csv",
                    "title": "Revenue",
                    "reason": "No semantic match exists.",
                },
            )
        )
    )
    assert incomplete.root.isError is True
    assert "every saved report catalog page" in incomplete.root.content[0].text

    final_page = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="list_saved_report_catalog",
                arguments={"cursor": "page-2"},
            )
        )
    )
    assert final_page.root.isError is False
    proposed = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "create",
                    "artifact_kind": "table",
                    "artifact_filename": "revenue.csv",
                    "title": "Revenue",
                    "reason": "No semantic match exists.",
                },
            )
        )
    )
    assert proposed.root.isError is False
    assert collector.report_proposal == {
        "action": "create",
        "artifact_kind": "table",
        "artifact_filename": "revenue.csv",
        "title": "Revenue",
        "reason": "No semantic match exists.",
        "existing_report_id": None,
        "catalog_revision": "revision-a",
        "catalog_scan_complete": True,
        "proactive_creation_allowed": True,
        "loaded_report_ids": [],
        "attached_report_id": None,
    }
    repeated = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "create",
                    "artifact_kind": "table",
                    "artifact_filename": "revenue.csv",
                    "title": "Revenue copy",
                    "reason": "Try again.",
                },
            )
        )
    )
    assert repeated.root.isError is True
    assert "Only one report action outcome" in repeated.root.content[0].text


@pytest.mark.asyncio
async def test_complete_publication_requires_a_catalog_backed_report_outcome():
    collector = StandaloneArtifactCollector()

    async def load_catalog(_cursor: str | None) -> dict[str, Any]:
        return {
            "items": [],
            "next_cursor": None,
            "catalog_revision": "revision-empty",
            "total_reports": 0,
            "proactive_creation_allowed": True,
        }

    server = build_standalone_chat_mcp_server(
        collector,
        report_catalog_loader=load_catalog,
    )["instance"]
    published = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="publish_report",
                arguments={
                    "filename": "revenue.html",
                    "html": "<html><body>Revenue</body></html>",
                },
            )
        )
    )
    publication = json.loads(published.root.content[0].text)
    assert publication["published"] is True
    assert publication["next_required_action"].startswith(
        "REQUIRED BEFORE YOUR FINAL ANSWER"
    )

    unscanned = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "no_suggestion",
                    "artifact_kind": "report",
                    "artifact_filename": "revenue.html",
                    "title": "Revenue",
                    "reason": "This is a one-off diagnostic.",
                },
            )
        )
    )
    assert unscanned.root.isError is True
    assert "every saved report catalog page" in unscanned.root.content[0].text

    await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="list_saved_report_catalog",
                arguments={},
            )
        )
    )
    recorded = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "no_suggestion",
                    "artifact_kind": "report",
                    "artifact_filename": "revenue.html",
                    "title": "Revenue",
                    "reason": "This is a one-off diagnostic.",
                },
            )
        )
    )

    assert recorded.root.isError is False
    assert json.loads(recorded.root.content[0].text) == {
        "recorded": True,
        "proposed": False,
        "action": "no_suggestion",
    }
    assert collector.report_proposal is None
    assert collector.report_action_outcome == {
        "action": "no_suggestion",
        "artifact_kind": "report",
        "artifact_filename": "revenue.html",
        "title": "Revenue",
        "reason": "This is a one-off diagnostic.",
        "existing_report_id": None,
        "catalog_revision": "revision-empty",
        "catalog_scan_complete": True,
        "proactive_creation_allowed": True,
        "loaded_report_ids": [],
        "attached_report_id": None,
    }


@pytest.mark.asyncio
async def test_report_creation_fails_closed_above_500_catalog_entries():
    collector = StandaloneArtifactCollector(
        artifacts=[
            {
                "kind": "table",
                "filename": "revenue.csv",
                "payload": {
                    "columns": [{"name": "revenue"}],
                    "rows": [{"revenue": 100}],
                    "completeness": "complete",
                    "truncated": False,
                },
            }
        ]
    )

    async def load_catalog(_cursor: str | None) -> dict[str, Any]:
        return {
            "items": [],
            "next_cursor": None,
            "catalog_revision": "revision-large",
            "total_reports": 501,
            "proactive_creation_allowed": False,
        }

    server = build_standalone_chat_mcp_server(
        collector,
        report_catalog_loader=load_catalog,
    )["instance"]
    scanned = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="list_saved_report_catalog",
                arguments={},
            )
        )
    )
    assert scanned.root.isError is False

    blocked = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "create",
                    "artifact_kind": "table",
                    "artifact_filename": "revenue.csv",
                    "title": "Revenue",
                    "reason": "No semantic match exists.",
                },
            )
        )
    )
    assert blocked.root.isError is True
    assert (
        "Proactive report creation is unavailable"
        in blocked.root.content[0].text
    )
    assert collector.report_proposal is None


@pytest.mark.asyncio
async def test_report_update_requires_loaded_context_unless_the_report_is_attached():
    artifact = {
        "kind": "chart",
        "filename": "revenue.png",
        "payload": {
            "source": {"completeness": "complete", "truncated": False},
        },
    }

    async def load_context(report_id: str) -> dict[str, Any]:
        return {"report_id": report_id, "title": "Revenue"}

    async def load_catalog(_cursor: str | None) -> dict[str, Any]:
        return {
            "items": [{"report_id": "report-a", "title": "Revenue"}],
            "next_cursor": None,
            "catalog_revision": "revision-a",
            "total_reports": 1,
            "proactive_creation_allowed": True,
        }

    collector = StandaloneArtifactCollector(artifacts=[artifact])
    server = build_standalone_chat_mcp_server(
        collector,
        report_context_loader=load_context,
        report_catalog_loader=load_catalog,
    )["instance"]
    blocked = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "update",
                    "artifact_kind": "chart",
                    "artifact_filename": "revenue.png",
                    "title": "Revenue",
                    "reason": "Only the date range changed.",
                    "existing_report_id": "report-a",
                },
            )
        )
    )
    assert blocked.root.isError is True
    await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="list_saved_report_catalog",
                arguments={},
            )
        )
    )
    await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="load_report_context",
                arguments={"report_id": "report-a"},
            )
        )
    )
    accepted = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "update",
                    "artifact_kind": "chart",
                    "artifact_filename": "revenue.png",
                    "title": "Revenue",
                    "reason": "Only the date range changed.",
                    "existing_report_id": "report-a",
                },
            )
        )
    )
    assert accepted.root.isError is False


@pytest.mark.asyncio
async def test_analysis_notebook_start_needs_no_plan_and_uses_only_the_seeded_path(
    tmp_path: Path,
) -> None:
    seeded = tmp_path / "analysis.py"
    seeded.write_text("import marimo\n", encoding="utf-8")
    calls: list[dict[str, Any]] = []

    def start_notebook(
        _context: Any, arguments: dict[str, Any]
    ) -> list[TextContent]:
        calls.append(arguments)
        return [
            TextContent(
                type="text", text=json.dumps({"session_id": "session-a"})
            )
        ]

    runtime_session = SimpleNamespace()

    lifecycle = StandaloneNotebookLifecycle()
    config = build_standalone_chat_mcp_server(
        StandaloneArtifactCollector(),
        notebook_mcp_app=object(),
        analysis_notebook_path=seeded,
        notebook_lifecycle=lifecycle,
        notebook_starter=start_notebook,
        notebook_session_resolver=lambda _session_id: runtime_session,
    )
    server = config["instance"]
    response = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="start_analysis_notebook",
                arguments={},
            )
        )
    )

    assert response.root.isError is False
    assert calls == [{"file_path": str(seeded), "auto_run": True}]
    assert lifecycle.session_id == "session-a"
    assert runtime_session._signalpilot_chat_runtime is True


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
    assert execution_env["CLAUDE_CODE_OAUTH_TOKEN"] == ""
    assert execution_env["OAUTH_TOKEN"] == ""
    assert execution_env["ANTHROPIC_AUTH_TOKEN"] == ""
    assert process_env == {
        "CLAUDE_CODE_OAUTH_TOKEN": "old-oauth",
        "OAUTH_TOKEN": "old-alias",
    }

    process_env = {
        "ANTHROPIC_API_KEY": "depleted-org-key",
        "ANTHROPIC_AUTH_TOKEN": "old-auth-token",
    }
    execution_env = dict(process_env)
    _apply_auth_config(
        execution_env,
        {"type": "oauth", "token": "working-oauth"},
    )
    assert execution_env == {
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_AUTH_TOKEN": "",
        "OAUTH_TOKEN": "",
        "CLAUDE_CODE_OAUTH_TOKEN": "working-oauth",
    }
    # This mirrors the Agent SDK's subprocess environment merge. Deleting the
    # competing keys would preserve the inherited values; empty overrides do not.
    merged = {**process_env, **execution_env}
    assert merged["ANTHROPIC_API_KEY"] == ""
    assert merged["ANTHROPIC_AUTH_TOKEN"] == ""


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


def test_agent_contract_includes_default_signalpilot_mcp_tools():
    # The prompt file wraps lines; compare against whitespace-collapsed text.
    _prompt_flat = " ".join(STANDALONE_SYSTEM_PROMPT.split())
    assert "Answer data questions with evidence" in _prompt_flat
    assert "first tool call for any analytics request is the `Skill` tool" in _prompt_flat
    assert "`signalpilot-dbt:dbt-workflow`" in _prompt_flat
    assert "SP_CHAT_SCRATCH_DIRECTORY" in _prompt_flat
    assert "analytics-steps.md" in _prompt_flat
    assert "prebuild-state.md" in _prompt_flat
    assert "list_saved_report_catalog" in _prompt_flat
    assert "load_report_context" in _prompt_flat
    assert "propose_report_action" in _prompt_flat
    assert "publish_table" in _prompt_flat
    assert "publish_chart" in _prompt_flat
    assert "publish_report" in _prompt_flat
    assert "GitHub Flavored Markdown" in _prompt_flat
    assert "HTML tags such as `<details>` do not render" in _prompt_flat
    assert {
        "mcp__signalpilot__get_knowledge",
        "mcp__signalpilot__propose_knowledge",
        "mcp__signalpilot__notion_search",
        "mcp__signalpilot__notion_create_page",
        "mcp__signalpilot__sandbox_exec",
        "mcp__signalpilot__dbt_execute",
    } <= set(STANDALONE_ALLOWED_TOOLS)
    assert all(
        "github" not in tool.lower() for tool in STANDALONE_ALLOWED_TOOLS
    )
    assert all(
        forbidden not in STANDALONE_ALLOWED_TOOLS
        for forbidden in ("Bash", "Write", "Edit", "WebFetch", "WebSearch")
    )
    assert set(STANDALONE_DISALLOWED_MCP_TOOLS) == {
        "mcp__signalpilot__schema_diff_branches",
        "mcp__signalpilot__xata_branch_diff",
        "mcp__signalpilot__xata_list_branches",
        "mcp__signalpilot__create_xata_branch",
        "mcp__signalpilot__delete_xata_branch",
    }
    assert set(IMPROVEMENT_EXTRA_TOOLS) <= set(STANDALONE_ALLOWED_TOOLS)


@pytest.mark.asyncio
async def test_scratch_python_tool_is_not_exposed():
    server = build_standalone_chat_mcp_server(
        StandaloneArtifactCollector(), notebook_mcp_app=None
    )["instance"]
    response = await server.request_handlers[ListToolsRequest](
        ListToolsRequest()
    )

    assert "run_scratch_python" not in {
        tool.name for tool in response.root.tools
    }


def test_notebook_workflow_is_always_enabled():
    *_, execution_prompt = _execution_prompt_values(
        {"prompt": "Summarize revenue"},
        project_id="project-a",
        branch="main",
        commit_sha="a" * 40,
        connection_name="warehouse",
    )
    assert "`signalpilot-dbt:dbt-workflow`" in execution_prompt
    assert "mcp__standalone-chat__start_analysis_notebook" in STANDALONE_ALLOWED_TOOLS
    assert any("signalpilot-notebook" in tool for tool in STANDALONE_ALLOWED_TOOLS)


def test_runtime_publication_sdk_is_exposed_from_top_level_package():
    # tests/conftest.py intentionally replaces the top-level package with a
    # lightweight shim, so verify the real package exports without importing it.
    from pathlib import Path

    package_source = (
        Path(__file__).parents[3] / "signalpilot" / "__init__.py"
    ).read_text(encoding="utf-8")
    assert '"publish_result"' in package_source
    assert '"publish_artifact"' in package_source
    assert '"open_dataset"' in package_source
