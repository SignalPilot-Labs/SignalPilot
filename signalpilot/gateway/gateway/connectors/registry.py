"""Connector registry — maps DBType to connector class."""

from __future__ import annotations

from ..models import DBType
from .base import BaseConnector
from .postgres import PostgresConnector
from .mysql import MySQLConnector


_REGISTRY: dict[str, type[BaseConnector]] = {
    DBType.postgres: PostgresConnector,
    DBType.mysql: MySQLConnector,
}


# Metadata for the frontend: describes what each DB type needs
DB_TYPE_META: dict[str, dict] = {
    DBType.postgres: {
        "name": "PostgreSQL",
        "description": "The world's most advanced open source relational database",
        "default_port": 5432,
        "supports_ssl": True,
        "supports_schemas": True,
        "connection_fields": ["host", "port", "database", "username", "password"],
        "placeholder_host": "localhost or db.example.com",
        "placeholder_database": "my_database",
        "docs_url": "https://www.postgresql.org/docs/",
        "status": "available",
    },
    DBType.mysql: {
        "name": "MySQL",
        "description": "Popular open source relational database for web applications",
        "default_port": 3306,
        "supports_ssl": True,
        "supports_schemas": False,
        "connection_fields": ["host", "port", "database", "username", "password"],
        "placeholder_host": "localhost or db.example.com",
        "placeholder_database": "my_database",
        "docs_url": "https://dev.mysql.com/doc/",
        "status": "available",
    },
    DBType.duckdb: {
        "name": "DuckDB",
        "description": "Fast in-process analytical database — no server needed",
        "default_port": None,
        "supports_ssl": False,
        "supports_schemas": True,
        "connection_fields": ["database"],
        "placeholder_database": "/path/to/data.duckdb or :memory:",
        "docs_url": "https://duckdb.org/docs/",
        "status": "coming_soon",
    },
    DBType.snowflake: {
        "name": "Snowflake",
        "description": "Cloud-native data warehouse for enterprise analytics",
        "default_port": 443,
        "supports_ssl": True,
        "supports_schemas": True,
        "connection_fields": ["host", "database", "username", "password"],
        "placeholder_host": "account.snowflakecomputing.com",
        "placeholder_database": "MY_DATABASE",
        "docs_url": "https://docs.snowflake.com/",
        "status": "coming_soon",
    },
}


def get_connector(db_type: DBType) -> BaseConnector:
    """Create and return a new connector instance for the given database type."""
    cls = _REGISTRY.get(db_type)
    if cls is None:
        meta = DB_TYPE_META.get(db_type)
        if meta and meta.get("status") == "coming_soon":
            raise ValueError(
                f"{meta['name']} connector is coming soon. "
                f"Currently supported: {', '.join(DB_TYPE_META[k]['name'] for k in _REGISTRY)}"
            )
        raise ValueError(
            f"Unsupported database type: {db_type}. "
            f"Supported: {', '.join(DB_TYPE_META[k]['name'] for k in _REGISTRY)}"
        )
    return cls()


def list_supported_types() -> list[dict]:
    """Return metadata for all known database types (for frontend rendering)."""
    return [
        {"type": db_type, **meta}
        for db_type, meta in DB_TYPE_META.items()
    ]
