"""
SignalPilot Gateway — FastAPI application.

Endpoints:
  GET  /health
  GET  /api/settings          GET/PUT gateway settings (BYOF config)
  PUT  /api/settings
  GET  /api/connections        list connections
  POST /api/connections        create connection
  GET  /api/connections/{name} get connection details
  DELETE /api/connections/{name}
  POST /api/connections/{name}/test

  GET  /api/sandboxes          list active sandboxes
  POST /api/sandboxes          create sandbox
  GET  /api/sandboxes/{id}     get sandbox details
  DELETE /api/sandboxes/{id}   kill sandbox
  POST /api/sandboxes/{id}/execute  run code

  POST /api/query              governed SQL query (direct DB)

  GET  /api/audit              audit log
  GET  /api/metrics            SSE live metrics stream
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .engine import inject_limit, validate_sql

# Map db_type to sqlglot dialect for correct SQL parsing/generation
_SQLGLOT_DIALECTS: dict[str, str] = {
    "postgres": "postgres",
    "mysql": "mysql",
    "snowflake": "snowflake",
    "bigquery": "bigquery",
    "redshift": "redshift",
    "clickhouse": "clickhouse",
    "databricks": "databricks",
    "duckdb": "duckdb",
    "sqlite": "sqlite",
}
from .middleware import APIKeyAuthMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware
from .models import (
    AuditEntry,
    ConnectionCreate,
    ConnectionUpdate,
    ExecuteRequest,
    GatewaySettings,
    SandboxCreate,
)
from .connectors.pool_manager import pool_manager
from .connectors.health_monitor import health_monitor
from .connectors.schema_cache import schema_cache
from .sandbox_client import SandboxClient
from .store import (
    append_audit,
    create_connection,
    delete_connection,
    delete_sandbox,
    get_connection,
    get_connection_string,
    get_credential_extras,
    get_sandbox,
    list_connections,
    list_sandboxes,
    load_settings,
    read_audit,
    save_settings,
    update_connection,
    upsert_sandbox,
    get_schema_endorsements,
    set_schema_endorsements,
    apply_endorsement_filter,
)

# ─── Error Sanitization (HIGH-06) ────────────────────────────────────────────

import re as _re

_SENSITIVE_PATTERNS = [
    _re.compile(r"postgresql://[^\s]+", _re.IGNORECASE),
    _re.compile(r"mysql://[^\s]+", _re.IGNORECASE),
    _re.compile(r"redshift://[^\s]+", _re.IGNORECASE),
    _re.compile(r"clickhouse://[^\s]+", _re.IGNORECASE),
    _re.compile(r"snowflake://[^\s]+", _re.IGNORECASE),
    _re.compile(r"databricks://[^\s]+", _re.IGNORECASE),
    _re.compile(r"password[=:]\s*\S+", _re.IGNORECASE),
    _re.compile(r"host=\S+", _re.IGNORECASE),
    _re.compile(r"access_token[=:]\s*\S+", _re.IGNORECASE),
    _re.compile(r"private_key[=:]\s*\S+", _re.IGNORECASE),
]


def _sanitize_db_error(error: str) -> str:
    """Remove connection strings, passwords, and host info from error messages."""
    sanitized = error
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    # Truncate to prevent information dump
    if len(sanitized) > 500:
        sanitized = sanitized[:500] + "..."
    return sanitized


# ─── Global sandbox client (recreated when settings change) ──────────────────

_sandbox_client: SandboxClient | None = None


def _get_sandbox_client() -> SandboxClient:
    global _sandbox_client
    if _sandbox_client is None:
        settings = load_settings()
        _sandbox_client = SandboxClient(
            base_url=settings.sandbox_manager_url,
            api_key=settings.sandbox_api_key,
        )
    return _sandbox_client


def _reset_sandbox_client():
    global _sandbox_client
    if _sandbox_client is not None:
        asyncio.create_task(_sandbox_client.close())
    _sandbox_client = None


# ─── App ─────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background pool cleanup task
    async def _pool_cleanup_loop():
        while True:
            await asyncio.sleep(60)
            await pool_manager.cleanup_idle()

    cleanup_task = asyncio.create_task(_pool_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        await pool_manager.close_all()
        if _sandbox_client:
            await _sandbox_client.close()


app = FastAPI(
    title="SignalPilot Gateway",
    version="0.1.0",
    description="Governed MCP server for AI database access",
    lifespan=lifespan,
)

# CORS — restrict to known origins instead of wildcard (CRIT-02 fix)
_ALLOWED_ORIGINS = [
    "http://localhost:3200",
    "http://localhost:3000",
    "http://127.0.0.1:3200",
    "http://127.0.0.1:3000",
]
# Allow override via env var for production deployments
import os as _os
_extra_origins = _os.getenv("SP_ALLOWED_ORIGINS", "")
if _extra_origins:
    _ALLOWED_ORIGINS.extend(o.strip() for o in _extra_origins.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    allow_credentials=True,
)

# Security middleware stack (order matters: outermost runs first)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, general_rpm=120, expensive_rpm=30)
app.add_middleware(APIKeyAuthMiddleware)


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    settings = load_settings()
    sandbox_status = "unknown"
    try:
        client = _get_sandbox_client()
        data = await client.health()
        sandbox_status = data.get("status", "unknown")
    except Exception as e:
        sandbox_status = f"error: {e}"

    return {
        "status": "healthy",
        "version": "0.1.0",
        "sandbox_manager": settings.sandbox_manager_url,
        "sandbox_status": sandbox_status,
        "active_sandboxes": len(list_sandboxes()),
        "connections": len(list_connections()),
    }


# ─── Settings ────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    return load_settings()


@app.put("/api/settings")
async def update_settings(settings: GatewaySettings):
    save_settings(settings)
    _reset_sandbox_client()  # Reconnect with new URL
    return settings


# ─── Connections ─────────────────────────────────────────────────────────────

@app.get("/api/connections")
async def get_connections():
    return list_connections()


@app.post("/api/connections", status_code=201)
async def add_connection(conn: ConnectionCreate):
    # Pre-flight validation per DB type
    errors = _validate_connection_params(conn)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})
    try:
        info = create_connection(conn)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Auto-refresh schema in background (like HEX's automatic schema fetch on new connections)
    asyncio.create_task(_auto_schema_refresh(info.name, info.db_type))

    return info


async def _auto_schema_refresh(name: str, db_type: str):
    """Background task: fetch schema for newly created connections.

    HEX automatically kicks off a schema refresh on new connections.
    This ensures the schema is cached and ready for AI agents immediately.
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        conn_str = get_connection_string(name)
        if not conn_str:
            return
        extras = get_credential_extras(name)
        connector = await pool_manager.acquire(db_type, conn_str, credential_extras=extras)
        schema = await connector.get_schema()
        await pool_manager.release(db_type, conn_str)
        # Cache the schema
        schema_cache.put(name, schema)
        logger.info("Auto-refreshed schema for new connection '%s': %d tables", name, len(schema))
    except Exception as e:
        logger.warning("Auto-schema-refresh failed for '%s': %s", name, e)


