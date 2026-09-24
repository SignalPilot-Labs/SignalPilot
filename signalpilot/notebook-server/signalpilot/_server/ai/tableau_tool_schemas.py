"""MCP tool schemas for the Tableau tools of the standalone chat agent.

The tools are listed only when the org has an active Tableau integration
(``features.tableau`` on the execution request). Descriptions use
ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from mcp.types import Tool

_SKILL = "Load the signalpilot-dbt:tableau skill first."
_REF = {"type": "string", "minLength": 1, "maxLength": 300}


def _ref(description: str) -> dict[str, object]:
    return {**_REF, "description": description}


def _object(
    properties: dict[str, object], required: list[str]
) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def tableau_tools() -> list[Tool]:
    return [
        Tool(
            name="tableau_search",
            description=(
                f"{_SKILL} Search the Tableau site. Give a text query and an "
                "optional kind. The tool returns matching workbooks, views, "
                "data sources, or projects with id, name, project, and URL."
            ),
            inputSchema=_object(
                {
                    "query": {"type": "string", "maxLength": 300},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "all",
                            "workbook",
                            "view",
                            "datasource",
                            "project",
                        ],
                        "default": "all",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 25,
                    },
                },
                ["query"],
            ),
        ),
        Tool(
            name="tableau_get_workbook",
            description=(
                f"{_SKILL} Get the details of one workbook. Give the workbook "
                "id or exact name. The tool returns the project, the views, "
                "and the data connections of the workbook."
            ),
            inputSchema=_object(
                {"workbook": _ref("The workbook id or exact name.")},
                ["workbook"],
            ),
        ),
        Tool(
            name="tableau_download_workbook",
            description=(
                f"{_SKILL} Download one workbook as a .twb file into the "
                "scratch directory. Give the workbook id or exact name. The "
                "default file is tableau/<name>.twb. The tool returns the "
                "file path and a short summary of the dashboards, worksheets, "
                "data sources, and parameters. The tool does not return the "
                "XML. Use the skill scripts to read or edit the file."
            ),
            inputSchema=_object(
                {
                    "workbook": _ref("The workbook id or exact name."),
                    "path": {
                        "type": "string",
                        "maxLength": 300,
                        "description": (
                            "Optional .twb file path relative to the scratch "
                            "directory."
                        ),
                    },
                },
                ["workbook"],
            ),
        ),
        Tool(
            name="tableau_publish_workbook",
            description=(
                f"{_SKILL} Publish a .twb or .twbx file from the scratch "
                "directory to the Tableau site. Give the file path and the "
                "workbook name. The default is to overwrite a workbook with "
                "the same name. Give a SignalPilot connection name to embed "
                "its credentials in the matching data connections. The tool "
                "returns the workbook id, URL, views, the connections that "
                "got credentials, and the connections that did not."
            ),
            inputSchema=_object(
                {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 300,
                        "description": (
                            "The .twb or .twbx file path relative to the "
                            "scratch directory."
                        ),
                    },
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 255,
                    },
                    "project": {
                        "type": "string",
                        "maxLength": 255,
                        "description": (
                            "Project name or id. The default is the site "
                            "default project."
                        ),
                    },
                    "overwrite": {"type": "boolean", "default": True},
                    "connection": {
                        "type": "string",
                        "maxLength": 255,
                        "description": "SignalPilot connection name.",
                    },
                    "show_tabs": {"type": "boolean", "default": True},
                    "description": {"type": "string", "maxLength": 2000},
                },
                ["path", "name"],
            ),
        ),
        Tool(
            name="tableau_publish_datasource",
            description=(
                f"{_SKILL} Publish a live Tableau data source on a SignalPilot "
                "connection. Give a name, the connection name, and exactly "
                "one of table or sql. The gateway adds the warehouse "
                "credentials. Do not supply credentials. The tool returns the "
                "data source id, content URL, project, and URL. Workbooks "
                "refer to the data source by its content URL."
            ),
            inputSchema=_object(
                {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 255,
                    },
                    "connection": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 255,
                        "description": "SignalPilot connection name.",
                    },
                    "database": {"type": "string", "maxLength": 255},
                    "schema": {"type": "string", "maxLength": 255},
                    "table": {"type": "string", "maxLength": 255},
                    "sql": {"type": "string", "maxLength": 100_000},
                    "project": {"type": "string", "maxLength": 255},
                    "overwrite": {"type": "boolean", "default": True},
                    "description": {"type": "string", "maxLength": 2000},
                },
                ["name", "connection"],
            ),
        ),
        Tool(
            name="tableau_datasource_fields",
            description=(
                f"{_SKILL} List the fields of one published data source. "
                "Give the data source id, name, or content URL. The tool "
                "returns each field name, caption, data type, role, and "
                "default aggregation."
            ),
            inputSchema=_object(
                {
                    "datasource": _ref(
                        "The data source id, name, or content URL."
                    )
                },
                ["datasource"],
            ),
        ),
        Tool(
            name="tableau_query_datasource",
            description=(
                f"{_SKILL} Query one published data source with the VizQL "
                "Data Service. Give the data source and a list of field "
                "objects. Filters and a row limit are optional. The default "
                "limit is 500 rows and the maximum is 5000. The tool returns "
                "the rows and the row count. Use it to check the numbers that "
                "a workbook shows."
            ),
            inputSchema=_object(
                {
                    "datasource": _ref(
                        "The data source id, name, or content URL."
                    ),
                    "fields": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 50,
                        "items": {"type": "object"},
                        "description": (
                            "VizQL Data Service field objects, for example "
                            '{"fieldCaption": "Sales", "function": "SUM"}.'
                        ),
                    },
                    "filters": {
                        "type": "array",
                        "maxItems": 50,
                        "items": {"type": "object"},
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5000,
                        "default": 500,
                    },
                },
                ["datasource", "fields"],
            ),
        ),
        Tool(
            name="tableau_view_image",
            description=(
                f"{_SKILL} Render one view or dashboard on the Tableau server "
                "to a PNG image. Give the view id or name. A large dashboard "
                "can take two minutes. The tool saves the image as "
                "artifacts/tableau-<name>.png and returns the image. Look at "
                "the image to check the result."
            ),
            inputSchema=_object(
                {
                    "view": _ref("The view id or name."),
                    "name": {
                        "type": "string",
                        "maxLength": 100,
                        "description": "Optional short name for the saved file.",
                    },
                    "width": {
                        "type": "integer",
                        "minimum": 200,
                        "maximum": 4000,
                    },
                    "height": {
                        "type": "integer",
                        "minimum": 200,
                        "maximum": 4000,
                    },
                },
                ["view"],
            ),
        ),
        Tool(
            name="tableau_view_data",
            description=(
                f"{_SKILL} Get the summary data of one view as CSV text. Give "
                "the view id or name and an optional row limit. The default "
                "is 200 rows."
            ),
            inputSchema=_object(
                {
                    "view": _ref("The view id or name."),
                    "max_rows": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10_000,
                        "default": 200,
                    },
                },
                ["view"],
            ),
        ),
        Tool(
            name="tableau_connection_info",
            description=(
                f"{_SKILL} Get the Tableau connection values of one "
                "SignalPilot connection: the Tableau connection class, server, "
                "port, database, and user name. The tool never returns the "
                "password. Use these values to point a workbook at the "
                "connection."
            ),
            inputSchema=_object(
                {
                    "connection": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 255,
                        "description": "SignalPilot connection name.",
                    }
                },
                ["connection"],
            ),
        ),
    ]
