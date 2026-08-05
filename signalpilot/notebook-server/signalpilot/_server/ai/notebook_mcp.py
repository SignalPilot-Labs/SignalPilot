"""
signalpilot-notebook-mcp: In-process MCP server for notebook tools.

Cell edits use the Document Transaction system (same as the frontend).
Transactions are applied to `session.document`, then broadcast to all
WebSocket consumers via `session.notify()` with `from_consumer_id=None`
so every connected browser sees real-time updates.

Multi-notebook: every mutating tool accepts a session_id parameter.
Use get_active_notebooks to discover available sessions.
"""

from __future__ import annotations

import ast
import json
import uuid
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any, NoReturn
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
from signalpilot._server.ai.chat_runtime_output import (
    authorize_chat_runtime_session,
    compact_chat_runtime_output,
    notebook_server_headers,
    redact_chat_runtime_text,
)
from signalpilot._server.ai.tools.exceptions import ToolExecutionError
from signalpilot._types.ids import CellId_t
from signalpilot._utils.dataclass_to_openapi import PythonTypeToOpenAPI

if TYPE_CHECKING:
    from collections.abc import Callable

    from signalpilot._server.ai.tools.base import ToolBase, ToolContext

LOGGER = _loggers.sp_logger()


class NotebookToolError(ValueError):
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        super().__init__(json.dumps(payload, default=str, sort_keys=True))


def _graph_error_payload(
    *,
    error_type: str,
    cell_ids: list[str],
    variable: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "type": error_type,
        "variable": variable,
        "cell_ids": sorted(set(cell_ids)),
    }
    if message:
        error["message"] = message[:500]
    return {"status": "rejected", "has_errors": True, "error": error}


def _validate_candidate_graph(cells: list[tuple[CellId_t, str]]) -> None:
    import linecache

    from signalpilot._ast.compiler import compile_cell, get_filename
    from signalpilot._lint.validate_graph import check_for_errors
    from signalpilot._runtime.dataflow import DirectedGraph

    filenames = {get_filename(cell_id) for cell_id, _code in cells}
    previous_cache = {
        filename: linecache.cache.get(filename) for filename in filenames
    }
    try:
        graph = DirectedGraph()
        for cell_id, code in cells:
            try:
                graph.register_cell(
                    cell_id, compile_cell(code, cell_id=cell_id)
                )
            except SyntaxError as exc:
                raise NotebookToolError(
                    _graph_error_payload(
                        error_type="SyntaxError",
                        cell_ids=[str(cell_id)],
                        message=exc.msg,
                    )
                ) from exc

        graph_errors = check_for_errors(graph)
        for cell_id in sorted(graph_errors, key=str):
            for error in graph_errors[cell_id]:
                error_type = type(error).__name__
                variable = str(getattr(error, "name", "") or "") or None
                involved = {str(cell_id)}
                involved.update(
                    str(value) for value in getattr(error, "cells", ())
                )
                edge_variables: set[str] = set()
                for source, variables, target in getattr(
                    error, "edges_with_vars", ()
                ):
                    involved.update((str(source), str(target)))
                    edge_variables.update(str(value) for value in variables)
                if variable is None and edge_variables:
                    variable = sorted(edge_variables)[0]
                raise NotebookToolError(
                    _graph_error_payload(
                        error_type=error_type,
                        variable=variable,
                        cell_ids=sorted(involved),
                        message=error.describe(),
                    )
                )
    finally:
        for filename, cached in previous_cache.items():
            if cached is None:
                linecache.cache.pop(filename, None)
            else:
                linecache.cache[filename] = cached


def _record_notebook_failure(
    session: Any,
    payload: dict[str, Any],
    *,
    dirty: bool,
) -> None:
    session._signalpilot_last_notebook_failure = payload
    recorded = list(getattr(session, "_signalpilot_notebook_failures", ()))
    recorded.append(payload)
    session._signalpilot_notebook_failures = recorded[-20:]
    if dirty:
        session._signalpilot_notebook_dirty = True
    error = payload.get("error") or {}
    LOGGER.error(
        "Notebook operation failed run_id=%s session_id=%s attempt=%s "
        "error_type=%s variable=%s cell_ids=%s dirty=%s",
        getattr(session, "_signalpilot_chat_run_id", ""),
        getattr(session, "_signalpilot_chat_session_id", ""),
        getattr(session, "_signalpilot_chat_attempt", ""),
        error.get("type"),
        error.get("variable"),
        error.get("cell_ids"),
        dirty,
    )


