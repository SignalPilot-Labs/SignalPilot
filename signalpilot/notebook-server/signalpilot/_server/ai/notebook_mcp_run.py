"""run_cells handler for the notebook MCP server.

Runs cells through the kernel HTTP API, waits for a fresh terminal
notification per cell, and reports every non-successful state as an error.
In the chat runtime the error payload is plain text: exception type and
message first, the last three traceback frames without Pygments HTML, and
cells that were skipped because an ancestor failed collapsed to one line.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from signalpilot._messaging.tracebacks import (
    TRACEBACK_MIMETYPE,
    is_code_highlighting,
    plain_traceback_text,
)
from signalpilot._server.ai.chat_runtime_output import (
    compact_chat_runtime_output,
    redact_chat_runtime_text,
)
from signalpilot._server.ai.notebook_mcp_edit import (
    _local_server_url,
    _server_headers,
)
from signalpilot._server.ai.notebook_mcp_graph import (
    NotebookToolError,
    _graph_error_payload,
    _raise_notebook_failure,
)
from signalpilot._server.ai.tools.exceptions import ToolExecutionError
from signalpilot._types.ids import CellId_t

if TYPE_CHECKING:
    from signalpilot._server.ai.tools.base import ToolContext

_ANCESTOR_ERROR_TYPES = {"SpAncestorPreventedError", "SpAncestorStoppedError"}
_ANCESTOR_EXCEPTION_TYPE = "Ancestor raised"


def _ancestor_failure(error: Any) -> str | None:
    """The raising ancestor id when ``error`` only says an ancestor failed."""
    if (
        type(error).__name__ not in _ANCESTOR_ERROR_TYPES
        and str(getattr(error, "exception_type", "") or "")
        != _ANCESTOR_EXCEPTION_TYPE
    ):
        return None
    raising = getattr(error, "raising_cell", None) or getattr(
        error, "blamed_cell", None
    )
    return str(raising) if raising else "unknown"


def _error_detail(
    error: Any,
    cell_id_string: str,
    *,
    chat_runtime: bool,
    redactions: tuple[str, ...],
) -> dict[str, Any]:
    message = str(
        error.describe()
        if hasattr(error, "describe")
        else getattr(error, "msg", "Cell execution failed")
    )
    if chat_runtime:
        message = redact_chat_runtime_text(message, redactions)
    detail: dict[str, Any] = {"type": type(error).__name__}
    if exception_type := getattr(error, "exception_type", None):
        detail["exception_type"] = str(exception_type)[:100]
    detail["message"] = message[:500]
    if variable := getattr(error, "name", None):
        detail["variable"] = str(variable)[:100]
    involved = {str(value) for value in getattr(error, "cells", ())}
    involved.add(cell_id_string)
    for source, _variables, target in getattr(error, "edges_with_vars", ()):
        involved.update((str(source), str(target)))
    detail["cell_ids"] = sorted(involved)
    raw_traceback = getattr(error, "traceback", None)
    if isinstance(raw_traceback, str) and raw_traceback.strip():
        text = plain_traceback_text(raw_traceback)
        if chat_runtime:
            text = redact_chat_runtime_text(text, redactions)
        detail["traceback_text"] = text
    return detail


def _is_traceback_console_item(item: Any) -> bool:
    mimetype = str(getattr(item, "mimetype", "") or "")
    text = getattr(item, "data", "") or getattr(item, "text", "")
    return mimetype == TRACEBACK_MIMETYPE or (
        isinstance(text, str) and is_code_highlighting(text)
    )


def _console_items(
    console: Any,
    *,
    chat_runtime: bool,
    redactions: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Console entries plus, in the chat runtime, extracted plain tracebacks.

    The UI path keeps the highlighted traceback in the console. The chat
    runtime never sees Pygments HTML: traceback items move to the error
    entry as ``traceback_text``.
    """
    items: list[dict[str, Any]] = []
    tracebacks: list[str] = []
    for item in console:
        channel = getattr(item, "channel", "")
        text = getattr(item, "data", "") or getattr(item, "text", "")
        if not text:
            continue
        rendered = str(text)
        if chat_runtime:
            rendered = redact_chat_runtime_text(rendered, redactions)
            if _is_traceback_console_item(item):
                tracebacks.append(plain_traceback_text(rendered))
                continue
        items.append({"channel": str(channel), "text": rendered[:1000]})
    return items, tracebacks