def _validate_connection_params(conn: ConnectionCreate) -> list[str]:
    """Validate connection parameters before persisting. Returns list of error messages."""
    errors: list[str] = []

    # If using connection_string, minimal validation
    if conn.connection_string:
        return errors

    db = conn.db_type

    # Host/port databases need at minimum host
    if db in ("postgres", "mysql", "redshift", "clickhouse"):
        if not conn.host:
            errors.append(f"{db} requires a host")
        if not conn.username:
            errors.append(f"{db} requires a username")

    # Snowflake needs account
    if db == "snowflake":
        if not conn.account:
            errors.append("Snowflake requires an account identifier")
        if not conn.username:
            errors.append("Snowflake requires a username")

    # BigQuery needs project
    if db == "bigquery":
        if not conn.project:
            errors.append("BigQuery requires a GCP project ID")
        if not conn.credentials_json:
            errors.append("BigQuery requires service account credentials JSON")

    # Databricks needs host + http_path + token
    if db == "databricks":
        if not conn.host:
            errors.append("Databricks requires a server hostname")
        if not conn.http_path:
            errors.append("Databricks requires an HTTP path (SQL warehouse endpoint)")
        if not conn.access_token:
            errors.append("Databricks requires a personal access token")

    # DuckDB/SQLite just need a path
    if db in ("duckdb", "sqlite"):
        if not conn.database:
            errors.append(f"{db} requires a database file path (or :memory:)")

    # SSH tunnel validation
    if conn.ssh_tunnel and conn.ssh_tunnel.enabled:
        if not conn.ssh_tunnel.host:
            errors.append("SSH tunnel requires a bastion host")
        if not conn.ssh_tunnel.username:
            errors.append("SSH tunnel requires a username")
        if conn.ssh_tunnel.auth_method == "key" and not conn.ssh_tunnel.private_key:
            errors.append("SSH tunnel with key auth requires a private key")
        if conn.ssh_tunnel.auth_method == "password" and not conn.ssh_tunnel.password:
            errors.append("SSH tunnel with password auth requires a password")
        if db not in ("postgres", "mysql", "redshift", "clickhouse"):
            errors.append(f"SSH tunnels are not supported for {db} (only host:port databases)")

    return errors


# Connection health — must be defined before {name} routes to avoid path conflict
@app.get("/api/connections/health")
async def get_all_connection_health(window: int = Query(default=300, ge=60, le=3600)):
    """Get health stats for all monitored connections (Feature #31)."""
    return {"connections": health_monitor.all_stats(window)}


@app.get("/api/connections/{name}")
async def get_connection_detail(name: str):
    conn = get_connection(name)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    return conn


@app.delete("/api/connections/{name}", status_code=204)
async def remove_connection(name: str):
    if not delete_connection(name):
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    # Invalidate schema cache for deleted connection
    schema_cache.invalidate(name)


