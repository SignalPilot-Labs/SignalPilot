"""MCP tool schemas exposed to the standalone chat agent."""

from mcp.types import Tool

DASHBOARD_AUTHORING_CONTRACT_VERSION = "2026-09-02.1"

_SCALAR_SCHEMA = {"type": ["string", "number", "boolean", "null"]}
_FIELD_TARGET_SCHEMA = {
    "type": "object",
    "properties": {
        "tableName": {"type": "string", "minLength": 1},
        "fieldId": {"type": "string", "minLength": 1},
        "isSqlColumn": {"type": ["boolean", "null"]},
    },
    "required": ["tableName", "fieldId"],
    "additionalProperties": False,
}
_FILTER_SETTINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "unitOfTime": {
            "type": ["string", "null"],
            "enum": ["days", "weeks", "months", "quarters", "years", None],
        },
        "completed": {"type": ["boolean", "null"]},
    },
    "additionalProperties": False,
}
_DASHBOARD_FILTER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "operator": {
            "type": "string",
            "enum": [
                "equals",
                "isNull",
                "notNull",
                "inBetween",
                "inThePast",
                "inTheCurrent",
                "inPeriodToDate",
            ],
        },
        "values": {"type": ["array", "null"], "items": _SCALAR_SCHEMA},
        "target": _FIELD_TARGET_SCHEMA,
        "tileTargets": {
            "type": ["object", "null"],
            "additionalProperties": {
                "oneOf": [_FIELD_TARGET_SCHEMA, {"const": False}],
            },
        },
        "label": {"type": ["string", "null"]},
        "singleValue": {"type": ["boolean", "null"]},
        "required": {"type": ["boolean", "null"]},
        "disabled": {"type": ["boolean", "null"]},
        "settings": {"oneOf": [_FILTER_SETTINGS_SCHEMA, {"type": "null"}]},
    },
    "required": ["id", "operator", "target"],
    "additionalProperties": False,
}
_LAYOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {"type": "integer", "minimum": 0, "maximum": 35},
        "y": {"type": "integer", "minimum": 0},
        "w": {"type": "integer", "minimum": 1, "maximum": 36},
        "h": {"type": "integer", "minimum": 1},
    },
    "required": ["x", "y", "w", "h"],
    "additionalProperties": False,
}
_DASHBOARD_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "chart_id": {"type": "string", "minLength": 1},
        "tile_id": {"type": "string", "minLength": 1},
        "label": {"type": "string", "minLength": 1},
        "question": {"type": "string", "minLength": 1},
        "description": {"type": "string", "minLength": 1},
        "required_concepts": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
        "explore_name": {"type": "string", "minLength": 1},
        "dimensions": {"type": "array", "items": {"type": "string"}},
        "metrics": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
        "section": {"type": "string", "minLength": 1},
        "order": {"type": "integer", "minimum": 0},
        "layout": _LAYOUT_SCHEMA,
        "visualization": {
            "type": "string",
            "enum": ["kpi", "table", "bar", "line", "area"],
        },
        "shared_filter_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "required": {"type": "boolean"},
    },
    "required": [
        "chart_id",
        "tile_id",
        "label",
        "question",
        "description",
        "required_concepts",
        "explore_name",
        "metrics",
        "section",
        "order",
        "layout",
        "visualization",
    ],
    "additionalProperties": False,
}
_SORT_SCHEMA = {
    "type": "object",
    "properties": {
        "fieldId": {"type": "string", "minLength": 1},
        "descending": {"type": "boolean"},
        "nullsFirst": {"type": ["boolean", "null"]},
    },
    "required": ["fieldId", "descending"],
    "additionalProperties": False,
}
_QUERY_FILTERS_SCHEMA = {
    "type": "object",
    "properties": {
        "dimensions": {"type": ["object", "null"]},
        "metrics": {"type": ["object", "null"]},
    },
    "additionalProperties": False,
}
_SEMANTIC_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"const": "semantic"},
        "exploreName": {"type": "string", "minLength": 1},
        "dimensions": {"type": "array", "items": {"type": "string"}},
        "metrics": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
        "filters": _QUERY_FILTERS_SCHEMA,
        "sorts": {"type": "array", "items": _SORT_SCHEMA},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10_000},
        "timezone": {"type": ["string", "null"]},
        "pivotDimensions": {
            "type": ["array", "null"],
            "maxItems": 1,
            "items": {"type": "string"},
        },
        "projectId": {"type": "string", "minLength": 1},
        "commitSha": {"type": "string", "minLength": 7},
    },
    "required": [
        "kind",
        "exploreName",
        "dimensions",
        "metrics",
        "filters",
        "sorts",
        "limit",
        "projectId",
        "commitSha",
    ],
    "additionalProperties": False,
}
_CUSTOM_FILTER_BINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "dashboardFieldId": {"type": "string", "minLength": 1},
        "outputColumn": {"type": "string", "minLength": 1},
        "logicalType": {
            "type": "string",
            "enum": ["string", "number", "boolean", "date", "timestamp"],
        },
    },
    "required": ["dashboardFieldId", "outputColumn", "logicalType"],
    "additionalProperties": False,
}
_SQL_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"const": "sql"},
        "connectionName": {"type": "string", "minLength": 1},
        "sqlTemplate": {"type": "string", "minLength": 1},
        "parameterDefinitions": {"type": "array", "items": {"type": "object"}},
        "outputBindings": {
            "type": "array",
            "items": _CUSTOM_FILTER_BINDING_SCHEMA,
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 10_000},
    },
    "required": [
        "kind",
        "connectionName",
        "sqlTemplate",
        "parameterDefinitions",
        "outputBindings",
        "limit",
    ],
    "additionalProperties": False,
}
_VISUALIZATION_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "type": {"const": "big_number"},
                "config": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "minLength": 1},
                        "format": {"type": ["string", "null"]},
                    },
                    "required": ["field"],
                    "additionalProperties": False,
                },
            },
            "required": ["type", "config"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "table"},
                "config": {
                    "type": "object",
                    "properties": {
                        "columns": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string"},
                        },
                        "groups": {
                            "type": ["array", "null"],
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["columns"],
                    "additionalProperties": False,
                },
            },
            "required": ["type", "config"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "cartesian"},
                "config": {
                    "type": "object",
                    "properties": {
                        "seriesType": {
                            "type": "string",
                            "enum": ["bar", "line", "area"],
                        },
                        "layout": {
                            "type": "object",
                            "properties": {
                                "xField": {"type": "string", "minLength": 1},
                                "yField": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {"type": "string"},
                                },
                                "stack": {"type": ["boolean", "null"]},
                            },
                            "required": ["xField", "yField"],
                            "additionalProperties": False,
                        },
                    },
                    "required": ["seriesType", "layout"],
                    "additionalProperties": False,
                },
            },
            "required": ["type", "config"],
            "additionalProperties": False,
        },
    ]
}
_CHART_SIGNALPILOT_SCHEMA = {
    "type": "object",
    "properties": {
        "crossFilter": {"type": "boolean"},
        "drillDimensions": {
            "type": ["array", "null"],
            "items": {"type": "string"},
        },
        "tableGroups": {
            "type": ["array", "null"],
            "items": {"type": "string"},
        },
        "customFilterBindings": {
            "type": ["array", "null"],
            "items": _CUSTOM_FILTER_BINDING_SCHEMA,
        },
        "provenanceRef": {"type": "string", "minLength": 1},
    },
    "required": ["crossFilter", "provenanceRef"],
    "additionalProperties": False,
}
_CHART_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "question": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "query": {"oneOf": [_SEMANTIC_QUERY_SCHEMA, _SQL_QUERY_SCHEMA]},
        "visualization": _VISUALIZATION_SCHEMA,
        "signalPilot": _CHART_SIGNALPILOT_SCHEMA,
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
    "additionalProperties": False,
}
_TILE_SCHEMA = {
    "type": "object",
    "properties": {
        "uuid": {"type": "string", "minLength": 1},
        "tileSlug": {"type": "string", "minLength": 1},
        "type": {"const": "saved_chart"},
        "x": {"type": "integer", "minimum": 0, "maximum": 35},
        "y": {"type": "integer", "minimum": 0},
        "h": {"type": "integer", "minimum": 1},
        "w": {"type": "integer", "minimum": 1, "maximum": 36},
        "properties": {
            "type": "object",
            "properties": {
                "title": {"type": ["string", "null"]},
                "hideTitle": {"type": ["boolean", "null"]},
                "chartName": {"type": ["string", "null"]},
                "chartSlug": {"type": "string", "minLength": 1},
                "sectionTitle": {"type": ["string", "null"]},
            },
            "required": ["chartSlug"],
            "additionalProperties": False,
        },
        "chartId": {"type": "string", "minLength": 1},
    },
    "required": [
        "uuid",
        "tileSlug",
        "type",
        "x",
        "y",
        "h",
        "w",
        "properties",
        "chartId",
    ],
    "additionalProperties": False,
}
_DASHBOARD_OPERATION_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "operation": {"const": "rename_dashboard"},
                "name": {"type": "string", "minLength": 1},
            },
            "required": ["operation", "name"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "operation": {"const": "add_chart"},
                "chart": _CHART_SCHEMA,
                "tile": _TILE_SCHEMA,
            },
            "required": ["operation", "chart", "tile"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "operation": {"const": "remove_chart"},
                "chart_id": {"type": "string", "minLength": 1},
            },
            "required": ["operation", "chart_id"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "operation": {"const": "replace_metric"},
                "chart_id": {"type": "string", "minLength": 1},
                "old_metric": {"type": "string", "minLength": 1},
                "new_metric": {"type": "string", "minLength": 1},
            },
            "required": ["operation", "chart_id", "old_metric", "new_metric"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "operation": {"enum": ["add_dimension", "remove_dimension"]},
                "chart_id": {"type": "string", "minLength": 1},
                "dimension": {"type": "string", "minLength": 1},
            },
            "required": ["operation", "chart_id", "dimension"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "operation": {"const": "add_filter_control"},
                "filter": _DASHBOARD_FILTER_SCHEMA,
            },
            "required": ["operation", "filter"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "operation": {"const": "change_visualization"},
                "chart_id": {"type": "string", "minLength": 1},
                "visualization": {
                    "enum": ["kpi", "table", "bar", "line", "area"]
                },
            },
            "required": ["operation", "chart_id", "visualization"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "operation": {"const": "move_chart"},
                "tile_uuid": {"type": "string", "minLength": 1},
                "x": {"type": "integer", "minimum": 0, "maximum": 35},
                "y": {"type": "integer", "minimum": 0},
            },
            "required": ["operation", "tile_uuid", "x", "y"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "operation": {"const": "resize_chart"},
                "tile_uuid": {"type": "string", "minLength": 1},
                "w": {"type": "integer", "minimum": 1, "maximum": 36},
                "h": {"type": "integer", "minimum": 1},
            },
            "required": ["operation", "tile_uuid", "w", "h"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "operation": {"const": "describe_chart"},
                "chart_id": {"type": "string", "minLength": 1},
                "description": {"type": "string", "minLength": 1},
            },
            "required": ["operation", "chart_id", "description"],
            "additionalProperties": False,
        },
    ]
}


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
                                "items": _DASHBOARD_FILTER_SCHEMA,
                            },
                            "intents": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 30,
                                "items": _DASHBOARD_INTENT_SCHEMA,
                            },
                        },
                        "required": ["name", "timezone", "intents"],
                        "additionalProperties": False,
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
                    "chart": _CHART_SCHEMA,
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
                        "items": _DASHBOARD_OPERATION_SCHEMA,
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
    ]
    if not notebook_enabled:
        tools = [
            tool for tool in tools if tool.name != "start_analysis_notebook"
        ]

    return tools
