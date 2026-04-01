"""Connector registry — maps DBType to connector class."""

from __future__ import annotations

from ..models import DBType
from .base import BaseConnector
from .duckdb import DuckDBConnector
from .postgres import PostgresConnector
from .sqlite import SQLiteConnector


_REGISTRY: dict[str, type[BaseConnector]] = {
    DBType.postgres: PostgresConnector,
    DBType.duckdb: DuckDBConnector,
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
