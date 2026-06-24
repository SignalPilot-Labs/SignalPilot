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
from typing import Any
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
from signalpilot._server.ai.tools.base import ToolBase, ToolContext
from signalpilot._server.ai.tools.exceptions import ToolExecutionError
from signalpilot._server.ai.tools.registry import (
    SUPPORTED_BACKEND_AND_MCP_TOOLS,
)
from signalpilot._types.ids import CellId_t
from signalpilot._utils.dataclass_to_openapi import PythonTypeToOpenAPI

LOGGER = _loggers.sp_logger()


def _is_markdown_call(value: ast.AST) -> bool:
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Attribute) and func.attr == "md":
        return isinstance(func.value, ast.Name) and func.value.id in {"sp", "mo"}
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
    token = str(context.session_manager.skew_protection_token)
    return {
        "Content-Type": "application/json",
        "Sp-Server-Token": token,
        "Sp-Session-Id": str(session_id),
    }


def build_notebook_mcp_server(context: ToolContext) -> Any:
    """
    Build an in-process MCP server with all notebook tools.

    Returns a McpSdkServerConfig for ClaudeAgentOptions.mcp_servers.
    """
    from claude_agent_sdk import McpSdkServerConfig
    from mcp.server import Server
    from mcp.types import TextContent, Tool

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
                                    "enum": ["update_cell", "add_cell", "delete_cell"],
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
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name in tool_instances:
            return await _invoke_backend_tool(tool_instances, name, arguments)

        if name == "edit_notebook":
            return _handle_edit_notebook(context, arguments)

        if name == "run_cells":
            return _handle_run_cells(context, arguments)

        if name == "start_notebook_session":
            return _handle_start_notebook_session(context, arguments)

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return McpSdkServerConfig(
        type="sdk", name="signalpilot-notebook", instance=server
    )


def _handle_edit_notebook(
    context: ToolContext, arguments: dict[str, Any]
) -> list[Any]:
    """Edit notebook cells via Document Transaction system.

    Uses session.document.apply() + session.notify() to update both
    the backend document model and all connected frontends in real-time.
    """
    from mcp.types import TextContent

    session_id = arguments.get("session_id", "")
    edits = arguments.get("edits", [])

    if not session_id:
        return [TextContent(type="text", text="Error: session_id is required. Call get_active_notebooks first.")]
    if not edits:
        return [TextContent(type="text", text="Error: edits list is empty")]

    try:
        session = context.get_session(session_id)
    except ToolExecutionError as e:
        return [TextContent(type="text", text=f"Error: {e.message}")]

    cell_manager = session.app_file_manager.app.cell_manager
    existing_cells = list(cell_manager.cell_data())
    existing_ids = {str(cd.cell_id) for cd in existing_cells}
    existing_by_id = {str(cd.cell_id): cd for cd in existing_cells}
    last_cell_id = str(existing_cells[-1].cell_id) if existing_cells else None

    LOGGER.info(f"[edit_notebook] session={session_id}, cells={sorted(existing_ids)}, edits={len(edits)}")

    # Build document changes and track results
    doc_changes = []
    results = []
    execute_ids: list[CellId_t] = []
    execute_codes: list[str] = []

    for edit in edits:
        op = edit.get("type", "")
        cell_id = edit.get("cell_id", "")
        code = edit.get("code", "")

        if op == "add_cell":
            new_id = CellId_t(str(uuid.uuid4()).replace("-", "")[:8])
            hide_code = _is_markdown_only_cell(code)
            doc_changes.append(CreateCell(
                cell_id=new_id,
                code=code,
                name="_",
                config=CellConfig(hide_code=hide_code),
                after=CellId_t(last_cell_id) if last_cell_id else None,
            ))
            execute_ids.append(new_id)
            execute_codes.append(code)
            last_cell_id = str(new_id)
            results.append({"op": "add_cell", "cell_id": str(new_id), "status": "ok", "hide_code": hide_code})

        elif op == "update_cell":
            if not cell_id or cell_id not in existing_ids:
                results.append({"op": op, "cell_id": cell_id,
                                "error": f"cell_id not found. Available: {sorted(existing_ids)}"})
                continue
            doc_changes.append(SetCode(cell_id=CellId_t(cell_id), code=code))
            if _is_markdown_only_cell(code):
                existing = existing_by_id[cell_id]
                if not existing.config.hide_code:
                    doc_changes.append(SetConfig(
                        cell_id=CellId_t(cell_id),
                        column=existing.config.column,
                        disabled=existing.config.disabled,
                        hide_code=True,
                    ))
            execute_ids.append(CellId_t(cell_id))
            execute_codes.append(code)
            results.append({"op": "update_cell", "cell_id": cell_id, "status": "ok", "hide_code": _is_markdown_only_cell(code)})

        elif op == "delete_cell":
            if not cell_id or cell_id not in existing_ids:
                results.append({"op": op, "cell_id": cell_id,
                                "error": f"cell_id not found. Available: {sorted(existing_ids)}"})
                continue
            doc_changes.append(DeleteCell(cell_id=CellId_t(cell_id)))
            existing_ids.discard(cell_id)
            results.append({"op": "delete_cell", "cell_id": cell_id, "status": "ok"})

        else:
            results.append({"op": op, "error": f"Unknown operation: {op}"})

    if not doc_changes:
        return [TextContent(type="text", text=json.dumps({"edits": results}, default=str))]

    # 1. Apply document transaction — updates backend document model
    try:
        transaction = Transaction(changes=tuple(doc_changes), source="kernel")
        applied = session.document.apply(transaction)
        LOGGER.info(f"[edit_notebook] Transaction applied: {len(doc_changes)} changes, version={applied.version}")
    except Exception as e:
        LOGGER.error(f"[edit_notebook] Transaction failed: {e}")
        return [TextContent(type="text", text=json.dumps({
            "error": f"Transaction failed: {e}",
            "edits": results,
        }, default=str))]

    # 2. Notify ALL WebSocket consumers (from_consumer_id=None = no exclusion)
    try:
        session.notify(
            NotebookDocumentTransactionNotification(transaction=applied),
            from_consumer_id=None,
        )
        LOGGER.info("[edit_notebook] Notification broadcast to all consumers")
    except Exception as e:
        LOGGER.error(f"[edit_notebook] Notify failed: {e}")

    # 3. Execute updated/new cells via HTTP (put_control_request doesn't work from MCP thread)
    if execute_ids:
        try:
            import requests as _requests

            resp = _requests.post(
                _local_server_url(context, "/api/kernel/run"),
                headers=_server_headers(context, str(session_id)),
                json={
                    "cellIds": [str(c) for c in execute_ids],
                    "codes": execute_codes,
                },
                timeout=15,
            )
            LOGGER.info(f"[edit_notebook] Executed {len(execute_ids)} cells via HTTP: {resp.status_code}")
        except Exception as e:
            LOGGER.warning(f"[edit_notebook] Execution failed: {e}")

    # 4. Auto-save to disk
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
            LOGGER.info(f"[edit_notebook] Saved to {filename}")
    except Exception as e:
        LOGGER.warning(f"[edit_notebook] Auto-save failed: {e}")

    return [TextContent(type="text", text=json.dumps({
        "edits": results,
        "cells_before": len(existing_cells),
        "changes_applied": len(doc_changes),
    }, default=str))]


