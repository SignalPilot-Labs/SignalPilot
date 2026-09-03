"""Connector registry: maps DBType to connector class."""

from __future__ import annotations

import os
from dataclasses import dataclass

from ..dashboard.dialects import (
    BIGQUERY_DIALECT,
    CLICKHOUSE_DIALECT,
    DATABRICKS_DIALECT,
    DUCKDB_DIALECT,
    MSSQL_DIALECT,
    MYSQL_DIALECT,
    POSTGRES_DIALECT,
    REDSHIFT_DIALECT,
    SNOWFLAKE_DIALECT,
    SQLITE_DIALECT,
    TRINO_DIALECT,
    XATA_DIALECT,
    DashboardDialect,
)
from ..models import DBType
from .base import BaseConnector
from .drivers.bigquery import BigQueryConnector
from .drivers.clickhouse import ClickHouseConnector
from .drivers.databricks import DatabricksConnector
from .drivers.duckdb import DuckDBConnector
from .drivers.mssql import MSSQLConnector
from .drivers.mysql import MySQLConnector
from .drivers.postgres import PostgresConnector
from .drivers.redshift import RedshiftConnector
from .drivers.snowflake import SnowflakeConnector
from .drivers.sqlite import SQLiteConnector
from .drivers.trino import TrinoConnector
from .drivers.xata import XataConnector

# Use sandboxed connectors only when running inside Docker with the sandbox service.
# SP_SANDBOX_ENABLED is the only switch: false (or unset) skips sandboxing so
# file-based DBs open directly.
_is_local = os.environ.get("SP_DEPLOYMENT_MODE", "local") != "cloud"
_sandbox_enabled = os.environ.get("SP_SANDBOX_ENABLED", "false").lower() == "true"
if _is_local and _sandbox_enabled:
    from .drivers.sandboxed_duckdb import SandboxedDuckDBConnector
    from .drivers.sandboxed_sqlite import SandboxedSQLiteConnector

    _DuckDB: type[BaseConnector] = SandboxedDuckDBConnector
    _SQLite: type[BaseConnector] = SandboxedSQLiteConnector
else:
    _DuckDB = DuckDBConnector
    _SQLite = SQLiteConnector


@dataclass(frozen=True)
class ConnectorRegistration:
    connector_class: type[BaseConnector]
    dashboard_dialect: DashboardDialect


_REGISTRATIONS: dict[str, ConnectorRegistration] = {
    DBType.postgres.value: ConnectorRegistration(PostgresConnector, POSTGRES_DIALECT),
    DBType.duckdb.value: ConnectorRegistration(_DuckDB, DUCKDB_DIALECT),
    DBType.mysql.value: ConnectorRegistration(MySQLConnector, MYSQL_DIALECT),
    DBType.snowflake.value: ConnectorRegistration(SnowflakeConnector, SNOWFLAKE_DIALECT),
    DBType.bigquery.value: ConnectorRegistration(BigQueryConnector, BIGQUERY_DIALECT),
    DBType.redshift.value: ConnectorRegistration(RedshiftConnector, REDSHIFT_DIALECT),
    DBType.clickhouse.value: ConnectorRegistration(ClickHouseConnector, CLICKHOUSE_DIALECT),
    DBType.databricks.value: ConnectorRegistration(DatabricksConnector, DATABRICKS_DIALECT),
    DBType.mssql.value: ConnectorRegistration(MSSQLConnector, MSSQL_DIALECT),
    DBType.trino.value: ConnectorRegistration(TrinoConnector, TRINO_DIALECT),
    DBType.sqlite.value: ConnectorRegistration(_SQLite, SQLITE_DIALECT),
    DBType.xata.value: ConnectorRegistration(XataConnector, XATA_DIALECT),
}

# Kept as the connector-class projection for compatibility with connector tests
# and callers that introspect the general registry.
_REGISTRY: dict[str, type[BaseConnector]] = {
    db_type: registration.connector_class for db_type, registration in _REGISTRATIONS.items()
}


def _db_type_key(db_type: DBType | str) -> str:
    return db_type.value if isinstance(db_type, DBType) else str(db_type).lower()


def get_connector_registration(db_type: DBType | str) -> ConnectorRegistration:
    key = _db_type_key(db_type)
    registration = _REGISTRATIONS.get(key)
    if registration is None:
        raise ValueError(f"Unsupported database type: {key}")
    return registration


def get_dashboard_dialect(db_type: DBType | str) -> DashboardDialect:
    return get_connector_registration(db_type).dashboard_dialect


def registered_connector_types() -> tuple[str, ...]:
    return tuple(_REGISTRATIONS)


def get_connector(db_type: DBType | str) -> BaseConnector:
    """Get a new connector instance for the given database type."""
    return get_connector_registration(db_type).connector_class()


def get_sqlite_connector() -> SQLiteConnector:
    """Get a SQLite connector (used for benchmarking, not exposed via DBType enum)."""
    return SQLiteConnector()