def _raise_notebook_failure(
    session: Any,
    payload: dict[str, Any],
    *,
    dirty: bool,
) -> NoReturn:
    _record_notebook_failure(session, payload, dirty=dirty)
    raise NotebookToolError(payload)


def _is_markdown_call(value: ast.AST) -> bool:
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Attribute) and func.attr == "md":
        return isinstance(func.value, ast.Name) and func.value.id in {
            "sp",
            "mo",
        }
    return False


def _is_markdown_only_cell(code: str) -> bool:
    try:
        parsed = ast.parse(code)
    except SyntaxError:
        return False

    has_markdown_call = False
    for node in parsed.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Expr) and _is_markdown_call(node.value):
            has_markdown_call = True
            continue
        return False
    return has_markdown_call


def _local_server_url(context: ToolContext, path: str = "") -> str:
    """Build an HTTP URL for the currently running notebook server."""
    state = context.get_app().state
    host = getattr(state, "host", "127.0.0.1") or "127.0.0.1"
    if host in {"0.0.0.0", "::", "[::]"}:
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


def build_notebook_mcp_server(
    context: ToolContext,
    *,
    session_authorizer: Callable[[str], bool] | None = None,
) -> Any:
    """
    Build an in-process MCP server with all notebook tools.

    Returns a McpSdkServerConfig for ClaudeAgentOptions.mcp_servers.
    """
    from claude_agent_sdk import McpSdkServerConfig
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    from signalpilot._server.ai.tools.registry import (
        SUPPORTED_BACKEND_AND_MCP_TOOLS,
    )

    server = Server("signalpilot-notebook", version="1.0.0")

    tool_instances: dict[str, ToolBase[Any, Any]] = {}
    for tool_cls in SUPPORTED_BACKEND_AND_MCP_TOOLS:
        inst = tool_cls(context)
        tool_instances[inst.name] = inst

    converter = PythonTypeToOpenAPI(name_overrides={}, camel_case=False)
    tool_definitions: list[Tool] = []
    for inst in tool_instances.values():
        schema = converter.convert(inst.Args, processed_classes={})
        tool_definitions.append(
            Tool(
                name=inst.name,
                description=inst.description,
                inputSchema=schema,
            )
        )

    tool_definitions.append(
        Tool(
            name="edit_notebook",
            description=(
                "Edit cells in a notebook. Supports adding, updating, and deleting cells. "
                "Each edit needs a session_id (from get_active_notebooks or the system prompt). "
                "This is a marimo notebook: every non-private top-level name, including imports "
                "and loop targets, may be defined by only one live cell. Inspect the current cell "
                "map first; use underscore-prefixed names for disposable cell-local variables, "
                "and delete or update old definitions in the same atomic edit batch. "
                "Operations: update_cell (modify existing cell code), "
                "add_cell (add a new cell with generated ID), "
                "delete_cell (remove a cell). "
                "Changes appear in the frontend in real-time and are auto-saved."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID of the target notebook",
                    },
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "update_cell",
                                        "add_cell",
                                        "delete_cell",
                                    ],
                                },
                                "cell_id": {
                                    "type": "string",
                                    "description": "Cell ID (required for update_cell, delete_cell)",
                                },
                                "code": {
                                    "type": "string",
                                    "description": "Python code (required for update_cell, add_cell)",
                                },
                            },
                            "required": ["type"],
                        },
                        "description": "List of edit operations to apply",
                    },
                },
                "required": ["session_id", "edits"],
            },
        )
    )
    tool_definitions.append(
        Tool(
            name="run_cells",
            description=(
                "Run specific cells in a notebook and wait for results. "
                "BLOCKS until all cells finish executing, then returns their outputs, "
                "console output, and any errors. "
                "Requires a session_id. If no cell_ids provided, runs ALL cells."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID of the target notebook",
                    },
                    "cell_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Cell IDs to run. If empty, runs all cells.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Max seconds to wait for completion. Default: 120.",
                    },
                },
                "required": ["session_id"],
            },
        )
    )
    tool_definitions.append(
        Tool(
            name="save_data_snapshot",
            description=(
                "Save a compact aggregate data snapshot for the current external "
                "analysis deliverable. Requires session_id, name, description, "
                "columns, and rows. Use this only for governed notebook-derived "
                "data needed by a dashboard or report; do not dump raw tables."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID of the target analysis notebook",
                    },
                    "name": {
                        "type": "string",
                        "description": "Short stable snapshot name",
                    },
                    "description": {
                        "type": "string",
                        "description": "One-sentence explanation of the snapshot",
                    },
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered column names in each row",
                    },
                    "rows": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Compact aggregate rows, JSON serializable",
                    },
                },
                "required": [
                    "session_id",
                    "name",
                    "description",
                    "columns",
                    "rows",
                ],
            },
        )
    )
    tool_definitions.append(
        Tool(
            name="start_notebook_session",
            description=(
                "Start a kernel session for a notebook file so you can edit and run its cells. "
                "Takes an absolute file path to a .py notebook. Returns a session_id "
                "that can be used with edit_notebook, run_cells, and other tools. "
                "Use this after creating a notebook with the Write tool, or to open "
                "an existing notebook that doesn't have an active session. "
                "Multiple notebooks can have active sessions simultaneously."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the .py notebook file",
                    },
                    "auto_run": {
                        "type": "boolean",
                        "description": "If true, automatically run all cells after starting. Default: false.",
                    },
                },
                "required": ["file_path"],
            },
        )
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return tool_definitions

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any]
    ) -> list[TextContent]:
        authorize_chat_runtime_session(name, arguments, session_authorizer)
        if name in tool_instances:
            return await _invoke_backend_tool(tool_instances, name, arguments)

        if name == "edit_notebook":
            return _handle_edit_notebook(context, arguments)

        if name == "run_cells":
            return _handle_run_cells(context, arguments)

        if name == "save_data_snapshot":
            return _handle_save_data_snapshot(context, arguments)

        if name == "start_notebook_session":
            return _handle_start_notebook_session(context, arguments)

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return McpSdkServerConfig(
        type="sdk", name="signalpilot-notebook", instance=server
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
                    session,
                    _graph_error_payload(
                        error_type="CellNotFound",
                        cell_ids=[cell_id] if cell_id else [],
                        message=f"Available cells: {sorted(existing_ids)}",
                    ),
                    dirty=False,
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
                    session,
                    _graph_error_payload(
                        error_type="CellNotFound",
                        cell_ids=[cell_id] if cell_id else [],
                        message=f"Available cells: {sorted(existing_ids)}",
                    ),
                    dirty=False,
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
            ]
        )
    except NotebookToolError as exc:
        _record_notebook_failure(session, exc.payload, dirty=False)
        raise

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


