"""MCP tool schemas exposed to the standalone chat agent."""

from __future__ import annotations

from mcp.types import Tool

from signalpilot._server.ai.dashboard.schema import (
    CHART_ID_PATTERN,
    DASHBOARD_PATH_PATTERN,
)

_DASHBOARD_PATH_SCHEMA = {
    "type": "string",
    "pattern": DASHBOARD_PATH_PATTERN,
    "description": (
        "Dashboard file path relative to the scratch directory, for example "
        "artifacts/revenue.dashboard.json."
    ),
}
_CHART_ID_ITEMS_SCHEMA = {"type": "string", "pattern": CHART_ID_PATTERN}


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
            name="dashboard_sample_data",
            description=(
                "Check a dashboard file. Validates artifacts/<name>.dashboard.json "
                "against the dashboard schema, loads the datasets the requested "
                "charts use, applies filter defaults, sort, and limit, and returns "
                "the first rows with inferred column types and issue codes. Fix "
                "every issue before you call dashboard_screenshot."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": _DASHBOARD_PATH_SCHEMA,
                    "chart_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "items": _CHART_ID_ITEMS_SCHEMA,
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "default": 10,
                    },
                },
                "required": ["path", "chart_ids"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="dashboard_screenshot",
            description=(
                "Render a dashboard file to a PNG image and return it with a "
                "status JSON. Pass chart_ids to render a subset. Look at the "
                "image and fix layout or formatting problems in the file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": _DASHBOARD_PATH_SCHEMA,
                    "chart_ids": {
                        "type": ["array", "null"],
                        "minItems": 1,
                        "maxItems": 40,
                        "items": _CHART_ID_ITEMS_SCHEMA,
                    },
                    "width": {
                        "type": "integer",
                        "minimum": 640,
                        "maximum": 1920,
                        "default": 1280,
                    },
                    "theme": {
                        "type": "string",
                        "enum": ["light", "dark"],
                        "default": "light",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
    ]
    if not notebook_enabled:
        tools = [
            tool for tool in tools if tool.name != "start_analysis_notebook"
        ]

    return tools
