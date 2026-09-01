"""MCP tool schemas exposed to the standalone chat agent."""

from mcp.types import Tool


def standalone_chat_tools(*, notebook_enabled: bool) -> list[Tool]:
    common_properties = {
        "filename": {"type": "string"},
        "freshness_at": {"type": ["string", "null"]},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "exclusions": {"type": "array", "items": {"type": "string"}},
        "caveats": {"type": "array", "items": {"type": "string"}},
        "provenance": {"type": "object"},
        "parent_artifact_id": {"type": ["string", "null"]},
    }
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
        Tool(
            name="publish_table",
            description="Publish an immutable table snapshot attached to the answer.",
            inputSchema={
                "type": "object",
                "properties": {
                    **common_properties,
                    "result_id": {"type": "string"},
                    "columns": {"type": "array", "items": {"type": "object"}},
                    "rows": {"type": "array", "items": {"type": "object"}},
                    "column_descriptions": {"type": "object"},
                    "truncated": {"type": "boolean"},
                },
                "required": ["filename", "result_id"],
            },
        ),
        Tool(
            name="publish_chart",
            description=(
                "Publish a static chart using a Vega-Lite-compatible spec and the exact source-row snapshot."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **common_properties,
                    "result_id": {"type": "string"},
                    "spec": {"type": "object"},
                    "rows": {"type": "array", "items": {"type": "object"}},
                    "truncated": {"type": "boolean"},
                },
                "required": ["filename", "result_id", "spec"],
            },
        ),
        Tool(
            name="publish_report",
            description="Publish a self-contained static HTML/CSS report. JavaScript and remote resources are forbidden.",
            inputSchema={
                "type": "object",
                "properties": {
                    **common_properties,
                    "html": {"type": "string"},
                    "result_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "artifact_references": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["filename", "html"],
            },
        ),
        Tool(
            name="list_saved_report_catalog",
            description=(
                "List one 50-report page of compact saved-report semantic cards for this run's owner and project. "
                "Start without a cursor, then call every returned next_cursor before proposing a new report."
            ),
            inputSchema={
                "type": "object",
                "properties": {"cursor": {"type": ["string", "null"]}},
            },
        ),
        Tool(
            name="load_report_context",
            description=(
                "Load prompts, version lineage, output shape, governed SQL purposes, freshness, assumptions, "
                "and caveats for a report selected from the catalog. Historical SQL is context only."
            ),
            inputSchema={
                "type": "object",
                "properties": {"report_id": {"type": "string"}},
                "required": ["report_id"],
            },
        ),
        Tool(
            name="propose_report_action",
            description=(
                "Record the single catalog-backed report decision for this completed run. Use open for exact saved "
                "content, update for a semantically equivalent report, create when no catalog match exists, or "
                "no_suggestion when the artifact should not be promoted. Scan every catalog page first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "create",
                            "update",
                            "open",
                            "no_suggestion",
                        ],
                    },
                    "artifact_kind": {
                        "type": "string",
                        "enum": ["table", "chart", "report"],
                    },
                    "artifact_filename": {"type": "string"},
                    "title": {"type": "string", "maxLength": 200},
                    "reason": {"type": "string", "maxLength": 2000},
                    "existing_report_id": {"type": ["string", "null"]},
                },
                "required": [
                    "action",
                    "artifact_kind",
                    "artifact_filename",
                    "title",
                    "reason",
                ],
            },
        ),
    ]
    if not notebook_enabled:
        tools = [
            tool for tool in tools if tool.name != "start_analysis_notebook"
        ]

    return tools
