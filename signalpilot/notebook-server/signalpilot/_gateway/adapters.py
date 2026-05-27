"""Adapters to translate SignalPilot Gateway responses into sp-notebook data models."""
from __future__ import annotations

from typing import Any

from signalpilot._data.models import (
    DataSourceConnection,
    DataTable,
    DataTableColumn,
    DataType,
    Database,
    Schema,
)


_TYPE_MAP: dict[str, DataType] = {
    "bigint": "integer",
    "int": "integer",
    "int4": "integer",
    "int8": "integer",
    "integer": "integer",
    "smallint": "integer",
    "tinyint": "integer",
    "serial": "integer",
    "bigserial": "integer",
    "float": "number",
    "float4": "number",
    "float8": "number",
    "double": "number",
    "double precision": "number",
    "real": "number",
    "numeric": "number",
    "decimal": "number",
    "number": "number",
    "money": "number",
    "bool": "boolean",
    "boolean": "boolean",
    "varchar": "string",
    "char": "string",
    "text": "string",
    "string": "string",
    "character varying": "string",
    "character": "string",
    "nvarchar": "string",
    "nchar": "string",
    "uuid": "string",
    "json": "string",
    "jsonb": "string",
    "xml": "string",
    "date": "date",
    "datetime": "datetime",
    "datetime2": "datetime",
    "timestamp": "datetime",
    "timestamp without time zone": "datetime",
    "timestamp with time zone": "datetime",
    "timestamptz": "datetime",
    "time": "time",
    "time without time zone": "time",
    "time with time zone": "time",
    "timetz": "time",
    "interval": "string",
}

_DIALECT_MAP: dict[str, str] = {
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "mysql": "mysql",
    "sqlite": "sqlite",
    "duckdb": "duckdb",
    "snowflake": "snowflake",
    "bigquery": "bigquery",
    "redshift": "redshift",
    "clickhouse": "clickhouse",
    "databricks": "databricks",
    "mssql": "mssql",
    "trino": "trino",
}


def _map_column_type(raw_type: str) -> DataType:
    normalized = raw_type.lower().strip()
    if normalized in _TYPE_MAP:
        return _TYPE_MAP[normalized]
    for key, val in _TYPE_MAP.items():
        if key in normalized:
            return val
    return "unknown"


def gateway_column_to_datatable_column(col: dict[str, Any]) -> DataTableColumn:
    raw_type = col.get("type", "unknown")
    return DataTableColumn(
        name=col.get("name", ""),
        type=_map_column_type(raw_type),
        external_type=raw_type,
        sample_values=[],
    )


def _parse_columns_from_ddl(ddl: str) -> list[dict[str, Any]]:
    """Extract column info from a CREATE TABLE DDL string when compact mode is used."""
    import re

    columns: list[dict[str, Any]] = []
    match = re.search(r"\(\s*(.+)\s*\)", ddl, re.DOTALL)
    if not match:
        return columns
    body = match.group(1)
    for part in body.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if len(tokens) >= 2:
            col_name = tokens[0].strip('"').strip("`")
            col_type = tokens[1]
            columns.append({
                "name": col_name,
                "type": col_type,
                "nullable": "NOT NULL" not in part.upper(),
                "primary_key": "PRIMARY KEY" in part.upper(),
            })
    return columns


def gateway_schema_to_database(
    schema_response: dict[str, Any],
    connection: dict[str, Any],
) -> Database:
    """Transform gateway GET /api/connections/{name}/schema into a notebook Database.

    Gateway response format:
    {
      "connection_name": "...",
      "db_type": "...",
      "tables": {
        "schema.table_name": {
          "schema": "main",
          "name": "table_name",
          "columns": [...],  # non-compact mode
          "ddl": "CREATE TABLE ...",  # compact mode
          "row_count": 123,
        }
      }
    }
    """
    db_type = connection.get("db_type", schema_response.get("db_type", "unknown"))
    dialect = _DIALECT_MAP.get(db_type, db_type)
    conn_name = connection.get("name", schema_response.get("connection_name", ""))
    db_name = connection.get("database", conn_name)

    tables_dict = schema_response.get("tables", schema_response)
    if not isinstance(tables_dict, dict):
        tables_dict = {}

    schemas_map: dict[str, list[DataTable]] = {}

    for qualified_name, table_info in tables_dict.items():
        if not isinstance(table_info, dict):
            continue
        schema_name = table_info.get("schema", "public")
        table_name = table_info.get("name", qualified_name)

        columns_raw = table_info.get("columns", [])
        if not columns_raw and "ddl" in table_info:
            columns_raw = _parse_columns_from_ddl(table_info["ddl"])
        columns = [gateway_column_to_datatable_column(c) for c in columns_raw]

        pk_cols = [
            c.get("name", "") for c in columns_raw if c.get("primary_key")
        ]

        dt = DataTable(
            source_type="connection",
            source=dialect,
            name=table_name,
            num_rows=table_info.get("row_count"),
            num_columns=len(columns),
            variable_name=None,
            columns=columns,
            engine=conn_name,
            type="view" if table_info.get("is_view") else "table",
            primary_keys=pk_cols or None,
            indexes=None,
        )

        schemas_map.setdefault(schema_name, []).append(dt)

    schemas = [
        Schema(name=s_name, tables=tables)
        for s_name, tables in sorted(schemas_map.items())
    ]

    return Database(
        name=db_name,
        dialect=dialect,
        schemas=schemas,
        engine=conn_name,
    )


def gateway_connection_to_datasource(
    connection: dict[str, Any],
    schema_response: dict[str, Any] | None = None,
) -> DataSourceConnection:
    """Transform a single gateway connection into a notebook DataSourceConnection.

    If schema_response is provided, builds the full database tree.
    Otherwise, creates an empty shell that will be lazily loaded.
    """
    db_type = connection.get("db_type", "unknown")
    dialect = _DIALECT_MAP.get(db_type, db_type)
    conn_name = connection.get("name", "")
    display = f"{db_type.title()} ({conn_name})"

    databases: list[Database] = []
    if schema_response:
        databases = [gateway_schema_to_database(schema_response, connection)]
    else:
        db_name = connection.get("database", conn_name)
        databases = [
            Database(
                name=db_name,
                dialect=dialect,
                schemas=[],
                engine=conn_name,
            )
        ]

    return DataSourceConnection(
        source=db_type,
        dialect=dialect,
        name=conn_name,
        display_name=display,
        databases=databases,
        default_database=connection.get("database"),
        default_schema=connection.get("schema_name"),
    )


def gateway_connections_to_datasources(
    connections: list[dict[str, Any]],
) -> list[DataSourceConnection]:
    """Transform a list of gateway connections into notebook DataSourceConnections."""
    return [gateway_connection_to_datasource(c) for c in connections]