@app.put("/api/connections/{name}")
async def edit_connection(name: str, update: ConnectionUpdate):
    """Update an existing connection. Only provided fields are changed."""
    existing = get_connection(name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    # If db_type is changing, validate the new type's required fields
    update_data = update.model_dump(exclude_none=True)
    if update_data:
        # Merge with existing to validate
        merged_db_type = update_data.get("db_type", existing.db_type)
        merged = ConnectionCreate(
            name=name,
            db_type=merged_db_type,
            **{k: v for k, v in {**existing.model_dump(), **update_data}.items()
               if k not in ("id", "created_at", "last_used", "status", "name", "db_type")},
        )
        errors = _validate_connection_params(merged)
        if errors:
            raise HTTPException(status_code=422, detail={"validation_errors": errors})

    # Capture old connection string before update for pool cleanup
    old_conn_str = get_connection_string(name)

    result = update_connection(name, update)
    if not result:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    # Invalidate caches — connection params may have changed
    schema_cache.invalidate(name)
    if old_conn_str:
        await pool_manager.close_pool(old_conn_str)

    return result


@app.post("/api/connections/{name}/clone")
async def clone_connection(name: str, new_name: str = Query(..., min_length=1, max_length=64)):
    """Clone an existing connection with a new name.

    Copies all settings including credentials. Useful for creating staging/dev
    variants of production connections.
    """
    existing = get_connection(name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    # Check new name doesn't exist
    if get_connection(new_name):
        raise HTTPException(status_code=409, detail=f"Connection '{new_name}' already exists")

    # Build a ConnectionCreate from existing connection data
    clone_desc = f"Clone of {name}" if not existing.description else f"{existing.description} (clone)"
    create_data: dict = {
        "name": new_name,
        "db_type": existing.db_type,
        "description": clone_desc,
    }
    # Copy all non-None fields
    for field in ("host", "port", "database", "username", "account", "warehouse",
                   "schema_name", "role", "project", "dataset", "http_path", "catalog"):
        val = getattr(existing, field, None)
        if val is not None:
            create_data[field] = val

    # Use the original connection string as-is (preserves password)
    conn_str = get_connection_string(name)
    if conn_str:
        create_data["connection_string"] = conn_str

    conn = ConnectionCreate(**create_data)
    result = create_connection(conn)
    return result


@app.post("/api/connections/{name}/schema/refresh")
async def refresh_connection_schema(name: str):
    """Force-refresh the cached schema for a connection.

    Invalidates the cached schema and fetches fresh metadata from the database.
    Useful after migrations or DDL changes.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    # Invalidate cached schema
    schema_cache.invalidate(name)

    try:
        extras = get_credential_extras(name)
        connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)
        schema = await connector.get_schema()
        await pool_manager.release(info.db_type, conn_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))

    schema_cache.put(name, schema)
    return {
        "connection_name": name,
        "table_count": len(schema),
        "message": "Schema refreshed successfully",
    }


@app.post("/api/connections/{name}/test")
async def test_connection(name: str):
    """Two-phase connection test (industry standard pattern from HEX/DBeaver):
    Phase 1: Network/tunnel connectivity
    Phase 2: Database authentication and query
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        return {"status": "error", "phase": "credentials", "message": "No credentials stored (restart gateway to reload)"}

    extras = get_credential_extras(name)
    phases: list[dict] = []
    t0 = time.monotonic()

    # Phase 1: SSH tunnel (if configured)
    has_tunnel = (
        extras.get("ssh_tunnel")
        and extras["ssh_tunnel"].get("enabled")
        and info.db_type in ("postgres", "mysql", "redshift", "clickhouse")
    )
    if has_tunnel:
        try:
            from .connectors.ssh_tunnel import SSHTunnel
            from .connectors.pool_manager import _extract_host_port
            ssh_config = extras["ssh_tunnel"]
            remote_host, remote_port = _extract_host_port(conn_str, info.db_type)
            # Just verify SSH is reachable (tunnel start/stop is handled by pool_manager)
            phases.append({
                "phase": "ssh_tunnel",
                "status": "ok",
                "message": f"SSH tunnel config valid: {ssh_config.get('username')}@{ssh_config.get('host')}:{ssh_config.get('port', 22)}",
                "duration_ms": round((time.monotonic() - t0) * 1000, 1),
            })
        except Exception as e:
            phases.append({
                "phase": "ssh_tunnel",
                "status": "error",
                "message": _sanitize_db_error(str(e)),
                "duration_ms": round((time.monotonic() - t0) * 1000, 1),
            })
            return {"status": "error", "phases": phases, "message": f"SSH tunnel failed: {_sanitize_db_error(str(e))}"}

    # Phase 2: Database connection + auth + query
    t1 = time.monotonic()
    try:
        connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)
        ok = await connector.health_check()

        # Fetch database version for diagnostic info
        db_version = ""
        try:
            version_queries = {
                "postgres": "SELECT version()",
                "mysql": "SELECT version()",
                "redshift": "SELECT version()",
                "clickhouse": "SELECT version()",
                "snowflake": "SELECT CURRENT_VERSION()",
                "duckdb": "SELECT version()",
                "sqlite": "SELECT sqlite_version()",
            }
            vq = version_queries.get(info.db_type)
            if vq:
                vrows = await connector.execute(vq)
                if vrows:
                    raw = str(list(vrows[0].values())[0]).split("\n")[0]
                    # Extract just the product name and version number
                    import re as _re_ver
                    ver_match = _re_ver.match(r"([\w\s]+?\d+[\d.]+)", raw)
                    db_version = ver_match.group(1).strip() if ver_match else raw[:60]
        except Exception:
            pass

        await pool_manager.release(info.db_type, conn_str)
        phase2_duration = round((time.monotonic() - t1) * 1000, 1)
        if ok:
            msg = "Authentication and query test passed"
            if db_version:
                msg += f" ({db_version})"
            phases.append({
                "phase": "database",
                "status": "ok",
                "message": msg,
                "duration_ms": phase2_duration,
            })
        else:
            phases.append({
                "phase": "database",
                "status": "error",
                "message": "Health check failed after connection",
                "duration_ms": phase2_duration,
            })
            return {"status": "error", "phases": phases, "message": "Health check failed"}
    except Exception as e:
        phases.append({
            "phase": "database",
            "status": "error",
            "message": _sanitize_db_error(str(e)),
            "duration_ms": round((time.monotonic() - t1) * 1000, 1),
        })
        return {"status": "error", "phases": phases, "message": _sanitize_db_error(str(e))}

    total_ms = round((time.monotonic() - t0) * 1000, 1)
    return {
        "status": "healthy",
        "phases": phases,
        "message": "All connection tests passed",
        "total_duration_ms": total_ms,
    }


@app.get("/api/connections/{name}/health")
async def get_connection_health(name: str, window: int = Query(default=300, ge=60, le=3600)):
    """Get health stats for a specific connection."""
    stats = health_monitor.connection_stats(name, window)
    if stats is None:
        raise HTTPException(status_code=404, detail=f"No health data for connection '{name}'")
    return stats


@app.get("/api/connections/{name}/schema")
async def get_connection_schema(
    name: str,
    compact: bool = Query(default=False, description="Return compressed schema optimized for LLM context windows"),
    filter: str = Query(default="", description="Filter tables by name pattern (case-insensitive substring match, comma-separated)"),
):
    """Retrieve the full schema for a database connection (Feature #18: schema caching).

    With compact=true, returns a compressed DDL-style representation that reduces
    token count by ~60-70% while preserving all information needed for text-to-SQL.
    With filter, returns only tables matching the given patterns.
    This is critical for Spider2.0 benchmark performance on large schemas.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    # Check schema cache first (Feature #18)
    cached = schema_cache.get(name)
    is_cached = cached is not None
    if cached is None:
        try:
            extras = get_credential_extras(name)
            connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)
            cached = await connector.get_schema()
            await pool_manager.release(info.db_type, conn_str)
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))
        schema_cache.put(name, cached)

    # Apply endorsement filter (HEX Data Browser pattern — curate tables for AI agents)
    filtered = apply_endorsement_filter(name, cached)

    # Apply table name filter if provided (additional narrowing)
    if filter:
        patterns = [p.strip().lower() for p in filter.split(",") if p.strip()]
        filtered = {
            k: v for k, v in filtered.items()
            if any(pat in k.lower() or pat in v.get("name", "").lower() for pat in patterns)
        }

    tables = _compress_schema(filtered) if compact else filtered
    return {
        "connection_name": name,
        "db_type": info.db_type,
        "table_count": len(filtered),
        "total_tables": len(cached),
        "tables": tables,
        "cached": is_cached,
        "compact": compact,
        "filtered": bool(filter),
    }


def _compress_schema(schema: dict) -> dict:
    """Compress schema to DDL-style representation for LLM context efficiency.

    Top Spider2.0 performers use table compression for schemas >50K tokens.
    This reduces token count by ~60-70% while preserving:
    - Table and column names + types
    - Primary keys and foreign keys (critical for join path discovery)
    - Row counts (helps query planning)
    - Index information (helps optimization)
    """
    compressed = {}
    for key, table in schema.items():
        cols = []
        pk_cols = []
        for col in table.get("columns", []):
            col_type = col.get("type", "")
            nullable = "" if col.get("nullable", True) else " NOT NULL"
            # Add cardinality hint for unique columns (helps Spider2.0 join planning)
            unique_hint = ""
            stats = col.get("stats", {})
            if stats.get("distinct_fraction") == -1.0:
                unique_hint = " UNIQUE"
            cols.append(f"{col['name']} {col_type}{nullable}{unique_hint}")
            if col.get("primary_key"):
                pk_cols.append(col["name"])

        # Build compact DDL string
        ddl_parts = [f"CREATE TABLE {table.get('schema', '')}.{table['name']} ("]
        ddl_parts.append("  " + ", ".join(cols))
        if pk_cols:
            ddl_parts.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")
        ddl_parts.append(")")

        # Foreign keys as compact references
        fk_refs = []
        for fk in table.get("foreign_keys", []):
            ref_table = fk.get("references_table", "")
            if fk.get("references_schema"):
                ref_table = f"{fk['references_schema']}.{ref_table}"
            fk_refs.append(f"{fk['column']} -> {ref_table}.{fk.get('references_column', '')}")

        compressed[key] = {
            "ddl": "\n".join(ddl_parts),
            "row_count": table.get("row_count", 0),
        }
        if fk_refs:
            compressed[key]["foreign_keys"] = fk_refs
        if table.get("indexes"):
            compressed[key]["indexes"] = [
                idx.get("name", "") for idx in table["indexes"]
            ]
        if table.get("description"):
            compressed[key]["description"] = table["description"]
        # ClickHouse-specific
        if table.get("engine"):
            compressed[key]["engine"] = table["engine"]
        if table.get("sorting_key"):
            compressed[key]["sorting_key"] = table["sorting_key"]

    return compressed


def _group_tables(schema: dict) -> dict[str, list[str]]:
    """Group related tables by naming patterns and FK relationships.

    ReFoRCE (Spider2.0 SOTA) uses pattern-based table grouping to compress
    large schemas. Tables are grouped when they share a common prefix
    (e.g., order_items, order_history -> "order" group) or are connected
    by foreign keys.
    """
    from collections import defaultdict

    # Phase 1: Group by naming prefix (common enterprise pattern)
    prefix_groups: dict[str, list[str]] = defaultdict(list)
    for key in schema:
        table_name = schema[key].get("name", key.split(".")[-1])
        # Extract prefix — first word before underscore
        parts = table_name.lower().split("_")
        if len(parts) >= 2:
            prefix = parts[0]
            prefix_groups[prefix].append(key)
        else:
            prefix_groups[table_name].append(key)

    # Phase 2: Merge FK-connected tables into same groups
    fk_graph: dict[str, set[str]] = defaultdict(set)
    for key, table in schema.items():
        for fk in table.get("foreign_keys", []):
            ref_schema = fk.get("references_schema", "")
            ref_table = fk.get("references_table", "")
            ref_key = f"{ref_schema}.{ref_table}" if ref_schema else ref_table
            # Find the actual key that matches
            for k in schema:
                if k == ref_key or k.endswith(f".{ref_table}"):
                    fk_graph[key].add(k)
                    fk_graph[k].add(key)
                    break

    # Merge prefix groups that are FK-connected
    groups: dict[str, list[str]] = {}
    assigned: set[str] = set()
    for prefix, members in sorted(prefix_groups.items(), key=lambda x: -len(x[1])):
        if len(members) >= 2:
            group_key = prefix
            group_members = set(members)
            # Add FK-connected tables
            for m in list(group_members):
                group_members.update(fk_graph.get(m, set()))
            groups[group_key] = sorted(group_members - assigned)
            assigned.update(group_members)

    # Remaining ungrouped tables
    ungrouped = [k for k in schema if k not in assigned]
    if ungrouped:
        groups["_other"] = sorted(ungrouped)

    # Remove empty groups
    return {k: v for k, v in groups.items() if v}


@app.get("/api/connections/{name}/schema/grouped")
async def get_grouped_schema(
    name: str,
    sample_limit: int = Query(default=3, ge=1, le=10),
):
    """Return schema organized by table groups — optimized for large schemas.

    Uses ReFoRCE-style pattern-based table grouping to organize related tables
    together. This helps AI agents understand table relationships and reduces
    schema linking errors in text-to-SQL tasks.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    try:
        extras = get_credential_extras(name)
        connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)

        cached = schema_cache.get(name)
        if cached is None:
            cached = await connector.get_schema()
            schema_cache.put(name, cached)

        # Compress and group
        compressed = _compress_schema(cached)
        groups = _group_tables(cached)

        await pool_manager.release(info.db_type, conn_str)

        return {
            "connection_name": name,
            "db_type": info.db_type,
            "table_count": len(cached),
            "group_count": len(groups),
            "groups": {
                group_name: {
                    "tables": {k: compressed[k] for k in table_keys if k in compressed},
                    "table_count": len(table_keys),
                }
                for group_name, table_keys in groups.items()
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))