def _handle_run_cells(
    context: ToolContext, arguments: dict[str, Any]
) -> list[Any]:
    """Run cells and report every non-successful terminal state as an error."""
    import time

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
        import requests as _requests

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

        resp = _requests.post(
            _local_server_url(context, "/api/kernel/run"),
            headers=hdrs,
            json={"cellIds": [str(c) for c in run_ids], "codes": run_codes},
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Kernel execution returned HTTP {resp.status_code}"
            )
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

    elapsed = round(time.monotonic() - start, 3)
    timed_out = not completed
    cell_results: list[dict[str, Any]] = []
    failed_cell_ids: list[str] = []
    failure_errors: list[dict[str, Any]] = []
    chat_runtime = bool(getattr(session, "_signalpilot_chat_runtime", False))
    redactions = tuple(
        getattr(session, "_signalpilot_chat_redactions", ()) or ()
    )

    for cell_id in run_ids:
        cell_id_string = str(cell_id)
        notification = session.session_view.cell_notifications.get(cell_id)
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
        elif (
            notification is None
            or float(getattr(notification, "timestamp", 0.0) or 0.0)
            <= baseline_timestamps[cell_id]
        ):
            error_details.append(
                {
                    "type": "UnknownStateError",
                    "message": "No current execution state was reported",
                }
            )
        else:
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
                        data,
                        mimetype=str(mimetype),
                        redactions=redactions,
                    )
                elif isinstance(data, str) and len(data) > 2000:
                    data = data[:2000] + "... (truncated)"
                output_channel = getattr(output, "channel", None)
                if (
                    getattr(output_channel, "value", output_channel)
                    == "sp-error"
                ):
                    raw_errors = getattr(output, "data", None)
                    if not isinstance(raw_errors, list):
                        raw_errors = []
                    for error in raw_errors:
                        error_type = type(error).__name__
                        message = str(
                            error.describe()
                            if hasattr(error, "describe")
                            else getattr(error, "msg", "Cell execution failed")
                        )
                        if chat_runtime:
                            message = redact_chat_runtime_text(
                                message, redactions
                            )
                        detail: dict[str, Any] = {
                            "type": error_type,
                            "message": message[:500],
                        }
                        if exception_type := getattr(
                            error, "exception_type", None
                        ):
                            detail["exception_type"] = str(exception_type)[
                                :100
                            ]
                        if variable := getattr(error, "name", None):
                            detail["variable"] = str(variable)[:100]
                        involved = {
                            str(value) for value in getattr(error, "cells", ())
                        }
                        involved.add(cell_id_string)
                        for source, _variables, target in getattr(
                            error, "edges_with_vars", ()
                        ):
                            involved.update((str(source), str(target)))
                        if involved:
                            detail["cell_ids"] = sorted(involved)
                        error_details.append(detail)
                else:
                    result["output"] = {
                        "mimetype": str(mimetype),
                        "data": str(data),
                    }

            console = getattr(notification, "console", None)
            if console:
                console_items = []
                for item in console:
                    channel = getattr(item, "channel", "")
                    text = getattr(item, "data", "") or getattr(
                        item, "text", ""
                    )
                    if text:
                        rendered = str(text)
                        if chat_runtime:
                            rendered = redact_chat_runtime_text(
                                rendered,
                                redactions,
                            )
                        console_items.append(
                            {"channel": str(channel), "text": rendered[:1000]}
                        )
                if console_items:
                    result["console"] = console_items

        if error_details:
            result["status"] = "failed"
            result["errors"] = error_details
            failed_cell_ids.append(cell_id_string)
            failure_errors.extend(error_details)
        cell_results.append(result)

    payload = {
        "status": "failed" if failed_cell_ids else "completed",
        "has_errors": bool(failed_cell_ids),
        "cell_ids": [str(cell_id) for cell_id in run_ids],
        "failed_cell_ids": failed_cell_ids,
        "cells": cell_results,
        "elapsed_seconds": elapsed,
        "timed_out": timed_out,
    }
    if failed_cell_ids:
        first_error = failure_errors[0]
        failure_payload = {
            **payload,
            "error": {
                "type": first_error["type"],
                "variable": first_error.get("variable"),
                "cell_ids": failed_cell_ids,
                "message": first_error.get("message"),
            },
        }
        _raise_notebook_failure(session, failure_payload, dirty=False)

    return [
        TextContent(
            type="text",
            text=json.dumps(payload, default=str),
        )
    ]


