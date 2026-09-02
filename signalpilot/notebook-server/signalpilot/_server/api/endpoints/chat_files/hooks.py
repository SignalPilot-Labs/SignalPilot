"""Glue between the agent event relay and the file capture.

`capture_after_tool_result` runs after each tool result. `capture_at_run_end`
runs once before the final payload and on every rejection or error path.
Neither ever raises into the stream. A capture failure is a log line.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from signalpilot import _loggers

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from signalpilot._server.api.endpoints.chat_files.capture import (
        ScratchFileCapture,
    )
    from signalpilot._server.api.endpoints.chat_files.uploader import (
        RuntimeFileUploader,
    )

LOGGER = _loggers.sp_logger()

# Built-in tools that never write a file.
READ_ONLY_TOOLS = frozenset(
    {
        "Read",
        "Glob",
        "Grep",
        "Skill",
        "TodoWrite",
        "ToolSearch",
        "WebFetch",
        "WebSearch",
        "LS",
        "TodoRead",
        "AskUserQuestion",
    }
)

# MCP tools that only read. Matched on the suffix after the server prefix.
READ_ONLY_MCP_SUFFIXES = (
    "query_database",
    "list_tables",
    "explore_column",
    "explore_columns",
    "explore_table",
    "explore_value",
    "get_schema",
    "search_knowledge",
    "read_knowledge",
    "get_knowledge",
    "explain_query",
    "validate_sql",
    "inspect_dbt",
    "plan_query",
    "describe_table",
    "schema_overview",
    "schema_statistics",
    "schema_ddl",
    "schema_link",
    "schema_diff",
    "get_relationships",
    "find_join_path",
    "find_column_producers",
    "map_columns",
    "check_model_schema",
    "check_budget",
    "estimate_query_cost",
    "connection_health",
    "connector_capabilities",
    "list_database_connections",
    "list_workspace_projects",
    "list_semantic_metrics",
    "list_notion_integrations",
    "notion_search",
    "notion_fetch_page",
    "get_date_boundaries",
    "get_dbt_profile",
    "query_history",
    "read_notebook",
    "get_lightweight_cell_map",
    "get_notebook_errors",
    "sandbox_read_file",
    "analyze_grain",
    "compare_join_types",
    "generate_sql_skeleton",
    "debug_cte_query",
    "dbt_error_parser",
    "audit_model_sources",
    "verify_model_values",
    "verify_metric_conformance",
    "validate_model_output",
)


def tool_is_read_only(tool_name: str) -> bool:
    """Return True when a tool cannot change the scratch directory.

    Unknown tools trigger a sweep. A subagent (`Agent`) triggers a sweep
    because it can write files.
    """
    name = str(tool_name or "").strip()
    if not name:
        return False
    if name in READ_ONLY_TOOLS:
        return True
    if name.startswith("mcp__"):
        suffix = name.rsplit("__", 1)[-1]
        return suffix in READ_ONLY_MCP_SUFFIXES
    return False


def _progress_line(content: str) -> bytes:
    payload = {"type": "progress", "content": content, "is_error": False}
    return (json.dumps(payload) + "\n").encode("utf-8")


async def _sweep_and_upload(
    *,
    capture: ScratchFileCapture,
    uploader: RuntimeFileUploader,
    reason: str,
    tool_call_id: str | None,
) -> AsyncIterator[bytes]:
    """Sweep, upload, yield one progress line per stored file."""
    captured = await capture.sweep(reason=reason, tool_call_id=tool_call_id)
    if not captured:
        return
    outcomes = await uploader.upload_many(
        captured, reason=reason, tool_call_id=tool_call_id
    )
    for outcome in outcomes:
        if not outcome.ok:
            # Read the file again on the next sweep so the run-end pass
            # retries it.
            capture.forget(outcome.path)
            continue
        if outcome.unchanged:
            continue
        verb = "Removed" if outcome.deleted else "Saved"
        yield _progress_line(f"{verb} {outcome.path}")


async def capture_after_tool_result(
    event: Any,
    tool_name: str,
    *,
    capture: ScratchFileCapture,
    uploader: RuntimeFileUploader,
) -> AsyncIterator[bytes]:
    """Sweep after one tool result unless the tool is read-only."""
    if tool_is_read_only(tool_name):
        return
    tool_call_id = str(getattr(event, "tool_call_id", "") or "") or None
    try:
        async for line in _sweep_and_upload(
            capture=capture,
            uploader=uploader,
            reason="tool",
            tool_call_id=tool_call_id,
        ):
            yield line
    except Exception:
        LOGGER.warning(
            "Chat file capture failed after tool run_id=%s tool=%s",
            capture.run_id,
            tool_name,
            exc_info=True,
        )


def build_after_tool_result_hook(
    *,
    capture: ScratchFileCapture,
    uploader: RuntimeFileUploader,
) -> Callable[[Any, str], AsyncIterator[bytes]]:
    """Bind the capture and uploader for the stream relay."""

    def hook(event: Any, tool_name: str) -> AsyncIterator[bytes]:
        return capture_after_tool_result(
            event, tool_name, capture=capture, uploader=uploader
        )

    return hook


async def capture_at_run_end(
    *,
    capture: ScratchFileCapture,
    uploader: RuntimeFileUploader,
) -> list[bytes]:
    """Final sweep. Return the progress lines; never raise."""
    lines: list[bytes] = []
    try:
        async for line in _sweep_and_upload(
            capture=capture,
            uploader=uploader,
            reason="run_end",
            tool_call_id=None,
        ):
            lines.append(line)
    except Exception:
        LOGGER.warning(
            "Chat file capture failed at run end run_id=%s",
            capture.run_id,
            exc_info=True,
        )
    return lines