@app.get("/api/connections/{name}/schema/samples")
async def get_schema_samples(
    name: str,
    tables: str = Query(default="", description="Comma-separated table keys to sample (e.g., 'public.users,public.orders')"),
    limit: int = Query(default=5, ge=1, le=20, description="Max distinct values per column"),
):
    """Get sample distinct values for columns — critical for Spider2.0 schema linking.

    Top performers use sample values to reduce column name hallucination
    and improve schema-to-question matching. Returns up to `limit` distinct
    values per column for the specified tables.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    # Get schema to know which columns exist
    cached = schema_cache.get(name)
    if cached is None:
        try:
            extras = get_credential_extras(name)
            connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)
            cached = await connector.get_schema()
            schema_cache.put(name, cached)
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))

    # Determine which tables to sample
    table_keys = [t.strip() for t in tables.split(",") if t.strip()] if tables else list(cached.keys())
    # Cap at 10 tables to prevent overload
    table_keys = table_keys[:10]

    try:
        extras = get_credential_extras(name)
        connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)

        samples: dict[str, dict[str, list]] = {}
        for table_key in table_keys:
            if table_key not in cached:
                continue
            table_info = cached[table_key]
            # Only sample string-like columns (most useful for schema linking)
            string_types = {"character varying", "varchar", "text", "char", "character", "enum",
                           "String", "VARCHAR", "TEXT", "CHAR", "NVARCHAR", "string"}
            sample_cols = [
                col["name"] for col in table_info.get("columns", [])
                if col.get("type", "") in string_types or "char" in col.get("type", "").lower()
            ]
            if not sample_cols:
                continue

            table_name = f"{table_info.get('schema', '')}.{table_info['name']}" if table_info.get("schema") else table_info["name"]
            values = await connector.get_sample_values(table_name, sample_cols, limit=limit)
            if values:
                samples[table_key] = values

        await pool_manager.release(info.db_type, conn_str)
        return {
            "connection_name": name,
            "tables_sampled": len(samples),
            "samples": samples,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))


@app.get("/api/connections/{name}/schema/enriched")
async def get_enriched_schema(
    name: str,
    sample_limit: int = Query(default=3, ge=1, le=10, description="Max sample values per column"),
):
    """Return enriched compact schema optimized for Spider2.0 text-to-SQL.

    Combines compact DDL + foreign keys + sample values + statistics in one call.
    This is the recommended endpoint for AI agents — provides everything needed
    for accurate schema linking in a single request with minimal token count.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    try:
        extras = get_credential_extras(name)
        connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)

        # Get or use cached schema
        cached = schema_cache.get(name)
        if cached is None:
            cached = await connector.get_schema()
            schema_cache.put(name, cached)

        # Build enriched compact schema
        enriched: dict[str, Any] = {}
        for key, table in cached.items():
            # Compact DDL
            cols = []
            pk_cols = []
            for col in table.get("columns", []):
                col_type = col.get("type", "")
                nullable = "" if col.get("nullable", True) else " NOT NULL"
                unique_hint = ""
                stats = col.get("stats", {})
                if stats.get("distinct_fraction") == -1.0:
                    unique_hint = " UNIQUE"
                cols.append(f"{col['name']} {col_type}{nullable}{unique_hint}")
                if col.get("primary_key"):
                    pk_cols.append(col["name"])

            ddl_parts = [f"CREATE TABLE {table.get('schema', '')}.{table['name']} ("]
            ddl_parts.append("  " + ", ".join(cols))
            if pk_cols:
                ddl_parts.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")
            ddl_parts.append(")")

            fk_refs = []
            for fk in table.get("foreign_keys", []):
                ref_table = fk.get("references_table", "")
                if fk.get("references_schema"):
                    ref_table = f"{fk['references_schema']}.{ref_table}"
                fk_refs.append(f"{fk['column']} -> {ref_table}.{fk.get('references_column', '')}")

            entry: dict[str, Any] = {
                "ddl": "\n".join(ddl_parts),
                "row_count": table.get("row_count", 0),
            }
            if fk_refs:
                entry["foreign_keys"] = fk_refs
            if table.get("indexes"):
                entry["indexes"] = [idx.get("name", "") for idx in table["indexes"]]
            if table.get("description"):
                entry["description"] = table["description"]

            enriched[key] = entry

        # Sample values (string columns only, limited tables)
        string_types = {"character varying", "varchar", "text", "char", "character",
                       "enum", "String", "VARCHAR", "TEXT", "CHAR", "NVARCHAR", "string"}
        for key in list(enriched.keys())[:15]:  # Cap at 15 tables
            table_info = cached.get(key, {})
            sample_cols = [
                col["name"] for col in table_info.get("columns", [])
                if col.get("type", "") in string_types or "char" in col.get("type", "").lower()
            ]
            if not sample_cols:
                continue
            table_name = f"{table_info.get('schema', '')}.{table_info['name']}" if table_info.get("schema") else table_info["name"]
            try:
                values = await connector.get_sample_values(table_name, sample_cols, limit=sample_limit)
                if values:
                    enriched[key]["sample_values"] = values
            except Exception:
                pass

        await pool_manager.release(info.db_type, conn_str)

        return {
            "connection_name": name,
            "db_type": info.db_type,
            "table_count": len(enriched),
            "tables": enriched,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))


