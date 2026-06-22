"""SQL dialect mapping shared by REST and MCP query validation."""

from __future__ import annotations

SQLGLOT_DIALECTS: dict[str, str] = {
    "postgres": "postgres",
    "mysql": "mysql",
    "snowflake": "snowflake",
    "bigquery": "bigquery",
    "redshift": "redshift",
    "clickhouse": "clickhouse",
    "databricks": "databricks",
    "mssql": "tsql",
    "trino": "trino",
    "duckdb": "duckdb",
    "sqlite": "sqlite",
}


def sqlglot_dialect(db_type: object | None) -> str:
    """Return the sqlglot dialect for a SignalPilot db_type."""
    key = getattr(db_type, "value", db_type)
    return SQLGLOT_DIALECTS.get(str(key or "").lower(), "postgres")
