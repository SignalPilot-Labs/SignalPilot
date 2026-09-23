"""SQL dialect mapping shared by REST and MCP query validation."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_FALLBACK_DIALECT = "postgres"

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
    "xata": "postgres",
}


def sqlglot_dialect(db_type: object | None) -> str:
    """Return the sqlglot dialect for a SignalPilot db_type.

    Unknown or empty db types fall back to postgres and log a warning, so a
    silent grammar mismatch (T-SQL parsed as Postgres) is visible in the logs.
    """
    key = str(getattr(db_type, "value", db_type) or "").lower()
    dialect = SQLGLOT_DIALECTS.get(key)
    if dialect is None:
        logger.warning(
            "No sqlglot dialect mapped for db_type %r; falling back to %s",
            key or None,
            _FALLBACK_DIALECT,
        )
        return _FALLBACK_DIALECT
    return dialect