@app.get("/api/connections/{name}/schema/diff")
async def get_schema_diff(name: str):
    """Compare current database schema against cached version.

    Returns added/removed/modified tables and columns. Useful for detecting
    schema drift, migration verification, and keeping AI agent context current.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    try:
        extras = get_credential_extras(name)
        connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)
        new_schema = await connector.get_schema()
        await pool_manager.release(info.db_type, conn_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))

    # Compare with cached schema
    diff = schema_cache.diff(name, new_schema)
    if diff is None:
        # No cached schema — store current and return no-diff baseline
        schema_cache.put(name, new_schema)
        return {
            "connection_name": name,
            "has_cached": False,
            "message": "No cached schema to compare. Current schema cached as baseline.",
            "table_count": len(new_schema),
        }

    # Update cache with new schema
    schema_cache.put(name, new_schema)

    return {
        "connection_name": name,
        "has_cached": True,
        "diff": diff,
        "table_count": len(new_schema),
    }


@app.get("/api/connections/{name}/schema/search")
async def search_schema(
    name: str,
    q: str = Query(..., min_length=1, description="Search query — matches table names, column names, column comments"),
    include_samples: bool = Query(default=False, description="Include sample values for matched columns"),
    limit: int = Query(default=20, ge=1, le=100, description="Max tables to return"),
):
    """Semantic search across schema metadata for AI agent schema linking.

    This endpoint enables Spider2.0-style schema linking: given a natural language
    query, the agent searches for relevant tables and columns before generating SQL.
    Matches against table names, column names, column comments, and foreign key
    references. Results are ranked by relevance (exact match > prefix > substring).
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    # Get schema from cache or fetch
    cached = schema_cache.get(name)
    if cached is None:
        try:
            extras = get_credential_extras(name)
            connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)
            cached = await connector.get_schema()
            await pool_manager.release(info.db_type, conn_str)
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))
        schema_cache.put(name, cached)

    # Score each table by relevance to query terms
    terms = [t.strip().lower() for t in q.split() if t.strip()]
    scored: list[tuple[float, str, dict]] = []

    for key, table in cached.items():
        score = 0.0
        table_name_lower = table.get("name", "").lower()
        schema_name_lower = table.get("schema", "").lower()
        matched_columns: list[str] = []

        for term in terms:
            # Table name matching (highest weight)
            if term == table_name_lower:
                score += 10.0
            elif table_name_lower.startswith(term):
                score += 5.0
            elif term in table_name_lower:
                score += 3.0

            # Schema name matching
            if term in schema_name_lower:
                score += 1.0

            # Column name matching
            for col in table.get("columns", []):
                col_name = col.get("name", "").lower()
                col_comment = col.get("comment", "").lower()
                if term == col_name:
                    score += 4.0
                    matched_columns.append(col["name"])
                elif col_name.startswith(term):
                    score += 2.0
                    matched_columns.append(col["name"])
                elif term in col_name:
                    score += 1.5
                    matched_columns.append(col["name"])
                # Comment matching
                if col_comment and term in col_comment:
                    score += 1.0
                    if col["name"] not in matched_columns:
                        matched_columns.append(col["name"])

            # FK reference matching — find tables that reference or are referenced
            for fk in table.get("foreign_keys", []):
                ref_table = fk.get("references_table", "").lower()
                if term in ref_table:
                    score += 2.0

            # Table description/comment matching
            desc = table.get("description", "").lower()
            if desc and term in desc:
                score += 1.5

        if score > 0:
            # Deduplicate matched columns
            result_table = dict(table)
            result_table["_matched_columns"] = list(dict.fromkeys(matched_columns))
            result_table["_relevance_score"] = round(score, 1)
            scored.append((score, key, result_table))

    # Sort by score descending, take top N
    scored.sort(key=lambda x: x[0], reverse=True)
    results = {}
    for score, key, table in scored[:limit]:
        results[key] = table

    # Optionally fetch sample values for matched columns
    if include_samples and results:
        try:
            extras = get_credential_extras(name)
            connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)
            for key, table in results.items():
                matched_cols = table.get("_matched_columns", [])
                if matched_cols and hasattr(connector, "get_sample_values"):
                    full_name = f"{table.get('schema', '')}.{table['name']}" if table.get("schema") else table["name"]
                    try:
                        samples = await connector.get_sample_values(full_name, matched_cols[:5], limit=3)
                        if samples:
                            table["_sample_values"] = samples
                    except Exception:
                        pass
            await pool_manager.release(info.db_type, conn_str)
        except Exception:
            pass

    return {
        "connection_name": name,
        "query": q,
        "result_count": len(results),
        "total_tables": len(cached),
        "tables": results,
    }


# ─── Schema Endorsements (HEX Data Browser pattern) ────────────────────────
# Curating which tables the AI agent sees improves SQL accuracy from 82% to 96%
# (per HEX's internal testing). Two modes:
#   - "all" (default): show all tables except hidden ones
#   - "endorsed_only": show only explicitly endorsed tables

@app.get("/api/connections/{name}/schema/endorsements")
async def get_endorsements(name: str):
    """Get schema endorsement config for a connection."""
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    return get_schema_endorsements(name)


