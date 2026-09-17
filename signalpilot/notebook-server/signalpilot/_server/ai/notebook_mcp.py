"""
signalpilot-notebook-mcp: In-process MCP server for notebook tools.

Cell edits use the Document Transaction system (same as the frontend).
Transactions are applied to `session.document`, then broadcast to all
WebSocket consumers via `session.notify()` with `from_consumer_id=None`
so every connected browser sees real-time updates.

Multi-notebook: every mutating tool accepts a session_id parameter.
Use get_active_notebooks to discover available sessions.

The handlers live in sibling modules; this module builds the server and
re-exports the handler entry points other modules and tests import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from signalpilot import _loggers
from signalpilot._server.ai.chat_runtime_output import (
    authorize_chat_runtime_session,
)
from signalpilot._server.ai.notebook_mcp_edit import (
    REJECTED_NEW_CELLS_HINT,
    _handle_edit_notebook,
    _handle_save_data_snapshot,
    _local_server_url,
    _server_headers,
)
from signalpilot._server.ai.notebook_mcp_graph import (
    NotebookToolError,
    _graph_error_payload,
    _is_markdown_only_cell,
    _raise_notebook_failure,
    _record_notebook_failure,
    _validate_candidate_graph,
)
from signalpilot._server.ai.notebook_mcp_run import _handle_run_cells
from signalpilot._server.ai.notebook_mcp_session import (
    ACTIVE_NOTEBOOKS_TOOL,
    _handle_start_notebook_session,
    _invoke_backend_tool,
)
from signalpilot._utils.dataclass_to_openapi import PythonTypeToOpenAPI

if TYPE_CHECKING:
    from collections.abc import Callable

    from signalpilot._server.ai.tools.base import ToolBase, ToolContext

LOGGER = _loggers.sp_logger()

__all__ = [
    "ACTIVE_NOTEBOOKS_TOOL",
    "REJECTED_NEW_CELLS_HINT",
    "NotebookToolError",
    "_graph_error_payload",
    "_handle_edit_notebook",
    "_handle_run_cells",
    "_handle_save_data_snapshot",
    "_handle_start_notebook_session",
    "_invoke_backend_tool",
    "_is_markdown_only_cell",
    "_local_server_url",
    "_raise_notebook_failure",
    "_record_notebook_failure",
    "_server_headers",
    "_validate_candidate_graph",
    "build_notebook_mcp_server",
    "notebook_tool_schemas",
]


def notebook_tool_schemas(
    tool_instances: dict[str, ToolBase[Any, Any]],
) -> dict[str, dict[str, Any]]:
    """JSON schema per backend tool, with dataclass defaults honoured."""
    converter = PythonTypeToOpenAPI(
        name_overrides={}, camel_case=False, honor_defaults=True
    )
    return {
        name: converter.convert(inst.Args, processed_classes={})
        for name, inst in tool_instances.items()
    }


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

    tool_definitions: list[Tool] = []
    for name, schema in notebook_tool_schemas(tool_instances).items():
        inst = tool_instances[name]
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
                "never reference those private names from another cell, and delete or update old "
                "definitions in the same atomic edit batch. "
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
        if name == ACTIVE_NOTEBOOKS_TOOL:
            # Discovery never needs a session id; the result is filtered to
            # the run's own sessions instead, and an empty list is valid.
            return await _invoke_backend_tool(
                tool_instances,
                name,
                arguments,
                session_authorizer=session_authorizer,
            )
        authorize_chat_runtime_session(name, arguments, session_authorizer)
        if name in tool_instances:
            return await _invoke_backend_tool(
                tool_instances,
                name,
                arguments,
                session_authorizer=session_authorizer,
            )

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