def _handle_start_notebook_session(
    context: ToolContext, arguments: dict[str, Any]
) -> list[Any]:
    """Start a kernel session for a notebook file."""
    from mcp.types import TextContent

    file_path = arguments.get("file_path", "")
    auto_run = arguments.get("auto_run", False)

    if not file_path:
        return [TextContent(type="text", text="Error: file_path is required")]

    import os

    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)

    if not os.path.exists(file_path):
        return [
            TextContent(
                type="text", text=f"Error: File not found: {file_path}"
            )
        ]

    try:
        sm = context.session_manager

        # Check if a session already exists for this file
        for sid, sess in sm.sessions.items():
            sess_path = sess.app_file_manager.path
            if sess_path and os.path.normpath(
                str(sess_path)
            ) == os.path.normpath(file_path):
                LOGGER.info(
                    f"[start_session] Existing session {sid} for {file_path}"
                )
                cell_data = list(
                    sess.app_file_manager.app.cell_manager.cell_data()
                )
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "session_id": str(sid),
                                "status": "already_running",
                                "file": file_path,
                                "cells": len(cell_data),
                            }
                        ),
                    )
                ]

        # Create a headless consumer for the session
        from signalpilot._session.consumer import SessionConsumer
        from signalpilot._session.model import ConnectionState
        from signalpilot._types.ids import ConsumerId, SessionId

        new_session_id = SessionId(f"s_{uuid.uuid4().hex[:6]}")
        consumer_id = ConsumerId(str(new_session_id))

        class HeadlessConsumer(SessionConsumer):
            """Minimal consumer for agent-managed sessions."""

            def __init__(self, cid: ConsumerId) -> None:
                self._consumer_id = cid
                self._state = ConnectionState.OPEN

            @property
            def consumer_id(self) -> ConsumerId:
                return self._consumer_id

            def notify(self, notification: Any) -> None:
                pass  # Discard — agent reads state via MCP tools

            def connection_state(self) -> ConnectionState:
                return self._state

            def on_attach(self, session: Any, event_bus: Any) -> None:
                pass

            def on_detach(self) -> None:
                self._state = ConnectionState.CLOSED

        consumer = HeadlessConsumer(consumer_id)

        session = sm.create_session(
            session_id=new_session_id,
            session_consumer=consumer,
            query_params={},
            file_key=file_path,
            auto_instantiate=True,
        )

        LOGGER.info(
            f"[start_session] Created session {new_session_id} for {file_path}"
        )

        # Wait for kernel to be ready, then instantiate via HTTP
        import time

        import requests as _requests

        hdrs = _server_headers(context, str(new_session_id))

        # Wait for kernel process to be alive
        for attempt in range(10):
            km = getattr(session, "_kernel_manager", None)
            if km and km.is_alive():
                LOGGER.info(
                    f"[start_session] Kernel alive after {attempt * 0.5}s"
                )
                break
            time.sleep(0.5)
        else:
            LOGGER.warning("[start_session] Kernel not alive after 5s")

        # Instantiate with retry
        instantiate_ok = False
        for attempt in range(5):
            try:
                resp = _requests.post(
                    _local_server_url(context, "/api/kernel/instantiate"),
                    headers=hdrs,
                    json={"objectIds": [], "values": [], "autoRun": auto_run},
                    timeout=15,
                )
                LOGGER.info(
                    f"[start_session] Instantiate attempt {attempt + 1}: HTTP {resp.status_code} {resp.text[:100]}"
                )
                if resp.status_code == 200:
                    instantiate_ok = True
                    break
            except Exception as e:
                LOGGER.warning(
                    f"[start_session] Instantiate attempt {attempt + 1} failed: {e}"
                )
            time.sleep(1.0)

        if not instantiate_ok:
            LOGGER.error("[start_session] All instantiate attempts failed")

        cell_data = list(session.app_file_manager.app.cell_manager.cell_data())
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "session_id": str(new_session_id),
                        "status": "started",
                        "file": file_path,
                        "cells": len(cell_data),
                        "cell_ids": [str(cd.cell_id) for cd in cell_data],
                        "auto_run": auto_run,
                    }
                ),
            )
        ]

    except Exception as e:
        LOGGER.error(f"[start_session] Failed: {e}")
        import traceback

        return [
            TextContent(
                type="text",
                text=f"Error starting session: {e}\n{traceback.format_exc()[:500]}",
            )
        ]


