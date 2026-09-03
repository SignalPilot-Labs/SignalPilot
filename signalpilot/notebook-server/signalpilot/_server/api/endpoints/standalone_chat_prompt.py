"""Prompts and tool allowlists for standalone chat execution."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starlette.exceptions import HTTPException

if TYPE_CHECKING:
    from collections.abc import Sequence

STANDALONE_ALLOWED_TOOLS = [
    "mcp__signalpilot__analyze_grain",
    "mcp__signalpilot__analyze_project_db",
    "mcp__signalpilot__archive_knowledge",
    "mcp__signalpilot__audit_model_sources",
    "mcp__signalpilot__check_budget",
    "mcp__signalpilot__check_model_schema",
    "mcp__signalpilot__compare_join_types",
    "mcp__signalpilot__connection_health",
    "mcp__signalpilot__connector_capabilities",
    "mcp__signalpilot__dbt_error_parser",
    "mcp__signalpilot__dbt_execute",
    "mcp__signalpilot__debug_cte_query",
    "mcp__signalpilot__describe_table",
    "mcp__signalpilot__estimate_query_cost",
    "mcp__signalpilot__explain_query",
    "mcp__signalpilot__explore_column",
    "mcp__signalpilot__explore_columns",
    "mcp__signalpilot__explore_table",
    "mcp__signalpilot__find_join_path",
    "mcp__signalpilot__find_column_producers",
    "mcp__signalpilot__generate_sql_skeleton",
    "mcp__signalpilot__get_date_boundaries",
    "mcp__signalpilot__get_dbt_profile",
    "mcp__signalpilot__get_knowledge",
    "mcp__signalpilot__get_relationships",
    "mcp__signalpilot__list_database_connections",
    "mcp__signalpilot__list_notion_integrations",
    "mcp__signalpilot__list_semantic_metrics",
    "mcp__signalpilot__list_tables",
    "mcp__signalpilot__list_workspace_projects",
    "mcp__signalpilot__map_columns",
    "mcp__signalpilot__notion_create_page",
    "mcp__signalpilot__notion_fetch_page",
    "mcp__signalpilot__notion_search",
    "mcp__signalpilot__propose_knowledge",
    "mcp__signalpilot__query_database",
    "mcp__signalpilot__query_history",
    "mcp__signalpilot__read_knowledge",
    "mcp__signalpilot__read_notebook",
    "mcp__signalpilot__refresh_mart",
    "mcp__signalpilot__run_notebook",
    "mcp__signalpilot__sandbox_exec",
    "mcp__signalpilot__sandbox_read_file",
    "mcp__signalpilot__sandbox_write_file",
    "mcp__signalpilot__schema_diff",
    "mcp__signalpilot__schema_ddl",
    "mcp__signalpilot__schema_link",
    "mcp__signalpilot__schema_overview",
    "mcp__signalpilot__schema_statistics",
    "mcp__signalpilot__search_knowledge",
    "mcp__signalpilot__validate_sql",
    "mcp__signalpilot__validate_model_output",
    "mcp__signalpilot__verify_model_values",
    "mcp__signalpilot__verify_metric_conformance",
    "mcp__standalone-chat__begin_dashboard_authoring",
    "mcp__standalone-chat__set_dashboard_plan",
    "mcp__standalone-chat__upsert_dashboard_chart",
    "mcp__standalone-chat__apply_dashboard_operations",
    "mcp__standalone-chat__create_dashboard_preview",
    "mcp__standalone-chat__inspect_dbt",
    "mcp__standalone-chat__start_analysis_notebook",
    "mcp__signalpilot-notebook__edit_notebook",
    "mcp__signalpilot-notebook__run_cells",
    "mcp__signalpilot-notebook__get_lightweight_cell_map",
    "mcp__signalpilot-notebook__get_notebook_errors",
]

# Compatibility aliases retained for callers that group these tools. All are
# now part of the default standalone tool surface.
SANDBOX_TOOLS = [
    "mcp__signalpilot__sandbox_exec",
    "mcp__signalpilot__sandbox_write_file",
    "mcp__signalpilot__sandbox_read_file",
]
IMPROVEMENT_EXTRA_TOOLS = SANDBOX_TOOLS  # historical alias
REFRESH_MART_TOOL = "mcp__signalpilot__refresh_mart"
DBT_EXECUTE_TOOL = "mcp__signalpilot__dbt_execute"

# Xata branch control is not part of chat analysis. The selected project and
# database connection remain fixed for the lifetime of the run.
STANDALONE_DISALLOWED_MCP_TOOLS = [
    "mcp__signalpilot__schema_diff_branches",
    "mcp__signalpilot__xata_branch_diff",
    "mcp__signalpilot__xata_list_branches",
    "mcp__signalpilot__create_xata_branch",
    "mcp__signalpilot__delete_xata_branch",
]

# System prompts live in standalone .md files â€” easy to read and modify
# without touching code. See _server/ai/prompts/.
_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "ai" / "prompts"


@lru_cache(maxsize=8)
def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


# Back-compat accessor (tests and older callers) â€” the content lives in the
# .md file; this just materializes it at import time.
STANDALONE_SYSTEM_PROMPT = _load_prompt("standalone_chat_system.md")


def _execution_prompt_values(
    body: dict[str, Any],
    *,
    project_id: str,
    branch: str,
    commit_sha: str,
    connection_name: str,
    connector_slugs: Sequence[str] = (),
) -> tuple[str, list[dict[str, str]], bool, bool, str]:
    """Validate request text and build the bounded agent prompt context.

    ``connector_slugs`` names the external MCP connectors injected into this
    run. When any exist, the R11 connector-safety section is appended.
    """
    prompt = str(body.get("prompt") or "").strip()
    if not prompt or len(prompt) > 50_000:
        raise HTTPException(
            status_code=400, detail="Prompt is empty or too large"
        )
    history = [
        {
            "role": str(item.get("role") or "user"),
            "content": str(item.get("content") or ""),
        }
        for item in list(body.get("messages") or [])[-40:]
        if isinstance(item, dict)
    ]
    warm_context = json.dumps(body.get("warm_context") or {}, default=str)[
        :120_000
    ]
    features = (
        body.get("features") if isinstance(body.get("features"), dict) else {}
    )
    is_improvement_run = str(body.get("run_origin") or "user") == "improvement"
    sandbox_runtime_enabled = (
        bool(features.get("sandbox_runtime")) and not is_improvement_run
    )
    prompt_parts = [STANDALONE_SYSTEM_PROMPT]
    if sandbox_runtime_enabled:
        prompt_parts.append(_load_prompt("sandbox_dbt_suffix.md"))
    if is_improvement_run:
        prompt_parts.append(_load_prompt("improvement_suffix.md"))
    if connector_slugs:
        prompt_parts.append(_load_prompt("connectors_suffix.md"))
    connectors_line = ", ".join(connector_slugs) if connector_slugs else "none"
    system_prompt = (
        "\n\n".join(prompt_parts)
        + "\n\n"
        + f"Selected project: {project_id}\nFrozen branch: {branch}\n"
        + f"Frozen commit: {commit_sha}\nSelected connection: {connection_name}\n"
        + f"Lineage link: /lineage/<model_name>?project={project_id}\n"
        + f"Connectors: {connectors_line}\n\n"
        + f"<governed_project_context>\n{warm_context}\n</governed_project_context>"
    )
    return (
        prompt,
        history,
        is_improvement_run,
        sandbox_runtime_enabled,
        system_prompt,
    )