def _handle_run_cells(
    context: ToolContext, arguments: dict[str, Any]
) -> list[Any]:
    """Run cells and wait for completion, returning outputs.

    Blocks until all cells finish executing (idle or error),
    then returns their outputs and any errors.
    """
    import time

    from mcp.types import TextContent

    session_id = arguments.get("session_id", "")
    cell_ids_raw = arguments.get("cell_ids", [])
    timeout_secs = arguments.get("timeout", 120)

    if not session_id:
        return [TextContent(type="text", text="Error: session_id is required")]

    try:
        session = context.get_session(session_id)
    except ToolExecutionError as e:
        return [TextContent(type="text", text=f"Error: {e.message}")]

    cell_manager = session.app_file_manager.app.cell_manager

    if cell_ids_raw:
        run_ids = [CellId_t(cid) for cid in cell_ids_raw]
    else:
        run_ids = [cd.cell_id for cd in cell_manager.cell_data()]

    cell_data_map = {cd.cell_id: cd for cd in cell_manager.cell_data()}
    run_codes = [cell_data_map[cid].code if cid in cell_data_map else "" for cid in run_ids]

    # Execute via HTTP API (put_control_request doesn't work from MCP thread)
    try:
        import requests as _requests

        hdrs = _server_headers(context, str(session_id))

        # Ensure kernel is instantiated first
        _requests.post(
            _local_server_url(context, "/api/kernel/instantiate"),
            headers=hdrs,
            json={"objectIds": [], "values": [], "autoRun": False},
            timeout=10,
        )

        resp = _requests.post(
            _local_server_url(context, "/api/kernel/run"),
            headers=hdrs,
            json={"cellIds": [str(c) for c in run_ids], "codes": run_codes},
            timeout=15,
        )
        if resp.status_code != 200:
            return [TextContent(type="text", text=f"Error running cells: HTTP {resp.status_code}: {resp.text[:200]}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error queuing cells: {e}")]

    # Poll until all cells are idle/error or timeout
    run_id_set = {str(cid) for cid in run_ids}
    start = time.monotonic()
    while time.monotonic() - start < timeout_secs:
        time.sleep(0.5)
        all_done = True
        for cid in run_id_set:
            notif = session.session_view.cell_notifications.get(CellId_t(cid))
            if notif is None:
                all_done = False
                break
            status = getattr(notif, "status", None) or getattr(notif, "runtime_state", None)
            status_str = str(status) if status else ""
            if "running" in status_str.lower() or "queued" in status_str.lower():
                all_done = False
                break
        if all_done:
            break

    # Collect results
    cell_results = []
    for cid in run_ids:
        cid_str = str(cid)
        notif = session.session_view.cell_notifications.get(cid)
        result: dict[str, Any] = {"cell_id": cid_str}

        if notif is None:
            result["status"] = "unknown"
            result["output"] = None
        else:
            status = getattr(notif, "status", None) or getattr(notif, "runtime_state", None)
            result["status"] = str(status) if status else "unknown"

            # Get output
            output = getattr(notif, "output", None)
            if output:
                mimetype = getattr(output, "mimetype", "")
                data = getattr(output, "data", "")
                if isinstance(data, str) and len(data) > 2000:
                    data = data[:2000] + "... (truncated)"
                result["output"] = {"mimetype": str(mimetype), "data": str(data)}

            # Get console output
            console = getattr(notif, "console", None)
            if console:
                console_items = []
                for item in console:
                    channel = getattr(item, "channel", "")
                    text = getattr(item, "data", "") or getattr(item, "text", "")
                    if text:
                        console_items.append({"channel": str(channel), "text": str(text)[:1000]})
                if console_items:
                    result["console"] = console_items

            # Get errors
            errors = getattr(notif, "errors", None) or []
            if errors:
                error_list = []
                for err in errors:
                    msg = getattr(err, "msg", "") or str(err)
                    error_list.append(str(msg)[:500])
                result["errors"] = error_list

        cell_results.append(result)

    elapsed = round(time.monotonic() - start, 1)
    timed_out = elapsed >= timeout_secs

    return [TextContent(type="text", text=json.dumps({
        "cells": cell_results,
        "elapsed_seconds": elapsed,
        "timed_out": timed_out,
    }, default=str))]


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
        return [TextContent(type="text", text=f"Error: File not found: {file_path}")]

    try:
        sm = context.session_manager

        # Check if a session already exists for this file
        for sid, sess in sm.sessions.items():
            sess_path = sess.app_file_manager.path
            if sess_path and os.path.normpath(str(sess_path)) == os.path.normpath(file_path):
                LOGGER.info(f"[start_session] Existing session {sid} for {file_path}")
                cell_data = list(sess.app_file_manager.app.cell_manager.cell_data())
                return [TextContent(type="text", text=json.dumps({
                    "session_id": str(sid),
                    "status": "already_running",
                    "file": file_path,
                    "cells": len(cell_data),
                }))]

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

        LOGGER.info(f"[start_session] Created session {new_session_id} for {file_path}")

        # Wait for kernel to be ready, then instantiate via HTTP
        import time

        import requests as _requests

        hdrs = _server_headers(context, str(new_session_id))

        # Wait for kernel process to be alive
        for attempt in range(10):
            km = getattr(session, '_kernel_manager', None)
            if km and km.is_alive():
                LOGGER.info(f"[start_session] Kernel alive after {attempt * 0.5}s")
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
                LOGGER.info(f"[start_session] Instantiate attempt {attempt + 1}: HTTP {resp.status_code} {resp.text[:100]}")
                if resp.status_code == 200:
                    instantiate_ok = True
                    break
            except Exception as e:
                LOGGER.warning(f"[start_session] Instantiate attempt {attempt + 1} failed: {e}")
            time.sleep(1.0)

        if not instantiate_ok:
            LOGGER.error("[start_session] All instantiate attempts failed")

        cell_data = list(session.app_file_manager.app.cell_manager.cell_data())
        return [TextContent(type="text", text=json.dumps({
            "session_id": str(new_session_id),
            "status": "started",
            "file": file_path,
            "cells": len(cell_data),
            "cell_ids": [str(cd.cell_id) for cd in cell_data],
            "auto_run": auto_run,
        }))]

    except Exception as e:
        LOGGER.error(f"[start_session] Failed: {e}")
        import traceback
        return [TextContent(type="text", text=f"Error starting session: {e}\n{traceback.format_exc()[:500]}")]


async def _invoke_backend_tool(
    tool_instances: dict[str, ToolBase[Any, Any]],
    name: str,
    arguments: dict[str, Any],
) -> list[Any]:
    from mcp.types import TextContent

    t = tool_instances[name]

    try:
        result = await t(arguments)
        if is_dataclass(result):
            text = json.dumps(asdict(result), default=str)
        elif isinstance(result, dict):
            text = json.dumps(result, default=str)
        else:
            text = str(result)
        return [TextContent(type="text", text=text)]
    except ToolExecutionError as e:
        return [
            TextContent(
                type="text",
                text=f"Error: {e.message}\nSuggested fix: {e.suggested_fix or 'N/A'}",
            )
        ]
    except Exception as e:
        LOGGER.error(f"Tool {name} failed: {e}")
        return [TextContent(type="text", text=f"Error: {e}")]
