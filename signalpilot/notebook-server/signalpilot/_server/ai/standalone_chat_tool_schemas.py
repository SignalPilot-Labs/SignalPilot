"""MCP tool schemas exposed to the standalone chat agent."""

from mcp.types import Tool

DASHBOARD_AUTHORING_CONTRACT_VERSION = "2026-09-02.1"


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
            name="begin_dashboard_authoring",
            description=(
                "Begin or resume a private dashboard draft using the frozen Data Chat scope. Returns the bounded "
                "governed semantic projection, stable IDs, revisions, limits, and exact authoring contract version."
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
            name="set_dashboard_plan",
            description="Validate and atomically persist one typed dashboard plan before chart drafting.",
            inputSchema={
                "type": "object",
                "properties": {
                    "authoring_session_id": {"type": "string"},
                    "authoring_contract_version": {
                        "const": DASHBOARD_AUTHORING_CONTRACT_VERSION
                    },
                    "expected_plan_revision": {
                        "type": "integer",
                        "minimum": 0,
                    },
                    "plan": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": ["string", "null"]},
                            "timezone": {"type": "string"},
                            "filters": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                            "intents": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 30,
                                "items": {"type": "object"},
                            },
                        },
                        "required": ["name", "timezone", "intents"],
                    },
                },
                "required": [
                    "authoring_session_id",
                    "authoring_contract_version",
                    "expected_plan_revision",
                    "plan",
                ],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="upsert_dashboard_chart",
            description=(
                "Validate and persist exactly one complete chart for an accepted plan intent. A rejected chart returns "
                "safe structured issues and allowed semantic alternatives; retry that chart at most once."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "authoring_session_id": {"type": "string"},
                    "authoring_contract_version": {
                        "const": DASHBOARD_AUTHORING_CONTRACT_VERSION
                    },
                    "plan_revision": {"type": "integer", "minimum": 1},
                    "chart_id": {"type": "string"},
                    "chart": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "question": {"type": "string"},
                            "description": {"type": "string"},
                            "query": {"type": "object"},
                            "visualization": {"type": "object"},
                            "signalPilot": {"type": "object"},
                        },
                        "required": [
                            "id",
                            "title",
                            "question",
                            "description",
                            "query",
                            "visualization",
                            "signalPilot",
                        ],
                    },
                },
                "required": [
                    "authoring_session_id",
                    "authoring_contract_version",
                    "plan_revision",
                    "chart_id",
                    "chart",
                ],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="apply_dashboard_operations",
            description="Apply one bounded batch of stable-ID operations to the current validated unsaved draft.",
            inputSchema={
                "type": "object",
                "properties": {
                    "authoring_session_id": {"type": "string"},
                    "authoring_contract_version": {
                        "const": DASHBOARD_AUTHORING_CONTRACT_VERSION
                    },
                    "expected_draft_revision": {
                        "type": "integer",
                        "minimum": 1,
                    },
                    "operations": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 30,
                        "items": {"type": "object"},
                    },
                },
                "required": [
                    "authoring_session_id",
                    "authoring_contract_version",
                    "expected_draft_revision",
                    "operations",
                ],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="create_dashboard_preview",
            description=(
                "Deterministically finalize the complete validated private dashboard preview. Makes no model call and "
                "never applies, shares, publishes, or deploys a dashboard."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "authoring_session_id": {"type": "string"},
                    "authoring_contract_version": {
                        "const": DASHBOARD_AUTHORING_CONTRACT_VERSION
                    },
                    "plan_revision": {"type": "integer", "minimum": 0},
                    "expected_draft_revision": {
                        "type": "integer",
                        "minimum": 1,
                    },
                },
                "required": [
                    "authoring_session_id",
                    "authoring_contract_version",
                    "plan_revision",
                    "expected_draft_revision",
                ],
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
