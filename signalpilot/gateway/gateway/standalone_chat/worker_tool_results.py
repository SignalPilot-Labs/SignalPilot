"""tool_result handling for the chat worker: project, enrich, persist.

Collaborators (``get_session_factory``, ``_append``, ``_announce_notebook``)
are resolved through the worker module at call time so test monkeypatches on
``gateway.standalone_chat.worker`` keep reaching this code.
"""

from __future__ import annotations

import json
import logging
from contextlib import suppress
from typing import Any

from gateway.db.models import GatewayStructuredQueryResult
from gateway.standalone_chat.tool_projection import finalize_payload, project_tool_result
from gateway.standalone_chat.tool_projection.limits import CELL_MAX, INPUT_ECHO_MAX, TABLE_ROWS_MAX
from gateway.standalone_chat.worker_events import _notebook_started_payload

logger = logging.getLogger(__name__)

_REPORT_MAX = 4000
_STRUCTURED_TEXT_MAX = 2048


def _worker() -> Any:
    """Return the worker module. Import it late to avoid a circular import."""
    from gateway.standalone_chat import worker

    return worker


def cache_tool_input(tool_input: Any) -> dict[str, Any] | None:
    """Return a copy of ``tool_input`` bounded to ``INPUT_ECHO_MAX`` JSON bytes."""
    if not isinstance(tool_input, dict):
        return None
    try:
        if len(json.dumps(tool_input, default=str)) <= INPUT_ECHO_MAX:
            return dict(tool_input)
    except (TypeError, ValueError):
        return None
    trimmed: dict[str, Any] = {}
    for key, value in tool_input.items():
        if isinstance(value, (bool, int, float)) or value is None:
            trimmed[str(key)] = value
        elif isinstance(value, str):
            trimmed[str(key)] = value[:256]
    return trimmed


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= CELL_MAX else text[:CELL_MAX] + "…"


async def enrich_table_from_structured_result(
    result: dict[str, Any],
    *,
    run_id: str,
    org_id: str,
) -> bool:
    """Replace a parsed table preview with the durable structured result.

    Looks the row up by the ``result_id`` the tool printed in its footer and
    only trusts it when it belongs to this run and org. Returns True when the
    projection was replaced.
    """
    result_id = result.get("result_id")
    if result.get("kind") != "table" or not result_id:
        return False
    factory = _worker().get_session_factory()
    async with factory() as db:
        stored = await db.get(GatewayStructuredQueryResult, str(result_id))
    if stored is None or stored.run_id != run_id or stored.org_id != org_id:
        return False
    columns = [
        {"name": str(column.get("name")), "logical_type": column.get("logical_type")}
        for column in (stored.columns_json or [])
        if isinstance(column, dict) and column.get("name") is not None
    ]
    names = [column["name"] for column in columns]
    rows: list[list[Any]] = []
    for row in (stored.preview_rows_json or [])[:TABLE_ROWS_MAX]:
        if isinstance(row, dict):
            rows.append([_cell(row.get(name)) for name in names])
        elif isinstance(row, (list, tuple)):
            rows.append([_cell(cell) for cell in row[: len(names)]])
    result.update(
        {
            "columns": columns,
            "rows": rows,
            "preview_row_count": len(rows),
            "row_count": stored.saved_row_count,
            "query_row_count": stored.query_row_count,
            "preview_truncated": len(rows) < (stored.saved_row_count or 0),
            "columns_truncated": False,
            "completeness": stored.result_completeness
            if stored.result_completeness in ("complete", "truncated")
            else "unknown",
            "truncation_reason": stored.truncation_reason,
            "execution_id": stored.execution_id,
            "source": "structured",
        }
    )
    return True


async def handle_tool_result(
    *,
    run_id: str,
    event: dict[str, Any],
    content: str,
    parent_tool_call_id: str,
    tool_names_by_id: dict[str, str],
    tool_inputs_by_id: dict[str, dict[str, Any]],
    execution: Any,
    org_id: str,
) -> None:
    """Persist ``tool_completed`` for one tool result plus its side events."""
    worker = _worker()
    is_error = bool(event.get("is_error"))
    tool_call_id = str(event.get("tool_call_id") or "")
    completed_tool = tool_names_by_id.get(tool_call_id, "")
    tool_input = tool_inputs_by_id.get(tool_call_id)
    if is_error:
        # Author-visible events redact tool errors. Log the raw error text
        # here (server-side only) so operators can see why a tool failed.
        logger.warning(
            "standalone-chat tool error tool=%s run=%s raw=%s",
            completed_tool or "unknown",
            run_id,
            (content or "")[:2000],
        )
    raw_chars = event.get("result_chars")
    projected = project_tool_result(
        completed_tool,
        content,
        is_error=is_error,
        tool_input=tool_input,
        result_chars=raw_chars if isinstance(raw_chars, int) else None,
    )
    if projected.result.get("kind") == "table" and not is_error:
        with suppress(Exception):
            if await enrich_table_from_structured_result(projected.result, run_id=run_id, org_id=org_id):
                # The rows are now authoritative; a large raw copy is redundant.
                if projected.result_text and len(projected.result_text) > _STRUCTURED_TEXT_MAX:
                    projected.result_text = None
    payload: dict[str, Any] = {
        "tool_call_id": event.get("tool_call_id"),
        "tool": completed_tool or None,
        "error": is_error,
        "summary": projected.summary,
        "result": projected.result,
        "result_text": projected.result_text,
        "result_chars": projected.result_chars,
        "truncated": projected.truncated,
        "v": 1,
    }
    if projected.result_text is None:
        payload.pop("result_text")
    if parent_tool_call_id:
        payload["parent_tool_call_id"] = parent_tool_call_id
    if completed_tool == "Agent" and not is_error and content:
        # The Agent tool result IS the subagent's final report — surfaced in
        # its card, same disclosure level as the agent's own narration.
        payload["report"] = content[:_REPORT_MAX]
    await worker._append(run_id, "tool_completed", finalize_payload(payload))
    if not is_error and completed_tool.endswith("start_analysis_notebook"):
        await worker._announce_notebook(
            run_id,
            _notebook_started_payload(
                tool_result_content=content,
                gateway_session_id=getattr(execution, "session_id", None),
            ),
        )
    if completed_tool.endswith("run_cells"):
        await worker._append(
            run_id,
            "cell_executed",
            {"status": "failed" if is_error else "completed"},
        )