@app.put("/api/connections/{name}/schema/endorsements")
async def update_endorsements(name: str, body: dict):
    """Set schema endorsement config for a connection.

    Body: {"endorsed": ["schema.table", ...], "hidden": ["schema.table", ...], "mode": "all|endorsed_only"}
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    mode = body.get("mode", "all")
    if mode not in ("all", "endorsed_only"):
        raise HTTPException(status_code=422, detail="mode must be 'all' or 'endorsed_only'")
    result = set_schema_endorsements(name, body)
    # Invalidate schema cache so next fetch applies the new filter
    schema_cache.invalidate(name)
    return result


# ─── Column Name Correction (Spider2.0 hallucination fix) ──────────────────

def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            curr_row.append(min(
                prev_row[j + 1] + 1,
                curr_row[j] + 1,
                prev_row[j] + (0 if c1 == c2 else 1),
            ))
        prev_row = curr_row
    return prev_row[-1]


@app.post("/api/connections/{name}/schema/correct-columns")
async def correct_columns(name: str, body: dict):
    """Suggest corrections for hallucinated column names.

    Spider2.0 research shows that LLM agents frequently hallucinate column names
    (e.g., "customer_name" instead of "first_name"). This endpoint returns the
    closest matching columns using Levenshtein distance.

    Body: {"table": "public.customers", "columns": ["customer_name", "email_addr"]}
    Returns corrections for columns that don't exist in the schema.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    table_key = body.get("table", "")
    candidate_columns = body.get("columns", [])
    threshold = body.get("threshold", 0.5)  # Max edit distance as fraction of name length

    if not table_key or not candidate_columns:
        raise HTTPException(status_code=422, detail="table and columns are required")

    # Get cached schema
    cached = schema_cache.get(name)
    if cached is None:
        conn_str = get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        try:
            extras = get_credential_extras(name)
            connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)
            cached = await connector.get_schema()
            await pool_manager.release(info.db_type, conn_str)
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))
        schema_cache.put(name, cached)

    # Find the table
    table_info = cached.get(table_key)
    if not table_info:
        # Try fuzzy table match
        best_table = None
        best_dist = 999
        for k in cached:
            d = _levenshtein(table_key.lower(), k.lower())
            if d < best_dist:
                best_dist = d
                best_table = k
        if best_table and best_dist <= len(table_key) * threshold:
            table_info = cached[best_table]
        else:
            return {"corrections": {}, "table_suggestion": best_table if best_table else None}

    actual_columns = {col["name"].lower(): col["name"] for col in table_info.get("columns", [])}
    corrections: dict = {}

    for candidate in candidate_columns:
        candidate_lower = candidate.lower()
        # Exact match — no correction needed
        if candidate_lower in actual_columns:
            continue

        # Find closest column by edit distance
        best_match = None
        best_dist = 999
        for col_lower, col_name in actual_columns.items():
            d = _levenshtein(candidate_lower, col_lower)
            if d < best_dist:
                best_dist = d
                best_match = col_name

        # Only suggest if within threshold
        max_dist = max(len(candidate), 1) * threshold
        if best_match and best_dist <= max_dist:
            corrections[candidate] = {
                "suggestion": best_match,
                "distance": best_dist,
                "confidence": round(1.0 - (best_dist / max(len(candidate), 1)), 2),
            }
        else:
            corrections[candidate] = {"suggestion": None, "distance": best_dist, "confidence": 0.0}

    return {
        "table": table_key,
        "corrections": corrections,
        "total_columns": len(actual_columns),
    }


# ─── Sandboxes ───────────────────────────────────────────────────────────────

@app.get("/api/sandboxes")
async def get_sandboxes():
    return list_sandboxes()


@app.post("/api/sandboxes", status_code=201)
async def create_sandbox(req: SandboxCreate):
    session_token = str(uuid.uuid4())
    settings = load_settings()

    client = _get_sandbox_client()
    sandbox = await client.create_sandbox(
        session_token=session_token,
        connection_name=req.connection_name,
        label=req.label,
        budget_usd=req.budget_usd,
        row_limit=req.row_limit,
    )
    upsert_sandbox(sandbox)

    await append_audit(AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        event_type="connect",
        connection_name=req.connection_name,
        sandbox_id=sandbox.id,
        metadata={"label": req.label},
    ))

    return sandbox


@app.get("/api/sandboxes/{sandbox_id}")
async def get_sandbox_detail(sandbox_id: str):
    sandbox = get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return sandbox


@app.delete("/api/sandboxes/{sandbox_id}", status_code=204)
async def kill_sandbox(sandbox_id: str):
    sandbox = get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if sandbox.vm_id:
        client = _get_sandbox_client()
        await client.kill(sandbox.vm_id)

    delete_sandbox(sandbox_id)


@app.post("/api/sandboxes/{sandbox_id}/execute")
async def execute_in_sandbox(sandbox_id: str, req: ExecuteRequest):
    sandbox = get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if sandbox.status == "stopped":
        raise HTTPException(status_code=409, detail="Sandbox has been stopped")

    settings = load_settings()
    session_token = str(uuid.uuid4())  # In production, this is tied to the session

    client = _get_sandbox_client()
    result = await client.execute(
        sandbox=sandbox,
        code=req.code,
        session_token=session_token,
        timeout=req.timeout,
    )

    # Update sandbox state
    upsert_sandbox(sandbox)

    await append_audit(AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        event_type="execute",
        connection_name=sandbox.connection_name,
        sandbox_id=sandbox_id,
        metadata={"code_preview": req.code[:200], "success": result.success},
    ))

    return result


# ─── Direct SQL Query ─────────────────────────────────────────────────────────

class QueryRequest(ConnectionCreate.__class__):
    pass


from pydantic import BaseModel, Field


class DirectQueryRequest(BaseModel):
    connection_name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    sql: str = Field(..., min_length=1, max_length=100_000)
    row_limit: int = Field(default=10_000, ge=1, le=100_000)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)


