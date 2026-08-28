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
                "Start the run-bound analysis notebook only after plan_query selects notebook_sdk or dataset_ref. "
                "The notebook path is fixed by the runtime and cannot be supplied by the caller."
            ),
            inputSchema={
                "type": "object",
                "properties": {"plan_id": {"type": "string"}},
                "required": ["plan_id"],
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
            name="run_scratch_python",
            description=(
                "Run restricted, in-memory Python for calculations. Imports, files, networking, "
                "environment access, shell commands, and dynamic code are unavailable. Put the "
                "JSON-serializable output in a variable named result."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "data": {},
                },
                "required": ["source"],
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
