"""edit_notebook and save_data_snapshot handlers for the notebook MCP server.

Cell edits use the Document Transaction system (same as the frontend).
Transactions are applied to `session.document`, then broadcast to all
WebSocket consumers via `session.notify()` with `from_consumer_id=None`
so every connected browser sees real-time updates.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any
from urllib.parse import urlunsplit

from signalpilot import _loggers
from signalpilot._ast.cell import CellConfig
from signalpilot._messaging.notebook.changes import (
    CreateCell,
    DeleteCell,
    SetCode,
    SetConfig,
    Transaction,
)
from signalpilot._messaging.notification import (
    NotebookDocumentTransactionNotification,
)
from signalpilot._server.ai.chat_runtime_output import notebook_server_headers
from signalpilot._server.ai.notebook_mcp_graph import (
    NotebookToolError,
    _graph_error_payload,
    _is_markdown_only_cell,
    _raise_notebook_failure,
    _record_notebook_failure,
    _validate_candidate_graph,
)
from signalpilot._server.ai.tools.exceptions import ToolExecutionError
from signalpilot._types.ids import CellId_t

if TYPE_CHECKING:
    from signalpilot._server.ai.tools.base import ToolContext

LOGGER = _loggers.sp_logger()

REJECTED_NEW_CELLS_HINT = (
    "These cells were not created. Send add_cell again with corrected code."
)


def _local_server_url(context: ToolContext, path: str = "") -> str:
    """Build an HTTP URL for the currently running notebook server."""
    state = context.get_app().state
    host = getattr(state, "host", "127.0.0.1") or "127.0.0.1"
    if host in {"0.0.0.0", "::", "[::]"}:  # nosec B104: wildcard check, not a bind
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = int(getattr(state, "port", 2718))
    base_url = str(getattr(state, "base_url", "") or "").rstrip("/")
    normalized_path = "/" + path.lstrip("/") if path else ""
    return urlunsplit(
        ("http", f"{host}:{port}", f"{base_url}{normalized_path}", "", "")
    )


def _server_headers(context: ToolContext, session_id: str) -> dict[str, str]:
    return notebook_server_headers(
        auth_token=str(context.session_manager.auth_token),
        server_token=str(context.session_manager.skew_protection_token),
        session_id=str(session_id),
    )


def _handle_save_data_snapshot(
    context: ToolContext, arguments: dict[str, Any]
) -> list[Any]:
    from mcp.types import TextContent

    try:
        from signalpilot._server.api.deps import AppStateBase
        from signalpilot._server.api.endpoints.notion_analysis import (
            save_data_snapshot_for_session,
        )

        result = save_data_snapshot_for_session(
            AppStateBase.from_app(context.get_app()),
            session_id=str(arguments.get("session_id") or ""),
            name=str(arguments.get("name") or ""),
            description=str(arguments.get("description") or ""),
            columns=arguments.get("columns") or [],
            rows=arguments.get("rows") or [],
        )
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as exc:
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": str(exc)}),
            )
        ]


def _rejection_payload(
    payload: dict[str, Any], *, new_cell_ids: list[str]
) -> dict[str, Any]:
    """Keep committed cells in ``cell_ids``; list the uncreated cells apart.

    The candidate ids of ``add_cell`` operations never reached the document,
    so an agent must not call ``update_cell`` on them.
    """
    if not new_cell_ids:
        return payload
    new_ids = set(new_cell_ids)
    error = dict(payload.get("error") or {})
    error["cell_ids"] = [
        cell_id for cell_id in error.get("cell_ids", []) if cell_id not in new_ids
    ]
    return {
        **payload,
        "error": error,
        "rejected_new_cells": sorted(new_ids),
        "hint": REJECTED_NEW_CELLS_HINT,
    }


def _cell_not_found(cell_id: str, existing_ids: set[str]) -> dict[str, Any]:
    return _graph_error_payload(
        error_type="CellNotFound",
        cell_ids=[cell_id] if cell_id else [],
        message=f"Available cells: {sorted(existing_ids)}",
    )


def _handle_edit_notebook(
    context: ToolContext, arguments: dict[str, Any]
) -> list[Any]:
    """Apply a graph-safe notebook edit transaction."""
    from mcp.types import TextContent

    session_id = arguments.get("session_id", "")
    edits = arguments.get("edits", [])

    if not session_id:
        raise NotebookToolError(
            _graph_error_payload(
                error_type="InvalidRequest",
                cell_ids=[],
                message="session_id is required",
            )
        )
    if not edits:
        raise NotebookToolError(
            _graph_error_payload(
                error_type="InvalidRequest",
                cell_ids=[],
                message="edits list is empty",
            )
        )

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
    existing_cells = list(cell_manager.cell_data())
    existing_ids = {str(cd.cell_id) for cd in existing_cells}
    existing_by_id = {str(cd.cell_id): cd for cd in existing_cells}
    candidate_codes = {str(cd.cell_id): cd.code for cd in existing_cells}
    candidate_order = [str(cd.cell_id) for cd in existing_cells]
    last_cell_id = str(existing_cells[-1].cell_id) if existing_cells else None

    LOGGER.info(
        "[edit_notebook] session=%s cells=%s edits=%s",
        session_id,
        sorted(existing_ids),
        len(edits),
    )

    doc_changes: list[Any] = []
    results: list[dict[str, Any]] = []
    delete_ids: list[CellId_t] = []
    execute_ids: list[CellId_t] = []
    execute_codes: list[str] = []
    touched_ids: set[str] = set()
    new_cell_ids: list[str] = []

    for edit in edits:
        op = edit.get("type", "")
        cell_id = str(edit.get("cell_id") or "")
        code = edit.get("code")

        if op == "add_cell":
            if not isinstance(code, str):
                _raise_notebook_failure(
                    session,
                    _graph_error_payload(
                        error_type="InvalidRequest",
                        cell_ids=[],
                        message="code is required for add_cell",
                    ),
                    dirty=False,
                )
            new_id = CellId_t(str(uuid.uuid4()).replace("-", "")[:8])
            hide_code = _is_markdown_only_cell(code)
            doc_changes.append(
                CreateCell(
                    cell_id=new_id,
                    code=code,
                    name="_",
                    config=CellConfig(hide_code=hide_code),
                    after=CellId_t(last_cell_id) if last_cell_id else None,
                )
            )
            execute_ids.append(new_id)
            execute_codes.append(code)
            last_cell_id = str(new_id)
            candidate_codes[str(new_id)] = code
            candidate_order.append(str(new_id))
            new_cell_ids.append(str(new_id))
            results.append(
                {
                    "op": "add_cell",
                    "cell_id": str(new_id),
                    "status": "ok",
                    "hide_code": hide_code,
                }
            )

        elif op == "update_cell":
            if not cell_id or cell_id not in existing_ids:
                _raise_notebook_failure(
                    session, _cell_not_found(cell_id, existing_ids), dirty=False
                )
            if cell_id in touched_ids:
                _raise_notebook_failure(
                    session,
                    _graph_error_payload(
                        error_type="DuplicateEdit",
                        cell_ids=[cell_id],
                        message="A cell may be updated or deleted only once per batch",
                    ),
                    dirty=False,
                )
            if not isinstance(code, str):
                _raise_notebook_failure(
                    session,
                    _graph_error_payload(
                        error_type="InvalidRequest",
                        cell_ids=[cell_id],
                        message="code is required for update_cell",
                    ),
                    dirty=False,
                )
            touched_ids.add(cell_id)
            doc_changes.append(SetCode(cell_id=CellId_t(cell_id), code=code))
            if _is_markdown_only_cell(code):
                existing = existing_by_id[cell_id]
                if not existing.config.hide_code:
                    doc_changes.append(
                        SetConfig(
                            cell_id=CellId_t(cell_id),
                            column=existing.config.column,
                            disabled=existing.config.disabled,
                            hide_code=True,
                        )
                    )
            execute_ids.append(CellId_t(cell_id))
            execute_codes.append(code)
            candidate_codes[cell_id] = code
            results.append(
                {
                    "op": "update_cell",
                    "cell_id": cell_id,
                    "status": "ok",
                    "hide_code": _is_markdown_only_cell(code),
                }
            )

        elif op == "delete_cell":
            if not cell_id or cell_id not in existing_ids:
                _raise_notebook_failure(
                    session, _cell_not_found(cell_id, existing_ids), dirty=False
                )
            if cell_id in touched_ids:
                _raise_notebook_failure(
                    session,
                    _graph_error_payload(
                        error_type="DuplicateEdit",
                        cell_ids=[cell_id],
                        message="A cell may be updated or deleted only once per batch",
                    ),
                    dirty=False,
                )
            touched_ids.add(cell_id)
            doc_changes.append(DeleteCell(cell_id=CellId_t(cell_id)))
            delete_ids.append(CellId_t(cell_id))
            existing_ids.discard(cell_id)
            candidate_codes.pop(cell_id)
            candidate_order.remove(cell_id)
            results.append(
                {"op": "delete_cell", "cell_id": cell_id, "status": "ok"}
            )

        else:
            _raise_notebook_failure(
                session,
                _graph_error_payload(
                    error_type="InvalidRequest",
                    cell_ids=[cell_id] if cell_id else [],
                    message=f"Unknown operation: {op}",
                ),
                dirty=False,
            )

    try:
        _validate_candidate_graph(
            [
                (CellId_t(cell_id), candidate_codes[cell_id])
                for cell_id in candidate_order
            ],
            batch_cell_ids=touched_ids | set(new_cell_ids),
            new_cell_ids=new_cell_ids,
        )
    except NotebookToolError as exc:
        payload = _rejection_payload(exc.payload, new_cell_ids=new_cell_ids)
        _record_notebook_failure(session, payload, dirty=False)
        raise NotebookToolError(payload) from exc

    try:
        transaction = Transaction(changes=tuple(doc_changes), source="kernel")
        applied = session.document.apply(transaction)
        LOGGER.info(
            "[edit_notebook] Transaction applied changes=%s version=%s",
            len(doc_changes),
            applied.version,
        )
    except Exception as e:
        _raise_notebook_failure(
            session,
            _graph_error_payload(
                error_type="DocumentTransactionError",
                cell_ids=[
                    str(cell_id) for cell_id in execute_ids + delete_ids
                ],
                message=type(e).__name__,
            ),
            dirty=False,
        )

    try:
        session.notify(
            NotebookDocumentTransactionNotification(transaction=applied),
            from_consumer_id=None,
        )
        LOGGER.info("[edit_notebook] Notification broadcast")
    except Exception as e:
        LOGGER.warning("[edit_notebook] Notify failed: %s", type(e).__name__)

    try:
        import requests as _requests

        headers = _server_headers(context, str(session_id))
        for cell_id in delete_ids:
            response = _requests.post(
                _local_server_url(context, "/api/kernel/delete"),
                headers=headers,
                json={"cellId": str(cell_id)},
                timeout=15,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"Kernel deletion returned HTTP {response.status_code}"
                )

        if execute_ids:
            response = _requests.post(
                _local_server_url(context, "/api/kernel/run"),
                headers=headers,
                json={
                    "cellIds": [str(c) for c in execute_ids],
                    "codes": execute_codes,
                },
                timeout=15,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"Kernel execution returned HTTP {response.status_code}"
                )
    except Exception as exc:
        _raise_notebook_failure(
            session,
            _graph_error_payload(
                error_type="DocumentKernelSynchronizationError",
                cell_ids=[
                    str(cell_id) for cell_id in delete_ids + execute_ids
                ],
                message=type(exc).__name__,
            ),
            dirty=True,
        )

    try:
        from signalpilot._server.models.models import SaveNotebookRequest

        save_ids, save_codes, save_names, save_configs = [], [], [], []
        for cd in cell_manager.cell_data():
            save_ids.append(cd.cell_id)
            save_codes.append(cd.code)
            save_names.append(cd.name or "_")
            save_configs.append(cd.config)

        filename = str(session.app_file_manager.path or "")
        if filename:
            save_req = SaveNotebookRequest(
                cell_ids=save_ids,
                codes=save_codes,
                names=save_names,
                configs=save_configs,
                filename=filename,
                persist=True,
            )
            session.app_file_manager.save(save_req)
            LOGGER.info("[edit_notebook] Saved to %s", filename)
    except Exception as e:
        LOGGER.warning(
            "[edit_notebook] Auto-save failed: %s", type(e).__name__
        )

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "status": "completed",
                    "has_errors": False,
                    "edits": results,
                    "cells_before": len(existing_cells),
                    "changes_applied": len(doc_changes),
                },
                default=str,
            ),
        )
    ]