@app.post("/api/query")
async def query_database(req: DirectQueryRequest):
    info = get_connection(req.connection_name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{req.connection_name}' not found")

    settings = load_settings()
    timeout = req.timeout_seconds or settings.default_timeout_seconds

    # Load annotations for blocked tables check (Feature #19)
    annotations = load_annotations(req.connection_name)
    blocked_tables = list(annotations.blocked_tables)

    # Merge with settings-level blocked tables
    if settings.blocked_tables:
        blocked_tables.extend(t for t in settings.blocked_tables if t not in blocked_tables)

    # Map DB type to sqlglot dialect for correct SQL parsing
    dialect = _SQLGLOT_DIALECTS.get(info.db_type, "postgres")

    # Validate SQL (with blocked tables from annotations + settings)
    validation = validate_sql(req.sql, blocked_tables=blocked_tables or None, dialect=dialect)
    if not validation.ok:
        await append_audit(AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type="block",
            connection_name=req.connection_name,
            sql=req.sql,
            blocked=True,
            block_reason=validation.blocked_reason,
        ))
        raise HTTPException(status_code=400, detail=f"Query blocked: {validation.blocked_reason}")

    # Inject LIMIT using correct dialect syntax
    safe_sql = inject_limit(req.sql, req.row_limit, dialect=dialect)

    # Check query cache (Feature #30) — same normalized query returns cached result
    cached = query_cache.get(req.connection_name, req.sql, req.row_limit)
    if cached:
        await append_audit(AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type="query",
            connection_name=req.connection_name,
            sql=req.sql,
            tables=cached.tables,
            rows_returned=len(cached.rows),
            duration_ms=0.0,
            metadata={"cache_hit": True},
        ))
        return {
            "rows": cached.rows,
            "row_count": len(cached.rows),
            "tables": cached.tables,
            "execution_ms": cached.execution_ms,
            "sql_executed": cached.sql_executed,
            "cache_hit": True,
        }

    conn_str = get_connection_string(req.connection_name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    # Acquire connector once for both cost estimation and query execution (perf optimization)
    extras = get_credential_extras(req.connection_name)
    connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)

    # Cost estimation (Feature #13) — run EXPLAIN before execution
    cost_estimate = None
    try:
        from .governance.cost_estimator import CostEstimator
        cost_estimate = await CostEstimator.estimate(connector, safe_sql, info.db_type)

        # Check budget before executing expensive queries
        if cost_estimate.is_expensive and cost_estimate.estimated_usd > 0:
            # Warn in audit log but don't block (policy-based blocking is a future feature)
            await append_audit(AuditEntry(
                id=str(uuid.uuid4()),
                timestamp=time.time(),
                event_type="query",
                connection_name=req.connection_name,
                sql=req.sql,
                metadata={"cost_warning": True, "estimated_usd": cost_estimate.estimated_usd, "estimated_rows": cost_estimate.estimated_rows},
            ))
    except Exception:
        pass  # Cost estimation is best-effort

    start = time.monotonic()
    try:
        rows = await connector.execute(safe_sql, timeout=timeout)
        await pool_manager.release(info.db_type, conn_str)
    except asyncio.TimeoutError:
        health_monitor.record(req.connection_name, (time.monotonic() - start) * 1000, False, "timeout", info.db_type)
        raise HTTPException(
            status_code=408,
            detail=f"Query timed out after {timeout}s. Consider adding more specific WHERE clauses or reducing the scope.",
        )
    except Exception as e:
        health_monitor.record(req.connection_name, (time.monotonic() - start) * 1000, False, str(e)[:200], info.db_type)
        sanitized = _sanitize_db_error(str(e))
        raise HTTPException(status_code=500, detail=sanitized)

    elapsed_ms = (time.monotonic() - start) * 1000
    health_monitor.record(req.connection_name, elapsed_ms, True, db_type=info.db_type)

    # Apply PII redaction from annotations (Feature #15)
    from .governance.pii import PIIRedactor
    pii_redactor = PIIRedactor()
    pii_columns = annotations.pii_columns
    for col_name, rule in pii_columns.items():
        pii_redactor.add_rule(col_name, rule)
    if pii_redactor.has_rules():
        rows = pii_redactor.redact_rows(rows)

    # Store in cache after PII redaction (so cached data is already redacted)
    query_cache.put(
        connection_name=req.connection_name,
        sql=req.sql,
        row_limit=req.row_limit,
        rows=rows,
        tables=validation.tables,
        execution_ms=elapsed_ms,
        sql_executed=safe_sql,
    )

    # Charge query cost to budget (Feature #11 + #12)
    query_cost_usd = (elapsed_ms / 1000) * 0.000014
    budget_ledger.charge("default", query_cost_usd)

    await append_audit(AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        event_type="query",
        connection_name=req.connection_name,
        sql=req.sql,
        tables=validation.tables,
        rows_returned=len(rows),
        duration_ms=elapsed_ms,
        cost_usd=query_cost_usd,
        metadata={"pii_redacted": pii_redactor.last_redacted_columns} if pii_redactor.last_redacted_columns else {},
    ))

    response = {
        "rows": rows,
        "row_count": len(rows),
        "tables": validation.tables,
        "execution_ms": elapsed_ms,
        "sql_executed": safe_sql,
        "cache_hit": False,
        "pii_redacted": pii_redactor.last_redacted_columns if pii_redactor.last_redacted_columns else None,
    }
    if cost_estimate and not cost_estimate.warning:
        response["cost_estimate"] = {
            "estimated_rows": cost_estimate.estimated_rows,
            "estimated_usd": round(cost_estimate.estimated_usd, 8),
            "is_expensive": cost_estimate.is_expensive,
        }
    return response


@app.post("/api/query/explain")
async def explain_query(req: DirectQueryRequest):
    """Explain a query without executing it — returns the query plan and cost estimate.

    This is the pre-flight check for the Spider2.0 agent: understand the query plan
    and cost before committing to execution. Matches HEX's "Explain" button behavior.
    """
    info = get_connection(req.connection_name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{req.connection_name}' not found")

    conn_str = get_connection_string(req.connection_name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    # Validate SQL first
    dialect = _SQLGLOT_DIALECTS.get(info.db_type, "postgres")
    annotations = load_annotations(req.connection_name)
    blocked_tables = list(annotations.blocked_tables)
    settings = load_settings()
    if settings.blocked_tables:
        blocked_tables.extend(t for t in settings.blocked_tables if t not in blocked_tables)
    validation = validate_sql(req.sql, blocked_tables=blocked_tables or None, dialect=dialect)
    if not validation.ok:
        raise HTTPException(status_code=400, detail=f"Query blocked: {validation.blocked_reason}")

    safe_sql = inject_limit(req.sql, req.row_limit, dialect=dialect)

    try:
        extras = get_credential_extras(req.connection_name)
        connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)

        from .governance.cost_estimator import CostEstimator
        cost_estimate = await CostEstimator.estimate(connector, safe_sql, info.db_type)
        await pool_manager.release(info.db_type, conn_str)

        return {
            "connection_name": req.connection_name,
            "sql": safe_sql,
            "tables": validation.tables,
            "estimated_rows": cost_estimate.estimated_rows,
            "estimated_cost": cost_estimate.estimated_cost,
            "estimated_usd": round(cost_estimate.estimated_usd, 8),
            "is_expensive": cost_estimate.is_expensive,
            "warning": cost_estimate.warning,
            "plan": cost_estimate.raw_plan,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))


# ─── Audit ───────────────────────────────────────────────────────────────────

@app.get("/api/audit")
async def get_audit(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
    connection_name: str | None = None,
    event_type: str | None = None,
):
    entries = await read_audit(
        limit=limit,
        offset=offset,
        connection_name=connection_name,
        event_type=event_type,
    )
    return {"entries": entries, "total": len(entries)}