async def _invoke_backend_tool(
    tool_instances: dict[str, ToolBase[Any, Any]],
    name: str,
    arguments: dict[str, Any],
) -> list[Any]:
    from mcp.types import TextContent

    t = tool_instances[name]
    runtime_redactions: tuple[str, ...] = ()
    chat_runtime = False
    session_id = str(arguments.get("session_id") or "")
    if session_id:
        try:
            session = t.context.get_session(session_id)
            chat_runtime = bool(
                getattr(session, "_signalpilot_chat_runtime", False)
            )
            runtime_redactions = tuple(
                getattr(session, "_signalpilot_chat_redactions", ()) or ()
            )
        except Exception:
            pass

    try:
        result = await t(arguments)
        if is_dataclass(result):
            text = json.dumps(asdict(result), default=str)
        elif isinstance(result, dict):
            text = json.dumps(result, default=str)
        else:
            text = str(result)
        if chat_runtime:
            text = compact_chat_runtime_output(
                text,
                mimetype="application/json",
                redactions=runtime_redactions,
            )
        return [TextContent(type="text", text=text)]
    except ToolExecutionError as e:
        error_text = (
            f"Error: {e.message}\nSuggested fix: {e.suggested_fix or 'N/A'}"
        )
        return [
            TextContent(
                type="text",
                text=redact_chat_runtime_text(error_text, runtime_redactions),
            )
        ]
    except Exception as e:
        LOGGER.error(f"Tool {name} failed: {e}")
        return [
            TextContent(
                type="text",
                text=redact_chat_runtime_text(
                    f"Error: {e}", runtime_redactions
                ),
            )
        ]
