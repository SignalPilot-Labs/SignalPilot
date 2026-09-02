"""Project raw tool results into the ``tool_completed`` wire contract.

``project_tool_result`` never raises: any parser failure degrades to
``{"kind": "text"}`` with the raw text in ``result_text``. ``finalize_payload``
guarantees the serialized event stays under ``PAYLOAD_MAX``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from gateway.standalone_chat.tool_projection import builtins, ops, query, schema
from gateway.standalone_chat.tool_projection.base import ProjectedResult, text_result
from gateway.standalone_chat.tool_projection.limits import (
    PAYLOAD_MAX,
    RESULT_TEXT_SHRUNK,
    SCHEMA_COLS_SHRUNK,
    TABLE_LIST_SHRUNK,
    TABLE_ROWS_SHRUNK,
)
from gateway.standalone_chat.tool_projection.text import (
    error_projection,
    first_line,
    normalize_content,
)

__all__ = ["ProjectedResult", "finalize_payload", "project_tool_result"]

logger = logging.getLogger(__name__)

_SCHEMA_TEXT_TOOLS = frozenset(
    {"schema_overview", "get_date_boundaries", "find_join_path", "get_relationships", "schema_link"}
)
_ARTIFACT_TOOLS = frozenset({"create_dashboard_preview", "start_analysis_notebook"})
_LIST_TABLE_TOOLS = frozenset({"list_tables", "list_all_tables"})
_SCHEMA_TOOLS = frozenset({"describe_table", "get_table_schema"})


def _base_name(tool_name: str) -> str:
    return (tool_name or "").rsplit("__", 1)[-1]


def _humanize(base: str) -> str:
    return (base or "tool").replace("_", " ").strip().capitalize() or "Tool"


def _dispatch(tool_name: str, base: str, text: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    too_large = builtins.project_too_large(text, tool=base)
    if too_large is not None:
        return too_large
    if base in builtins.BUILTIN_TOOLS:
        return builtins.project_builtin(base, text, tool_input)
    if base == "query_database":
        return query.project_query_database(text, tool_input)
    if base == "validate_sql":
        return query.project_validate_sql(text, tool_input)
    if base == "explain_query":
        return query.project_explain_query(text, tool_input)
    if base == "estimate_query_cost":
        return query.project_estimate_query_cost(text, tool_input)
    if base == "plan_query":
        return query.project_plan_query(text, tool_input)
    if base in _LIST_TABLE_TOOLS:
        return schema.project_list_tables(text, tool_input)
    if base in _SCHEMA_TOOLS:
        return schema.project_describe_table(text, tool_input)
    if base == "explore_table":
        return schema.project_explore_table(text, tool_input)
    if base == "explore_columns":
        return schema.project_explore_columns(text, tool_input)
    if base == "explore_column":
        return schema.project_explore_column(text, tool_input)
    if base in _SCHEMA_TEXT_TOOLS:
        return schema.project_schema_text(text, tool_input)
    if base in ("dbt_execute", "refresh_mart"):
        return ops.project_dbt(text, tool_input)
    if base == "sandbox_exec":
        return ops.project_sandbox_exec(text, tool_input)
    if base == "Bash":
        return ops.project_bash(text, tool_input, is_error=False)
    if base == "get_knowledge":
        return ops.project_knowledge(text, tool_input, mode="get")
    if base == "search_knowledge":
        return ops.project_knowledge(text, tool_input, mode="search")
    if base == "read_knowledge":
        return ops.project_knowledge(text, tool_input, mode="read")
    if base in _ARTIFACT_TOOLS:
        return ops.project_artifact(text, tool_input, tool=base)
    return ops.project_json_or_text(text, tool_input, fallback=_humanize(base))


def project_tool_result(
    tool_name: str,
    content: Any,
    *,
    is_error: bool = False,
    tool_input: dict[str, Any] | None = None,
    result_chars: int | None = None,
) -> ProjectedResult:
    """Project one tool result. Never raises."""
    base = _base_name(tool_name)
    try:
        text = normalize_content(content)
    except Exception:  # pragma: no cover - normalize_content is defensive already
        text = str(content or "")
    full_length = result_chars if isinstance(result_chars, int) and result_chars >= 0 else len(text)
    if is_error:
        summary, body = error_projection(text)
        if base == "Bash":
            try:
                projected = ops.project_bash(body, tool_input, is_error=True)
                projected.summary = summary
                projected.result_chars = full_length
                return projected
            except Exception:
                logger.warning("tool projection failed tool=%s (error path)", tool_name, exc_info=True)
        return ProjectedResult(
            summary=summary,
            result={"kind": "text"},
            result_text=body,
            result_chars=full_length,
            truncated=len(body) < len(text),
        )
    try:
        projected = _dispatch(tool_name, base, text, tool_input if isinstance(tool_input, dict) else None)
    except Exception:
        logger.warning("tool projection failed tool=%s; falling back to text", tool_name, exc_info=True)
        projected = text_result(text, summary=first_line(text) or f"{_humanize(base)} completed")
    if not projected.summary.strip():
        projected.summary = f"{_humanize(base)} completed"
    if not isinstance(projected.result, dict) or not projected.result.get("kind"):
        projected.result = {"kind": "text"}
    if full_length > len(text) or projected.result_chars is None:
        projected.result_chars = full_length
    if full_length > len(text):
        projected.truncated = True
    return projected


def _serialized_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"))


def _shrink_result(result: dict[str, Any]) -> bool:
    """Apply the first applicable size reduction; True when something changed."""
    kind = result.get("kind")
    if kind == "table" and len(result.get("rows") or []) > TABLE_ROWS_SHRUNK:
        result["rows"] = result["rows"][:TABLE_ROWS_SHRUNK]
        result["preview_truncated"] = True
        return True
    if kind == "table_list" and len(result.get("entries") or []) > TABLE_LIST_SHRUNK:
        result["entries"] = result["entries"][:TABLE_LIST_SHRUNK]
        result["entries_truncated"] = True
        return True
    if kind in ("schema", "column_profile") and len(result.get("columns") or []) > SCHEMA_COLS_SHRUNK:
        result["columns"] = result["columns"][:SCHEMA_COLS_SHRUNK]
        result["columns_truncated"] = True
        return True
    if kind == "dbt_run" and len(result.get("log") or "") > RESULT_TEXT_SHRUNK:
        result["log"] = result["log"][-RESULT_TEXT_SHRUNK:]
        result["log_truncated"] = True
        return True
    if kind == "terminal":
        changed = False
        for key in ("stdout", "stderr"):
            if len(result.get(key) or "") > RESULT_TEXT_SHRUNK:
                result[key] = result[key][:RESULT_TEXT_SHRUNK]
                result[f"{key}_truncated"] = True
                changed = True
        return changed
    return False


def finalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable payload at most ``PAYLOAD_MAX`` bytes.

    Shrinks in order: kind-specific bulk (rows→20, entries→50, columns→100,
    logs→2 KB), then ``result_text``→2 KB, then ``result``→``{"kind":"text"}``
    with the text dropped. Sets ``truncated`` whenever it changed something.
    """
    payload = json.loads(json.dumps(payload, separators=(",", ":"), default=str))
    if _serialized_size(payload) <= PAYLOAD_MAX:
        return payload
    result = payload.get("result")
    if isinstance(result, dict):
        while _serialized_size(payload) > PAYLOAD_MAX and _shrink_result(result):
            payload["truncated"] = True
    if _serialized_size(payload) > PAYLOAD_MAX and isinstance(payload.get("result_text"), str):
        payload["result_text"] = payload["result_text"][:RESULT_TEXT_SHRUNK]
        payload["truncated"] = True
    if _serialized_size(payload) > PAYLOAD_MAX:
        payload["result"] = {"kind": "text"}
        payload["truncated"] = True
    if _serialized_size(payload) > PAYLOAD_MAX:
        payload.pop("result_text", None)
        payload["truncated"] = True
    if _serialized_size(payload) > PAYLOAD_MAX:
        payload.pop("report", None)
        payload["summary"] = str(payload.get("summary") or "")[:300]
        payload["truncated"] = True
    return payload
