"""Prompts and tool allowlists for standalone chat execution."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from starlette.exceptions import HTTPException

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
    "mcp__signalpilot__plan_query",
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
    "mcp__standalone-chat__publish_chart",
    "mcp__standalone-chat__publish_report",
    "mcp__standalone-chat__publish_table",
    "mcp__standalone-chat__list_saved_report_catalog",
    "mcp__standalone-chat__load_report_context",
    "mcp__standalone-chat__propose_report_action",
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


_NOTEBOOK_ONLY_RULE_PREFIXES = (
    "- Start the analysis notebook whenever",
    "- `notebook_sdk` or `dataset_ref`",
    "- The analysis notebook is a marimo reactive notebook",
    "- Define shared imports and reusable DataFrames once",
    "- If edit_notebook returns MultipleDefinitionError",
    "- Never edit, remove, or redefine the seeded",
    "- For notebook_sdk, first define `plan_id`",
    '- `source["rows"]` is JSON transport',
    "- Never copy MCP previews into notebook DataFrames",
    "- Keep complete bounded DataFrames inside the kernel",
    "- Publish derived rows from the kernel",
    "- Publish a runtime file with exactly",
    "- Verify every chart before publishing it",
    "- PublishedResult exposes only",
    "- Do not catch or suppress publication exceptions",
    "- Prefer governed SDK structured-result IDs",
)


def _system_prompt_for_features(*, notebook_analysis_enabled: bool) -> str:
    if notebook_analysis_enabled:
        return STANDALONE_SYSTEM_PROMPT
    lines: list[str] = []
    in_notebook_section = False
    for line in STANDALONE_SYSTEM_PROMPT.splitlines():
        if line.startswith("## The analysis notebook"):
            in_notebook_section = True
            continue
        if in_notebook_section and line.startswith("## "):
            in_notebook_section = False
        if not in_notebook_section and not line.startswith(
            _NOTEBOOK_ONLY_RULE_PREFIXES
        ):
            lines.append(line)
    disabled_rule = (
        "- Notebook analysis is disabled for this run. Do not call notebook "
        "tools; use an exact MCP plan or rewrite aggregate_required work as "
        "bounded warehouse SQL."
    )
    anchor = "- Use query_database with the returned plan_id only when the plan route is mcp."
    insert_at = lines.index(anchor) + 1 if anchor in lines else len(lines)
    lines.insert(insert_at, disabled_rule)
    return "\n".join(lines)


def _allowed_tools_for_features(
    *,
    notebook_analysis_enabled: bool,
) -> list[str]:
    if notebook_analysis_enabled:
        return list(STANDALONE_ALLOWED_TOOLS)
    return [
        tool
        for tool in STANDALONE_ALLOWED_TOOLS
        if "signalpilot-notebook" not in tool
        and not tool.endswith("start_analysis_notebook")
    ]


def _execution_prompt_values(
    body: dict[str, Any],
    *,
    project_id: str,
    branch: str,
    commit_sha: str,
    connection_name: str,
) -> tuple[str, list[dict[str, str]], bool, bool, bool, str]:
    """Validate request text and build the bounded agent prompt context."""
    prompt = str(body.get("prompt") or "").strip()
    if not prompt or len(prompt) > 50_000:
        raise HTTPException(status_code=400, detail="Prompt is empty or too large")
    history = [
        {
            "role": str(item.get("role") or "user"),
            "content": str(item.get("content") or ""),
        }
        for item in list(body.get("messages") or [])[-40:]
        if isinstance(item, dict)
    ]
    warm_context = json.dumps(body.get("warm_context") or {}, default=str)[:120_000]
    features = body.get("features") if isinstance(body.get("features"), dict) else {}
    notebook_analysis_enabled = bool(features.get("notebook_analysis"))
    is_improvement_run = str(body.get("run_origin") or "user") == "improvement"
    sandbox_runtime_enabled = bool(features.get("sandbox_runtime")) and not is_improvement_run
    prompt_parts = [
        _system_prompt_for_features(
            notebook_analysis_enabled=notebook_analysis_enabled
        )
    ]
    if sandbox_runtime_enabled:
        prompt_parts.append(_load_prompt("sandbox_dbt_suffix.md"))
    if is_improvement_run:
        prompt_parts.append(_load_prompt("improvement_suffix.md"))
    system_prompt = (
        "\n\n".join(prompt_parts)
        + "\n\n"
        + f"Selected project: {project_id}\nFrozen branch: {branch}\n"
        + f"Frozen commit: {commit_sha}\nSelected connection: {connection_name}\n\n"
        + f"<governed_project_context>\n{warm_context}\n</governed_project_context>"
    )
    return (
        prompt,
        history,
        notebook_analysis_enabled,
        is_improvement_run,
        sandbox_runtime_enabled,
        system_prompt,
    )
