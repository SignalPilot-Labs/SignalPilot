"""Connector registry — maps DBType to connector class."""

from __future__ import annotations

import os

from ..models import DBType
from .base import BaseConnector
from .bigquery import BigQueryConnector
from .clickhouse import ClickHouseConnector
from .databricks import DatabricksConnector
from .duckdb import DuckDBConnector
from .mssql import MSSQLConnector
from .mysql import MySQLConnector
from .postgres import PostgresConnector
from .redshift import RedshiftConnector
from .snowflake import SnowflakeConnector
from .sqlite import SQLiteConnector
from .trino import TrinoConnector

# Local mode: use sandboxed connectors for file-based DBs
_is_local = os.environ.get("SP_DEPLOYMENT_MODE", "local") != "cloud"
if _is_local:
    from .sandboxed_duckdb import SandboxedDuckDBConnector
    from .sandboxed_sqlite import SandboxedSQLiteConnector

    _DuckDB: type[BaseConnector] = SandboxedDuckDBConnector
    _SQLite: type[BaseConnector] = SandboxedSQLiteConnector
else:
    _DuckDB = DuckDBConnector
    _SQLite = SQLiteConnector


_REGISTRY: dict[str, type[BaseConnector]] = {
    DBType.postgres: PostgresConnector,
    DBType.duckdb: _DuckDB,
    DBType.mysql: MySQLConnector,
    DBType.snowflake: SnowflakeConnector,
    DBType.bigquery: BigQueryConnector,
    DBType.redshift: RedshiftConnector,
    DBType.clickhouse: ClickHouseConnector,
    DBType.databricks: DatabricksConnector,
    DBType.mssql: MSSQLConnector,
    DBType.trino: TrinoConnector,
    DBType.sqlite: _SQLite,
}


def get_connector(db_type: DBType | str) -> BaseConnector:
    """Get a new connector instance for the given database type."""
    cls = _REGISTRY.get(db_type)
    if cls is None:
        supported = [str(k) for k in _REGISTRY]
        raise ValueError(f"Unsupported database type: {db_type}. Supported: {supported}")
    return cls()


def get_sqlite_connector() -> SQLiteConnector:
    """Get a SQLite connector (used for benchmarking, not exposed via DBType enum)."""
    return SQLiteConnector()