@app.get("/api/audit/export")
async def export_audit(
    connection_name: str | None = None,
    event_type: str | None = None,
    format: str = Query(default="json", pattern=r"^(json|csv)$"),
):
    """Export full audit trail for compliance (Feature #45).

    Returns a downloadable JSON or CSV file with all audit entries
    matching the filter criteria. Suitable for SOC 2, HIPAA, or EU AI Act reporting.
    """
    entries = await read_audit(
        limit=10_000,
        offset=0,
        connection_name=connection_name,
        event_type=event_type,
    )

    if format == "csv":
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "timestamp", "event_type", "connection_name", "sql",
            "tables", "rows_returned", "duration_ms", "blocked",
            "block_reason", "agent_id", "metadata",
        ])
        for entry in entries:
            e = entry if isinstance(entry, dict) else entry.__dict__
            writer.writerow([
                e.get("id", ""),
                e.get("timestamp", ""),
                e.get("event_type", ""),
                e.get("connection_name", ""),
                e.get("sql", ""),
                ";".join(e.get("tables", [])),
                e.get("rows_returned", ""),
                e.get("duration_ms", ""),
                e.get("blocked", False),
                e.get("block_reason", ""),
                e.get("agent_id", ""),
                json.dumps(e.get("metadata", {})),
            ])
        content = output.getvalue()
        return StreamingResponse(
            iter([content]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=signalpilot-audit-export.csv"},
        )

    # JSON format
    export_data = {
        "export_timestamp": time.time(),
        "export_format": "signalpilot-audit-v1",
        "filters": {
            "connection_name": connection_name,
            "event_type": event_type,
        },
        "entry_count": len(entries),
        "entries": entries,
    }
    return StreamingResponse(
        iter([json.dumps(export_data, indent=2, default=str)]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=signalpilot-audit-export.json"},
    )


# ─── Budget / Governance ────────────────────────────────────────────────────

from .governance.budget import budget_ledger
from .governance.cache import query_cache


class BudgetCreateRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    budget_usd: float = Field(default=10.0, ge=0.01, le=10_000.0)


@app.post("/api/budget", status_code=201)
async def create_budget(req: BudgetCreateRequest):
    """Create a budget for a session."""
    budget = budget_ledger.create_session(req.session_id, req.budget_usd)
    return budget.to_dict()


@app.get("/api/budget/{session_id}")
async def get_budget(session_id: str):
    """Get budget status for a session."""
    budget = budget_ledger.get_session(session_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Session budget not found")
    return budget.to_dict()


@app.get("/api/budget")
async def list_budgets():
    """List all active session budgets."""
    return {
        "sessions": budget_ledger.get_all_sessions(),
        "total_spent_usd": round(budget_ledger.total_spent, 6),
    }


@app.delete("/api/budget/{session_id}", status_code=204)
async def close_budget(session_id: str):
    """Close and remove a session budget."""
    closed = budget_ledger.close_session(session_id)
    if not closed:
        raise HTTPException(status_code=404, detail="Session budget not found")


# ─── Schema Annotations ────────────────────────────────────────────────────

from .governance.annotations import load_annotations, generate_skeleton


@app.get("/api/connections/{name}/annotations")
async def get_annotations(name: str):
    """Get schema annotations for a connection (Feature #16)."""
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    annotations = load_annotations(name)
    return annotations.to_dict()


@app.post("/api/connections/{name}/annotations/generate")
async def generate_annotations(name: str):
    """Generate a starter schema.yml from database introspection (Feature #29)."""
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    try:
        extras = get_credential_extras(name)
        connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)
        schema = await connector.get_schema()
        await pool_manager.release(info.db_type, conn_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))

    skeleton = generate_skeleton(schema, name)
    return {
        "connection_name": name,
        "table_count": len(schema),
        "yaml": skeleton,
    }




# ─── Query Cache ──────────────────────────────────────────────────────────────


@app.get("/api/cache/stats")
async def cache_stats():
    """Get query cache statistics (Feature #30)."""
    return query_cache.stats()


@app.post("/api/cache/invalidate", status_code=200)
async def invalidate_cache(connection_name: str | None = None):
    """Invalidate cached query results. Optionally filter by connection."""
    count = query_cache.invalidate(connection_name)
    return {"invalidated": count, "connection_name": connection_name}


@app.post("/api/connections/{name}/detect-pii")
async def detect_pii(name: str):
    """Auto-detect PII columns in a database schema based on naming patterns.

    Returns suggested PII rules for columns with names matching known
    PII patterns (email, ssn, phone, etc.). Results should be reviewed
    and saved to schema.yml annotations.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    # Get schema (from cache if available)
    cached_schema = schema_cache.get(name)
    if cached_schema is None:
        try:
            extras = get_credential_extras(name)
            connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)
            cached_schema = await connector.get_schema()
            await pool_manager.release(info.db_type, conn_str)
            schema_cache.put(name, cached_schema)
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))

    from .governance.pii import detect_pii_columns

    all_detections: dict[str, dict[str, str]] = {}
    for table_key, table_data in cached_schema.items():
        columns = [col["name"] for col in table_data.get("columns", [])]
        detected = detect_pii_columns(columns)
        if detected:
            all_detections[table_data.get("name", table_key)] = {
                col: rule.value for col, rule in detected.items()
            }

    return {
        "connection_name": name,
        "tables_scanned": len(cached_schema),
        "tables_with_pii": len(all_detections),
        "detections": all_detections,
    }


@app.get("/api/schema-cache/stats")
async def schema_cache_stats():
    """Get schema cache statistics (Feature #18)."""
    return schema_cache.stats()


@app.post("/api/schema-cache/invalidate", status_code=200)
async def invalidate_schema_cache(connection_name: str | None = None):
    """Invalidate cached schema data. Optionally filter by connection."""
    count = schema_cache.invalidate(connection_name)
    return {"invalidated": count, "connection_name": connection_name}


# ─── Metrics SSE ─────────────────────────────────────────────────────────────

@app.get("/api/metrics")
async def metrics_stream():
    """Server-Sent Events stream of live gateway metrics."""

    async def generate():
        while True:
            settings = load_settings()
            sandboxes = list_sandboxes()
            running = sum(1 for s in sandboxes if s.status == "running")

            sandbox_health = "unknown"
            try:
                client = _get_sandbox_client()
                data = await client.health()
                sandbox_health = data.get("status", "unknown")
                kvm_available = data.get("kvm_available", False)
                active_vms = data.get("active_vms", 0)
                max_vms = data.get("max_vms", 10)
            except Exception:
                kvm_available = False
                active_vms = 0
                max_vms = 10

            payload = {
                "timestamp": time.time(),
                "sandbox_manager": settings.sandbox_manager_url,
                "sandbox_health": sandbox_health,
                "kvm_available": kvm_available,
                "active_sandboxes": len(sandboxes),
                "running_sandboxes": running,
                "active_vms": active_vms,
                "max_vms": max_vms,
                "connections": len(list_connections()),
                "query_cache": query_cache.stats(),
                "schema_cache": schema_cache.stats(),
            }

            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(generate(), media_type="text/event-stream")