def _cell_result(
    cell_id: CellId_t,
    notification: Any,
    *,
    timed_out: bool,
    baseline: float,
    chat_runtime: bool,
    redactions: tuple[str, ...],
) -> dict[str, Any]:
    """One entry of ``cells`` in the run_cells payload."""
    cell_id_string = str(cell_id)
    result: dict[str, Any] = {
        "cell_id": cell_id_string,
        "status": "completed",
        "runtime_state": "unknown",
    }
    error_details: list[dict[str, Any]] = []

    if timed_out:
        error_details.append(
            {
                "type": "TimeoutError",
                "message": "Cell execution did not reach a terminal state",
            }
        )
        return _finish_cell_result(result, error_details)
    if (
        notification is None
        or float(getattr(notification, "timestamp", 0.0) or 0.0) <= baseline
    ):
        error_details.append(
            {
                "type": "UnknownStateError",
                "message": "No current execution state was reported",
            }
        )
        return _finish_cell_result(result, error_details)

    runtime_state = str(getattr(notification, "status", "") or "")
    result["runtime_state"] = runtime_state or "unknown"
    if runtime_state != "idle":
        error_details.append(
            {
                "type": "UnknownStateError",
                "message": f"Unexpected terminal state: {runtime_state or 'unknown'}",
            }
        )

    output = getattr(notification, "output", None)
    if output:
        mimetype = getattr(output, "mimetype", "")
        data = getattr(output, "data", "")
        if chat_runtime:
            data = compact_chat_runtime_output(
                data, mimetype=str(mimetype), redactions=redactions
            )
        elif isinstance(data, str) and len(data) > 2000:
            data = data[:2000] + "... (truncated)"
        output_channel = getattr(output, "channel", None)
        if getattr(output_channel, "value", output_channel) == "sp-error":
            raw_errors = getattr(output, "data", None)
            if not isinstance(raw_errors, list):
                raw_errors = []
            for error in raw_errors:
                ancestor = _ancestor_failure(error)
                if ancestor is not None:
                    return {
                        "cell_id": cell_id_string,
                        "status": "skipped",
                        "skipped_because": f"ancestor {ancestor} failed",
                    }
                error_details.append(
                    _error_detail(
                        error,
                        cell_id_string,
                        chat_runtime=chat_runtime,
                        redactions=redactions,
                    )
                )
        else:
            result["output"] = {"mimetype": str(mimetype), "data": str(data)}

    console = getattr(notification, "console", None)
    if console:
        items, tracebacks = _console_items(
            console, chat_runtime=chat_runtime, redactions=redactions
        )
        if items:
            result["console"] = items
        for text in tracebacks:
            target = next(
                (d for d in error_details if "traceback_text" not in d), None
            )
            if target is not None:
                target["traceback_text"] = text
    return _finish_cell_result(result, error_details)


def _finish_cell_result(
    result: dict[str, Any], error_details: list[dict[str, Any]]
) -> dict[str, Any]:
    if error_details:
        result["status"] = "failed"
        result["errors"] = error_details
    return result


