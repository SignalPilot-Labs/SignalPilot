"""Shared dependencies for all API routers.

Centralizes repeated patterns:
- Store dependency (DB-backed, user-scoped)
- Schema fetch-or-cache boilerplate
- Connection lookup with 404
- Error sanitization
- Schema filtering
- Sandbox client management
"""

from __future__ import annotations

import asyncio
import fnmatch
import re
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import UserID, OrgID, DBSession
from ..connectors.pool_manager import pool_manager
from ..connectors.schema_cache import schema_cache
from ..db.engine import get_db
from ..errors import query_error_hint
from ..sandbox_client import SandboxClient
from ..store import Store

# ─── Store dependency ────────────────────────────────────────────────────────

async def get_store(
    org_id: OrgID,
    user_id: UserID,
    db: DBSession,
) -> Store:
    """FastAPI dependency: yields a Store scoped to the current org."""
    return Store(db, org_id=org_id, user_id=user_id)

StoreD = Annotated[Store, Depends(get_store)]

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
    elif "authentication" in err_lower or "password" in err_lower or "access denied" in err_lower:
        hints.append("Verify username and password are correct")
    elif "timeout" in err_lower or "timed out" in err_lower:
        hints.append("Database is unreachable — check network connectivity")
    elif "ssl" in err_lower or "certificate" in err_lower or "tls" in err_lower:
        hints.append("SSL/TLS connection failed — check SSL configuration")
    elif "permission denied" in err_lower or "insufficient privileges" in err_lower:
        hints.append("User lacks required permissions")

    if hints:
        sanitized += " | Hint: " + "; ".join(hints)
    return sanitized


# ─── Connection lookup ────────────────────────────────────────────────────────

async def require_connection(store: Store, name: str):
    """Look up connection by name, raise 404 if not found."""
    info = await store.get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    return info


# ─── Schema fetch-or-cache ───────────────────────────────────────────────────

async def get_or_fetch_schema(
    store: Store, name: str, info=None, force_refresh: bool = False
) -> dict[str, Any]:
    if info is None:
        info = await require_connection(store, name)

    if not force_refresh:
        cached = schema_cache.get(name)
        if cached is not None:
            return cached

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    try:
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            schema = await connector.get_schema()
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e), info.db_type))

    schema_cache.put(name, schema)
    return schema


async def apply_filters(store: Store, name: str, schema: dict[str, Any]) -> dict[str, Any]:
    filtered = await store.apply_endorsement_filter(name, schema)
    sf_include, sf_exclude = await get_schema_filters(store, name)
    return apply_schema_filter(filtered, sf_include, sf_exclude)


async def get_filtered_schema(
    store: Store, name: str, info=None, force_refresh: bool = False
) -> dict[str, Any]:
    raw = await get_or_fetch_schema(store, name, info, force_refresh)
    return await apply_filters(store, name, raw)


# ─── Schema filtering ────────────────────────────────────────────────────────

def apply_schema_filter(
    schema: dict[str, dict],
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> dict[str, dict]:
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


async def get_schema_filters(store: Store, name: str) -> tuple[list[str], list[str]]:
    conn = await store.get_connection(name)
    if conn is None:
        return [], []
    include = getattr(conn, "schema_filter_include", []) or []
    exclude = getattr(conn, "schema_filter_exclude", []) or []
    return include, exclude


# ─── Sandbox client ───────────────────────────────────────────────────────────

_sandbox_client: SandboxClient | None = None


async def get_sandbox_client_with_store(store: Store) -> SandboxClient:
    global _sandbox_client
    if _sandbox_client is None:
        settings = await store.load_settings()
        _sandbox_client = SandboxClient(
            base_url=settings.sandbox_manager_url,
            api_key=settings.sandbox_api_key,
        )
    return _sandbox_client


def get_sandbox_client() -> SandboxClient:
    """Legacy: get sandbox client without store (uses existing instance)."""
    global _sandbox_client
    if _sandbox_client is None:
        raise HTTPException(status_code=503, detail="Sandbox client not initialized")
    return _sandbox_client


def reset_sandbox_client():
    global _sandbox_client
    if _sandbox_client is not None:
        asyncio.create_task(_sandbox_client.close())
    _sandbox_client = None
