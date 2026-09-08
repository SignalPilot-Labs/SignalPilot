"""In-process MCP tools for one standalone data-chat run.

The tools cover notebooks, read-only dbt inspection, and the two dashboard
check tools (`dashboard_sample_data`, `dashboard_screenshot`). Files the agent
saves under the scratch directory are captured by the filesystem sweep, not by
a tool. A dashboard is a plain `artifacts/<name>.dashboard.json` file; the
check tools read it and never write into `artifacts/`.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from signalpilot._server.ai.dashboard import (
    dashboard_sample_data,
    dashboard_screenshot,
)
from signalpilot._server.ai.standalone_chat_dbt import run_inspect_dbt
from signalpilot._server.ai.standalone_chat_lifecycle import (
    StandaloneArtifactCollector,
    StandaloneNotebookLifecycle,
)
from signalpilot._server.ai.standalone_chat_tool_schemas import (
    standalone_chat_tools,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

__all__ = [
    "StandaloneArtifactCollector",
    "StandaloneNotebookLifecycle",
    "build_standalone_chat_mcp_server",
]

# Mirrors the start_analysis_notebook input schema pattern.
_NOTEBOOK_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")


def build_standalone_chat_mcp_server(
    collector: StandaloneArtifactCollector,
    *,
    project_directory: Path | None = None,
    scratch_directory: Path | None = None,
    notebook_mcp_app: Any | None = None,
    analysis_notebook_path: Path | None = None,
    event_sink: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    notebook_lifecycle: StandaloneNotebookLifecycle | None = None,
    runtime_redactions: tuple[str, ...] = (),
    notebook_starter: Callable[[Any, dict[str, Any]], list[Any]] | None = None,
    notebook_session_resolver: Callable[[str], Any] | None = None,
    notebook_seeder: Callable[[str], Path] | None = None,
) -> Any:
    """Build the isolated in-process tool server used by one run."""
    # The collector is the extension point for tool-recorded results. The
    # current tools record nothing; files reach the run via the sweep.
    del collector
    from claude_agent_sdk import McpSdkServerConfig
    from mcp.server import Server
    from mcp.types import ImageContent, TextContent, Tool

    server = Server("standalone-chat", version="1.0.0")
    tools = standalone_chat_tools(
        notebook_enabled=notebook_mcp_app is not None
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return tools

    async def start_analysis_notebook(
        arguments: dict[str, Any],
    ) -> list[TextContent]:
        if notebook_mcp_app is None or analysis_notebook_path is None:
            raise ValueError("The run-bound analysis notebook is unavailable")
        notebook_name = str(arguments.get("notebook") or "analysis")
        if not _NOTEBOOK_NAME_RE.fullmatch(notebook_name):
            raise ValueError("Invalid notebook name")
        if notebook_name == "analysis":
            target_path = analysis_notebook_path
        else:
            target_path = analysis_notebook_path.parent / f"{notebook_name}.py"
        running_session = (
            notebook_lifecycle.sessions.get(notebook_name)
            if notebook_lifecycle is not None
            else None
        )
        if running_session:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "session_id": running_session,
                            "status": "already_running",
                            "notebook_path": str(target_path),
                            "notebook": notebook_name,
                        }
                    ),
                )
            ]
        if notebook_name != "analysis" and not target_path.is_file():
            # Named notebooks seed lazily in the SAME scratch.
            if notebook_seeder is None:
                raise ValueError("Named notebooks are unavailable in this run")
            target_path = notebook_seeder(notebook_name)
        start_arguments = {"file_path": str(target_path), "auto_run": True}
        if notebook_starter is None:
            from signalpilot._server.ai.notebook_mcp import (
                _handle_start_notebook_session,
            )
            from signalpilot._server.ai.tools.base import ToolContext

            result = _handle_start_notebook_session(
                ToolContext(app=notebook_mcp_app), start_arguments
            )
        else:
            result = notebook_starter(notebook_mcp_app, start_arguments)
        if not result:
            raise ValueError("Notebook kernel did not start")
        raw = str(getattr(result[0], "text", ""))
        try:
            started = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Notebook kernel returned an invalid response"
            ) from exc
        session_id = str(started.get("session_id") or "")
        if not session_id or str(started.get("status") or "").startswith(
            "error"
        ):
            raise ValueError("Notebook kernel did not start")
        if notebook_lifecycle is not None:
            notebook_lifecycle.sessions[notebook_name] = session_id
        if notebook_session_resolver is not None:
            runtime_session = notebook_session_resolver(session_id)
        else:
            from signalpilot._server.ai.tools.base import ToolContext

            runtime_session = ToolContext(app=notebook_mcp_app).get_session(
                session_id
            )
        runtime_session._signalpilot_chat_runtime = True
        runtime_session._signalpilot_chat_redactions = runtime_redactions
        if event_sink is not None:
            await event_sink(
                "notebook_started",
                {"notebook": notebook_name, "session_id": session_id},
            )
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "session_id": session_id,
                        "status": "started",
                        "cell_ids": started.get("cell_ids") or [],
                        "notebook_path": str(target_path),
                        "notebook": notebook_name,
                    }
                ),
            )
        ]

    async def inspect_dbt(arguments: dict[str, Any]) -> list[TextContent]:
        if project_directory is None or scratch_directory is None:
            raise ValueError("The frozen dbt project is unavailable")
        inspected = await run_inspect_dbt(
            project_directory=project_directory,
            scratch_directory=scratch_directory,
            arguments=arguments,
        )
        return [TextContent(type="text", text=json.dumps(inspected))]

    async def sample_dashboard_data(
        arguments: dict[str, Any],
    ) -> list[TextContent | ImageContent]:
        if scratch_directory is None:
            return _dashboard_unavailable()
        return await dashboard_sample_data(
            scratch_directory=scratch_directory,
            path=str(arguments.get("path") or ""),
            chart_ids=list(arguments.get("chart_ids") or []),
            limit=int(arguments.get("limit") or 10),
        )

    async def screenshot_dashboard(
        arguments: dict[str, Any],
    ) -> list[TextContent | ImageContent]:
        if scratch_directory is None:
            return _dashboard_unavailable()
        raw_ids = arguments.get("chart_ids")
        return await dashboard_screenshot(
            scratch_directory=scratch_directory,
            path=str(arguments.get("path") or ""),
            chart_ids=list(raw_ids) if raw_ids else None,
            width=int(arguments.get("width") or 1280),
            theme=str(arguments.get("theme") or "light"),
        )

    handlers = {
        "start_analysis_notebook": start_analysis_notebook,
        "inspect_dbt": inspect_dbt,
        "dashboard_sample_data": sample_dashboard_data,
        "dashboard_screenshot": screenshot_dashboard,
    }

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any]
    ) -> list[TextContent | ImageContent]:
        try:
            handler = handlers.get(name)
            if handler is None:
                raise ValueError(f"Unknown tool: {name}")
            return await handler(arguments)
        except Exception as exc:
            # Raising lets the MCP protocol mark the tool result as an error.
            # Returning an error-shaped TextContent reports isError=false and
            # makes a failed call look successful to Data Chat.
            raise ValueError(str(exc)) from exc

    return McpSdkServerConfig(
        type="sdk", name="standalone-chat", instance=server
    )


def _dashboard_unavailable() -> list[Any]:
    from mcp.types import TextContent

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "error": "scratch_unavailable",
                    "message": (
                        "The scratch directory is unavailable in this run, "
                        "so dashboard files cannot be read."
                    ),
                }
            ),
        )
    ]