def _queue_run(
    context: ToolContext,
    session: Any,
    session_id: str,
    run_ids: list[CellId_t],
    run_codes: list[str],
) -> None:
    import requests as _requests

    from signalpilot._messaging.cell_output import CellOutput

    hdrs = _server_headers(context, str(session_id))

    instantiate_response = _requests.post(
        _local_server_url(context, "/api/kernel/instantiate"),
        headers=hdrs,
        json={"objectIds": [], "values": [], "autoRun": False},
        timeout=10,
    )
    if instantiate_response.status_code != 200:
        raise RuntimeError(
            f"Kernel instantiate returned HTTP {instantiate_response.status_code}"
        )

    # A successful no-output execution broadcasts CellOutput.empty(). The
    # session-view merge intentionally treats an omitted output as
    # unchanged, and older runtimes also retained an explicit empty output
    # over a previous error. Clear the cached output before queueing so the
    # notification for this execution cannot inherit a stale exception.
    # The timestamp remains unchanged, so polling still requires a fresh
    # terminal notification from the kernel.
    for cell_id in run_ids:
        notification = session.session_view.cell_notifications.get(cell_id)
        if notification is not None:
            notification.output = CellOutput.empty()

    resp = _requests.post(
        _local_server_url(context, "/api/kernel/run"),
        headers=hdrs,
        json={"cellIds": [str(c) for c in run_ids], "codes": run_codes},
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Kernel execution returned HTTP {resp.status_code}")


def _wait_for_cells(
    session: Any,
    run_ids: list[CellId_t],
    baseline_timestamps: dict[CellId_t, float],
    timeout_secs: float,
) -> tuple[bool, float]:
    start = time.monotonic()
    completed = not run_ids
    while time.monotonic() - start < timeout_secs:
        time.sleep(0.5)
        all_done = True
        for cell_id in run_ids:
            notification = session.session_view.cell_notifications.get(cell_id)
            if (
                notification is None
                or float(getattr(notification, "timestamp", 0.0) or 0.0)
                <= baseline_timestamps[cell_id]
            ):
                all_done = False
                break
            status = str(getattr(notification, "status", "") or "")
            if status in {"running", "queued"}:
                all_done = False
                break
        if all_done:
            completed = True
            break
    return completed, round(time.monotonic() - start, 3)


def _handle_run_cells(
    context: ToolContext, arguments: dict[str, Any]
) -> list[Any]:
    """Run cells and report every non-successful terminal state as an error."""
    from mcp.types import TextContent

    session_id = arguments.get("session_id", "")
    cell_ids_raw = arguments.get("cell_ids", [])
    timeout_secs = arguments.get("timeout", 120)

    if not session_id:
        raise NotebookToolError(
            _graph_error_payload(
                error_type="InvalidRequest",
                cell_ids=[],
                message="session_id is required",
            )
        )
    try:
        timeout_secs = max(0.0, min(float(timeout_secs), 600.0))
    except (TypeError, ValueError) as exc:
        raise NotebookToolError(
            _graph_error_payload(
                error_type="InvalidRequest",
                cell_ids=[],
                message="timeout must be a number",
            )
        ) from exc

    try:
        session = context.get_session(session_id)
    except ToolExecutionError as e:
        raise NotebookToolError(
            _graph_error_payload(
                error_type="SessionNotFound",
                cell_ids=[],
                message=e.message,
            )
        ) from e

    cell_manager = session.app_file_manager.app.cell_manager
    cell_data_map = {cd.cell_id: cd for cd in cell_manager.cell_data()}

    if cell_ids_raw:
        run_ids = [CellId_t(cid) for cid in cell_ids_raw]
    else:
        run_ids = list(cell_data_map)

    missing_ids = [
        str(cell_id) for cell_id in run_ids if cell_id not in cell_data_map
    ]
    if missing_ids:
        _raise_notebook_failure(
            session,
            _graph_error_payload(
                error_type="CellNotFound",
                cell_ids=missing_ids,
                message="Requested cells are not present in the notebook",
            ),
            dirty=False,
        )

    run_codes = [cell_data_map[cid].code for cid in run_ids]
    baseline_timestamps = {
        cell_id: float(
            getattr(
                session.session_view.cell_notifications.get(cell_id),
                "timestamp",
                0.0,
            )
            or 0.0
        )
        for cell_id in run_ids
    }

    try:
        _queue_run(context, session, str(session_id), run_ids, run_codes)
    except Exception as exc:
        _raise_notebook_failure(
            session,
            _graph_error_payload(
                error_type="KernelQueueError",
                cell_ids=[str(cell_id) for cell_id in run_ids],
                message=type(exc).__name__,
            ),
            dirty=False,
        )

    completed, elapsed = _wait_for_cells(
        session, run_ids, baseline_timestamps, timeout_secs
    )
    timed_out = not completed
    chat_runtime = bool(getattr(session, "_signalpilot_chat_runtime", False))
    redactions = tuple(
        getattr(session, "_signalpilot_chat_redactions", ()) or ()
    )

    cell_results: list[dict[str, Any]] = []
    failed_cell_ids: list[str] = []
    skipped_cell_ids: list[str] = []
    failure_errors: list[dict[str, Any]] = []
    for cell_id in run_ids:
        result = _cell_result(
            cell_id,
            session.session_view.cell_notifications.get(cell_id),
            timed_out=timed_out,
            baseline=baseline_timestamps[cell_id],
            chat_runtime=chat_runtime,
            redactions=redactions,
        )
        if result["status"] == "failed":
            failed_cell_ids.append(result["cell_id"])
            failure_errors.extend(result["errors"])
        elif result["status"] == "skipped":
            skipped_cell_ids.append(result["cell_id"])
        cell_results.append(result)

    has_errors = bool(failed_cell_ids or skipped_cell_ids)
    payload: dict[str, Any] = {
        "status": "failed" if has_errors else "completed",
        "has_errors": has_errors,
        "cell_ids": [str(cell_id) for cell_id in run_ids],
        "failed_cell_ids": failed_cell_ids,
        "skipped_cell_ids": skipped_cell_ids,
        "cells": cell_results,
        "elapsed_seconds": elapsed,
        "timed_out": timed_out,
    }
    if has_errors:
        if failure_errors:
            first_error = failure_errors[0]
            error = {
                "type": first_error["type"],
                "variable": first_error.get("variable"),
                "cell_ids": failed_cell_ids,
                "message": first_error.get("message"),
            }
        else:
            skipped = next(
                r for r in cell_results if r["status"] == "skipped"
            )
            error = {
                "type": "AncestorFailed",
                "variable": None,
                "cell_ids": skipped_cell_ids,
                "message": skipped["skipped_because"],
            }
        _raise_notebook_failure(
            session, {**payload, "error": error}, dirty=False
        )

    return [TextContent(type="text", text=json.dumps(payload, default=str))]
