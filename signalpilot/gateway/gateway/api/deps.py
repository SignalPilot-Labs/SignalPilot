"""Shared dependencies for all API routers.

Centralizes repeated patterns:
- Schema fetch-or-cache boilerplate (was duplicated 19x in main.py)
- Connection lookup with 404
- Error sanitization
- Schema filtering
- Sandbox client management
- Shared constants
"""

from __future__ import annotations

import asyncio
import fnmatch
import re
from typing import Annotated, Any

from fastapi import HTTPException, Path

from ..connectors.pool_manager import pool_manager
from ..connectors.schema_cache import schema_cache
from ..errors import query_error_hint
from ..sandbox_client import SandboxClient
from ..store import (
    get_connection,
    get_connection_string,
    get_credential_extras,
    apply_endorsement_filter,
    load_settings,
)

# ─── SQLglot dialect mapping ─────────────────────────────────────────────────

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


# ─── Error sanitization ──────────────────────────────────────────────────────

_SENSITIVE_PATTERNS = [
    re.compile(r"postgresql://[^\s]+", re.IGNORECASE),
    re.compile(r"mysql://[^\s]+", re.IGNORECASE),
    re.compile(r"redshift://[^\s]+", re.IGNORECASE),
    re.compile(r"clickhouse://[^\s]+", re.IGNORECASE),
    re.compile(r"snowflake://[^\s]+", re.IGNORECASE),
    re.compile(r"databricks://[^\s]+", re.IGNORECASE),
    re.compile(r"password[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"host=\S+", re.IGNORECASE),
    re.compile(r"access_token[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"private_key[=:]\s*\S+", re.IGNORECASE),
]


def sanitize_db_error(error: str, db_type: str | None = None) -> str:
    """Remove connection strings, passwords, and host info from error messages.

    Also appends DB-specific troubleshooting hints for common errors.
    """
    sanitized = error
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    if len(sanitized) > 500:
        sanitized = sanitized[:500] + "..."

    err_lower = sanitized.lower()
    hints: list[str] = []

    if "connection refused" in err_lower or "could not connect" in err_lower:
        hints.append("Check that the database server is running and the host/port are correct")
        if db_type in ("postgres", "mysql", "redshift"):
            hints.append("Verify firewall rules allow connections from this server's IP")
        if db_type == "clickhouse":
            hints.append("ClickHouse default port: 9000 (native) or 8123 (HTTP). Verify the correct protocol is selected")
        if db_type == "mssql":
            hints.append("SQL Server default port is 1433. If using a named instance, check the port in SQL Server Configuration Manager")
    elif "authentication" in err_lower or "password" in err_lower or "access denied" in err_lower:
        hints.append("Verify username and password are correct")
        if db_type == "snowflake":
            hints.append("For Snowflake, ensure the account identifier is correct (e.g., xy12345.us-east-1)")
            if "mfa" in err_lower or "duo" in err_lower:
                hints.append("MFA is blocking — use key-pair or OAuth auth method instead of password")
        elif db_type == "databricks":
            hints.append("For Databricks, check that the personal access token (PAT) is valid and not expired")
        elif db_type == "bigquery":
            hints.append("Verify the service account JSON is valid and has BigQuery access roles")
        elif db_type == "mysql":
            hints.append("MySQL may require 'mysql_native_password' plugin. Check with: SELECT plugin FROM mysql.user WHERE User='...'")
        elif db_type == "trino":
            hints.append("If using JWT/certificate auth, verify the token/cert has not expired")
    elif "timeout" in err_lower or "timed out" in err_lower:
        hints.append("Database is unreachable — check network connectivity")
        hints.append("If behind a VPN, ensure VPN is connected. If behind a firewall, add this server's IP to the allowlist")
        if db_type == "snowflake":
            hints.append("Snowflake account may be in a different region — check the account URL")
        if db_type == "databricks":
            hints.append("Databricks workspace may be suspended — check the workspace status")
    elif "ssl" in err_lower or "certificate" in err_lower or "tls" in err_lower:
        hints.append("SSL/TLS connection failed — check SSL configuration")
        hints.append("Try enabling SSL in advanced options with the appropriate CA certificate")
        if db_type == "postgres":
            hints.append("Set ssl_mode to 'require' or 'verify-ca'. For RDS, use the AWS RDS CA bundle")
        elif db_type == "mysql":
            hints.append("Set ssl_mode to 'REQUIRED'. For RDS, download the RDS CA bundle")
        elif db_type == "clickhouse":
            hints.append("For ClickHouse Cloud, use clickhouse+https:// scheme with SSL enabled")
    elif "does not exist" in err_lower or "not found" in err_lower:
        if "database" in err_lower:
            hints.append("Database name not found — verify the database exists and the user has access")
        elif "warehouse" in err_lower:
            hints.append("Warehouse not found — verify warehouse name and that it is running")
        elif "schema" in err_lower or "catalog" in err_lower:
            hints.append("Schema/catalog not found — verify the name and permissions")
        elif "table" in err_lower:
            hints.append("Table not found — check schema filters and verify the table exists")
    elif "permission denied" in err_lower or "insufficient privileges" in err_lower:
        hints.append("User lacks required permissions. Grant at minimum SELECT access to the target schema")
        if db_type == "bigquery":
            hints.append("Assign 'BigQuery Data Viewer' and 'BigQuery Job User' roles to the service account")
        elif db_type == "snowflake":
            hints.append("Grant USAGE on warehouse and database, plus SELECT on schema tables")
    elif "too many" in err_lower and ("connection" in err_lower or "client" in err_lower):
        hints.append("Connection limit reached — reduce pool_max_size or close idle connections")
        if db_type == "postgres":
            hints.append("Check max_connections in postgresql.conf. Consider using PgBouncer for connection pooling")

    if hints:
        sanitized += " | Hint: " + "; ".join(hints)
    return sanitized


# ─── Connection name validation ──────────────────────────────────────────────

_CONN_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_connection_name(name: str) -> str:
    """Validate a connection name from URL path parameters.

    Prevents path traversal and injection by enforcing the same pattern
    as ConnectionCreate.name (alphanumeric, hyphens, underscores only).
    """
    if not name or len(name) > 64 or not _CONN_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="Invalid connection name. Use 1-64 characters: letters, digits, hyphens, underscores.",
        )
    return name


# FastAPI dependency for validated connection name path parameters
ConnectionName = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]

