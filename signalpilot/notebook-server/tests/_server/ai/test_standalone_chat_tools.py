"""Security contracts for standalone chat execution and publication tools."""

from __future__ import annotations

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
from signalpilot._server.ai.standalone_chat_tools import (
    StandaloneArtifactCollector,
    StandaloneNotebookLifecycle,
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
async def test_publish_tools_are_gone_and_unknown_tools_are_errors():
    config = build_standalone_chat_mcp_server(StandaloneArtifactCollector())
    server = config["instance"]
    listed = await server.request_handlers[ListToolsRequest](
        ListToolsRequest()
    )
    names = {tool.name for tool in listed.root.tools}
    assert names == {"inspect_dbt", "create_dashboard_preview"}
    assert not any(name.startswith("publish_") for name in names)
    assert not any("report" in name for name in names)

    for retired in (
        "publish_table",
        "publish_chart",
        "publish_report",
        "list_saved_report_catalog",
        "load_report_context",
        "propose_report_action",
    ):
        response = await server.request_handlers[CallToolRequest](
            CallToolRequest(
                params=CallToolRequestParams(
                    name=retired,
                    arguments={"filename": "revenue.csv"},
                )
            )
        )
        assert response.root.isError is True
        assert "Unknown tool" in response.root.content[0].text


@pytest.mark.asyncio
async def test_dashboard_preview_tool_creates_one_review_only_preview():
    calls: list[tuple[str, str]] = []

    async def create_preview(
        request: str, timezone: str, authoring_session_id: str | None
    ) -> dict[str, Any]:
        assert authoring_session_id is None
        calls.append((request, timezone))
        return {
            "id": "authoring-session-1",
            "summary": "Created a governed revenue dashboard.",
            "definition": {
                "name": "Executive Revenue",
                "charts": [
                    {"title": "Total Revenue"},
                    {"title": "Revenue Trend"},
                ],
            },
        }

    collector = StandaloneArtifactCollector()
    server = build_standalone_chat_mcp_server(
        collector,
        dashboard_preview_creator=create_preview,
    )["instance"]
    listed = await server.request_handlers[ListToolsRequest](ListToolsRequest())
    assert "create_dashboard_preview" in {
        tool.name for tool in listed.root.tools
    }

    request = CallToolRequest(
        params=CallToolRequestParams(
            name="create_dashboard_preview",
            arguments={
                "request": "Create an executive revenue dashboard",
                "timezone": "America/New_York",
            },
        )
    )
    created = await server.request_handlers[CallToolRequest](request)
    repeated = await server.request_handlers[CallToolRequest](request)

    assert created.root.isError is False
    assert repeated.root.isError is False
    assert calls == [
        ("Create an executive revenue dashboard", "America/New_York")
    ]
    payload = json.loads(created.root.content[0].text)
    assert payload == {
        "status": "preview_ready",
        "authoring_session_id": "authoring-session-1",
        "preview_url": "/dashboards/new?authoring=authoring-session-1",
        "summary": "Created a governed revenue dashboard.",
        "dashboard_name": "Executive Revenue",
        "chart_count": 2,
        "chart_titles": ["Total Revenue", "Revenue Trend"],
        "requires_review": True,
        "apply_required": True,
    }
    assert collector.dashboard_preview == payload

    conflicting = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="create_dashboard_preview",
                arguments={"request": "Create a different dashboard"},
            )
        )
    )
    assert conflicting.root.isError is True
    assert "Only one dashboard preview" in conflicting.root.content[0].text


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


def test_agent_contract_includes_default_signalpilot_mcp_tools():
    # The prompt file wraps lines; compare against whitespace-collapsed text.
    _prompt_flat = " ".join(STANDALONE_SYSTEM_PROMPT.split())
    assert "Answer data questions with evidence" in _prompt_flat
    assert "`TodoWrite`: a first plan" in _prompt_flat
    assert "Make no other tool call before the skill loads" in _prompt_flat
    assert "`signalpilot-dbt:dbt-workflow`" in _prompt_flat
    assert "SP_CHAT_SCRATCH_DIRECTORY" in _prompt_flat
    assert "analytics-steps.md" in _prompt_flat
    assert "prebuild-state.md" in _prompt_flat
    # The filesystem is the artifact API. No publish or report tools.
    assert "## Files and charts" in STANDALONE_SYSTEM_PROMPT
    assert "SP_CHAT_ARTIFACTS_DIRECTORY" in _prompt_flat
    assert "sp.artifact_path(" in _prompt_flat
    assert "![Revenue by month, 2025](artifacts/revenue_by_month.png)" in (
        _prompt_flat
    )
    assert "Prove findings with a chart saved to `artifacts/`" in _prompt_flat
    for retired in (
        "list_saved_report_catalog",
        "load_report_context",
        "propose_report_action",
        "publish_table",
        "publish_chart",
        "publish_report",
        "publish_artifact",
        "publish_result",
        "report decision",
        "result_id",
    ):
        assert retired not in _prompt_flat, retired
    assert "GitHub Flavored Markdown" in _prompt_flat
    assert "raw HTML" in _prompt_flat
    assert "blank line after an opening HTML tag" in _prompt_flat
    assert "Link each dbt model to its lineage page" in _prompt_flat
    assert "/lineage/rpt_customer_retention?project=PROJECT_ID" in _prompt_flat
    assert "Keep the link root-relative" in _prompt_flat
    assert "call `create_dashboard_preview` exactly once" in _prompt_flat
    assert "user must review and Apply" in _prompt_flat
    assert {
        "mcp__signalpilot__get_knowledge",
        "mcp__signalpilot__propose_knowledge",
        "mcp__signalpilot__notion_search",
        "mcp__signalpilot__notion_create_page",
        "mcp__signalpilot__sandbox_exec",
        "mcp__signalpilot__dbt_execute",
        "mcp__standalone-chat__create_dashboard_preview",
    } <= set(STANDALONE_ALLOWED_TOOLS)
    assert all(
        "github" not in tool.lower() for tool in STANDALONE_ALLOWED_TOOLS
    )
    assert not any(
        "publish_" in tool or "_report_" in tool or "report_action" in tool
        for tool in STANDALONE_ALLOWED_TOOLS
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
    assert "Lineage link: /lineage/<model_name>?project=project-a" in execution_prompt
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
    assert '"artifact_path"' in package_source
    assert '"open_dataset"' in package_source
    assert "publish_artifact" not in package_source
