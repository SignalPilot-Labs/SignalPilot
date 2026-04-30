"""Input validation helpers and constants for MCP tool calls."""

from __future__ import annotations

import re

# Input validation patterns
_CONN_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9_.]{1,256}$")
_MAX_SQL_LENGTH = 100_000


def _quote_table(name: str) -> str:
    """Quote a table name for SQL, handling schema-qualified names like main.track."""
    parts = name.split(".")
    return ".".join('"' + p.replace('"', '""') + '"' for p in parts)


def _validate_connection_name(name: str) -> str | None:
    """Validate connection name. Returns error message or None if valid."""
    if not name or not _CONN_NAME_RE.match(name):
        return f"Invalid connection name '{name}'. Use only letters, numbers, hyphens, underscores (1-64 chars)."
    return None


def _validate_sql(sql: str) -> str | None:
    """Validate SQL input length. Returns error message or None if valid."""
    if not sql or not sql.strip():
        return "SQL query cannot be empty."
    if len(sql) > _MAX_SQL_LENGTH:
        return f"SQL query exceeds maximum length ({_MAX_SQL_LENGTH} characters)."
    return None