# FastAPI dependency for validated UUID path parameters (tunnel IDs, sandbox IDs)
ResourceID = Annotated[str, Path(min_length=36, max_length=36, pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")]


# ─── Connection lookup ────────────────────────────────────────────────────────

def require_connection(name: str):
    """Look up connection by name, raise 404 if not found."""
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    return info


# ─── Schema fetch-or-cache (was duplicated 19x) ──────────────────────────────

async def get_or_fetch_schema(name: str, info=None, force_refresh: bool = False) -> dict[str, Any]:
    """Fetch schema from cache or database. Raises HTTPException on failure.

    This replaces the 19 identical copies of the schema fetch + filter boilerplate
    that existed throughout main.py.
    """
    if info is None:
        info = require_connection(name)

    if not force_refresh:
        cached = schema_cache.get(name)
        if cached is not None:
            return cached

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    try:
        extras = get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            schema = await connector.get_schema()
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e), info.db_type))

    schema_cache.put(name, schema)
    return schema


def apply_filters(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Apply endorsement filter + schema include/exclude filters."""
    filtered = apply_endorsement_filter(name, schema)
    sf_include, sf_exclude = get_schema_filters(name)
    return apply_schema_filter(filtered, sf_include, sf_exclude)


async def get_filtered_schema(name: str, info=None, force_refresh: bool = False) -> dict[str, Any]:
    """Fetch schema and apply all filters. Single call replaces the entire boilerplate."""
    raw = await get_or_fetch_schema(name, info, force_refresh)
    return apply_filters(name, raw)


# ─── Schema filtering ────────────────────────────────────────────────────────

def apply_schema_filter(
    schema: dict[str, dict],
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> dict[str, dict]:
    """Filter schema tables by include/exclude schema name patterns."""
    if not include and not exclude:
        return schema
    filtered: dict[str, dict] = {}
    for key, table_data in schema.items():
        table_schema = table_data.get("schema", "")
        if include:
            if not any(fnmatch.fnmatch(table_schema.lower(), pat.lower()) for pat in include):
                continue
        if exclude:
            if any(fnmatch.fnmatch(table_schema.lower(), pat.lower()) for pat in exclude):
                continue
        filtered[key] = table_data
    return filtered


def get_schema_filters(name: str) -> tuple[list[str], list[str]]:
    """Get schema filter config for a connection."""
    conn = get_connection(name)
    if conn is None:
        return [], []
    include = getattr(conn, "schema_filter_include", []) or []
    exclude = getattr(conn, "schema_filter_exclude", []) or []
    return include, exclude


# ─── Sandbox client ───────────────────────────────────────────────────────────

_sandbox_client: SandboxClient | None = None


def get_sandbox_client() -> SandboxClient:
    global _sandbox_client
    if _sandbox_client is None:
        settings = load_settings()
        _sandbox_client = SandboxClient(
            base_url=settings.sandbox_manager_url,
            api_key=settings.sandbox_api_key,
        )
    return _sandbox_client


def reset_sandbox_client():
    global _sandbox_client
    if _sandbox_client is not None:
        asyncio.create_task(_sandbox_client.close())
    _sandbox_client = None
