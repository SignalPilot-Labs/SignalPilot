"""MCP tool schemas exposed to the standalone chat agent."""

from mcp.types import Tool


def standalone_chat_tools(*, notebook_enabled: bool) -> list[Tool]:
    tools = [
        Tool(
            name="start_analysis_notebook",
            description=(
                "Start the run-bound analysis notebook whenever notebook work is useful. "
                "Starting a notebook does not execute a database query; each database query must still be planned separately. "
                "The notebook path is fixed by the runtime and cannot be supplied by the caller. "
                "Pass the optional notebook name to start a separate scratch or report notebook; "
                "the default is the analysis notebook."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "notebook": {
                        "type": "string",
                        "pattern": "^[a-z][a-z0-9_-]{0,40}$",
                    }
                },
                "additionalProperties": False,
            },
        ),
        Tool(
            name="inspect_dbt",
            description=(
                "Inspect the frozen dbt project with a read-only command. Only dbt parse, ls, and compile are available."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "enum": ["parse", "ls", "compile"],
                    },
                    "select": {"type": ["string", "null"], "maxLength": 500},
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="create_dashboard_preview",
            description=(
                "Create a private governed SignalPilot dashboard preview from the user's complete dashboard request. "
                "The project, branch, connection, and commit are fixed by the chat run. The user must review and "
                "explicitly Apply the returned preview; this tool never saves a dashboard automatically."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "request": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 50_000,
                    },
                    "timezone": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 100,
                        "default": "UTC",
                    },
                    "authoring_session_id": {
                        "type": ["string", "null"],
                        "description": "The active dashboard_authoring session from warm context when refining an existing preview.",
                    },
                },
                "required": ["request"],
                "additionalProperties": False,
            },
        ),
    ]
    if not notebook_enabled:
        tools = [
            tool for tool in tools if tool.name != "start_analysis_notebook"
        ]

    return tools
