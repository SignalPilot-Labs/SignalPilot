"""Prompts and tool allowlists for standalone chat execution."""

from __future__ import annotations

import json
import re
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
    "mcp__signalpilot__open_pull_request",
    "mcp__signalpilot__update_pull_request",
    "mcp__signalpilot__comment_on_pull_request",
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
    "mcp__standalone-chat__dashboard_list_published",
    "mcp__standalone-chat__dashboard_load_published",
    "mcp__standalone-chat__dashboard_sample_data",
    "mcp__standalone-chat__dashboard_screenshot",
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
# Conversation-derived keys of the gateway's warm context. These restate what
# the resumed SDK session already holds, so they are withheld on a resume.
_SESSION_CONTEXT_KEYS = frozenset(
    {
        "conversation_summary",
        "query_decisions",
        "structured_results",
        "report_reference",
    }
)

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "ai" / "prompts"


@lru_cache(maxsize=8)
def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


# Conditional sections live inline in the prompt files, marked
# `<!-- @if <flag> -->` ... `<!-- @endif -->`. A section whose flag is not set
# is dropped; the markers themselves never reach the model. This replaces the
# old one-file-per-condition split, which scattered the analysis workflow
# across files that were only sometimes present.
_SECTION_RE = re.compile(
    r"[ \t]*<!--\s*@if\s+(\w+)\s*-->\n(.*?)\n[ \t]*<!--\s*@endif\s*-->\n?",
    re.DOTALL,
)


def _apply_sections(text: str, flags: set[str]) -> str:
    def keep(match: re.Match[str]) -> str:
        return match.group(2) + "\n" if match.group(1) in flags else ""

    return _SECTION_RE.sub(keep, text).strip()


# Back-compat accessor (tests and older callers) â€” the content lives in the
# .md file; this just materializes it at import time.
STANDALONE_SYSTEM_PROMPT = _load_prompt("standalone_chat_system.md")


def git_publish_section(base_branch: str) -> str:
    """Back-compat shim: the publish section now lives in the one prompt file."""
    marker = "## Publish your work"
    text = _load_prompt("standalone_chat_system.md")
    start = text.index(marker)
    end = text.find("\n<!-- @endif -->", start)
    section = text[start:end if end != -1 else len(text)]
    return section.replace("{base_branch}", base_branch or "the project branch")


def _dbt_project_dir_line() -> str:
    """Name the org's configured dbt project directory for the agent.

    A repo can hold more than one dbt project; without this the agent reads
    whichever it finds first and can end up describing models that were never
    built. Best-effort: an unreachable gateway or an unset setting omits the
    line rather than failing the run.
    """
    try:
        from signalpilot._dbt.materialize import resolve_dbt_project_dir

        configured = resolve_dbt_project_dir()
    except Exception:
        return ""
    if configured is None:
        return ""
    where = configured or "the repository root"
    return (
        f"dbt project directory: {where}\n"
        "Read dbt files only from there; other folders in this repo may hold "
        "different dbt projects that are not the selected one.\n"
    )


def _execution_prompt_values(
    body: dict[str, Any],
    *,
    project_id: str,
    branch: str,
    commit_sha: str,
    connection_name: str,
    connector_slugs: Sequence[str] = (),
) -> tuple[str, list[dict[str, str]], bool, bool, str, str]:
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
    # The governed context splits in two. The project half describes the
    # project and never appears in the transcript, so it is sent every turn.
    # The session half is conversation-derived: on a resumed turn the SDK has
    # already replayed the transcript that produced it, so re-sending it is
    # duplication. `_extend_system_prompt` already gates <previous_conversation>
    # and the dbt file context on `not is_resume`; this is the same seam. The
    # caller appends the session block only when the session was NOT resumed,
    # which keeps it as the session-loss fallback it really is.
    warm_raw = body.get("warm_context") or {}
    if not isinstance(warm_raw, dict):
        warm_raw = {}
    project_half = {
        key: value
        for key, value in warm_raw.items()
        if key not in _SESSION_CONTEXT_KEYS
    }
    session_half = {
        key: value
        for key, value in warm_raw.items()
        if key in _SESSION_CONTEXT_KEYS and value
    }
    warm_context = json.dumps(project_half, default=str)[:120_000]
    session_context_block = (
        "<governed_session_context>\n"
        + json.dumps(session_half, default=str)[:120_000]
        + "\n</governed_session_context>"
        if session_half
        else ""
    )
    features = (
        body.get("features") if isinstance(body.get("features"), dict) else {}
    )
    is_improvement_run = str(body.get("run_origin") or "user") == "improvement"
    sandbox_runtime_enabled = (
        bool(features.get("sandbox_runtime")) and not is_improvement_run
    )
    # One prompt file, sliced by flag. The conditional sections are marked
    # inline with `<!-- @if <flag> -->`; a section whose flag is unset is
    # dropped before the prompt is sent.
    section_flags: set[str] = set()
    if sandbox_runtime_enabled:
        section_flags.add("sandbox_runtime")
    if is_improvement_run:
        section_flags.add("improvement")
    if connector_slugs:
        section_flags.add("connectors")
    prompt_parts = [_apply_sections(STANDALONE_SYSTEM_PROMPT, section_flags)]
    connectors_line = ", ".join(connector_slugs) if connector_slugs else "none"
    system_prompt = (
        "\n\n".join(prompt_parts).replace(
            "{base_branch}", branch or "the project branch"
        )
        + "\n\n"
        + f"Selected project: {project_id}\nFrozen branch: {branch}\n"
        + _dbt_project_dir_line()
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
        session_context_block,
        system_prompt,
    )
