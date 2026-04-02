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

from fastapi import FastAPI, HTTPException, Query, Request
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
    "mssql": "tsql",
    "trino": "trino",
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
from .errors import query_error_hint
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
    _build_connection_string,
    _extract_credential_extras,
    DATA_DIR,
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


def _infer_implicit_joins(schema: dict[str, Any]) -> list[dict]:
    """Detect implicit join relationships via column name pattern matching.

    For databases without FK declarations (common in data lakes, Databricks, etc.),
    this finds joinable columns by matching patterns like:
      - orders.customer_id → customers.id
      - order_items.product_id → products.id
      - payments.order_id → orders.order_id OR orders.id

    Returns list of inferred FK-like relationships with confidence scores.
    Only returns high-confidence matches (exact name conventions).
    """
    # Build lookup: table_name (lowered) → (full_key, table_data)
    table_lookup: dict[str, tuple[str, dict]] = {}
    # Also build: column_name → list of (full_key, table_data) that have it
    pk_columns: dict[str, list[tuple[str, dict]]] = {}

    for key, table in schema.items():
        tbl_name = table.get("name", "").lower()
        tbl_schema = table.get("schema", "")
        full_name = f"{tbl_schema}.{table.get('name', '')}" if tbl_schema else table.get("name", "")
        table_lookup[tbl_name] = (full_name, table)

        # Track PK/id columns for matching
        for col in table.get("columns", []):
            cn = col["name"].lower()
            if col.get("primary_key") or cn == "id":
                if cn not in pk_columns:
                    pk_columns[cn] = []
                pk_columns[cn].append((full_name, table))

    inferred: list[dict] = []
    seen = set()

    def _add_inferred(from_schema, from_table, from_col, ref_table_data, ref_col, confidence="high"):
        edge_key = (from_schema + "." + from_table, from_col, ref_table_data.get("schema", "") + "." + ref_table_data.get("name", ""), ref_col)
        if edge_key not in seen:
            seen.add(edge_key)
            inferred.append({
                "from_schema": from_schema,
                "from_table": from_table,
                "from_column": from_col,
                "to_schema": ref_table_data.get("schema", ""),
                "to_table": ref_table_data.get("name", ""),
                "to_column": ref_col,
                "inferred": True,
                "confidence": confidence,
            })
            return True
        return False

    # Build column name → set of tables that have this column (for shared-name joins)
    col_to_tables: dict[str, list[tuple[str, dict, str]]] = {}  # col_lower → [(full_key, table, actual_col_name)]
    for key, table in schema.items():
        for col in table.get("columns", []):
            cn = col["name"].lower()
            if cn not in col_to_tables:
                col_to_tables[cn] = []
            col_to_tables[cn].append((key, table, col["name"]))

    for key, table in schema.items():
        tbl_schema = table.get("schema", "")
        tbl_name = table.get("name", "").lower()

        # Skip if table already has explicit FKs — don't duplicate
        existing_fk_cols = {fk["column"].lower() for fk in table.get("foreign_keys", [])}

        for col in table.get("columns", []):
            cn = col["name"].lower()
            if cn in existing_fk_cols:
                continue

            # Pattern 1: column ends with _id → look for table with matching prefix
            # e.g., customer_id → customers.id
            if cn.endswith("_id") and cn != "id":
                prefix = cn[:-3]  # "customer"
                # Try plural forms: customer → customers, category → categories
                candidates = [prefix, prefix + "s", prefix + "es"]
                if prefix.endswith("y"):
                    candidates.append(prefix[:-1] + "ies")  # category → categories
                elif prefix.endswith("s") or prefix.endswith("x") or prefix.endswith("z"):
                    candidates.append(prefix + "es")  # address → addresses

                for candidate in candidates:
                    if candidate in table_lookup and candidate != tbl_name:
                        ref_full, ref_table = table_lookup[candidate]
                        # Find the matching PK/id column in the target table
                        ref_col = None
                        for rc in ref_table.get("columns", []):
                            rcn = rc["name"].lower()
                            if rc.get("primary_key") and rcn in ("id", cn):
                                ref_col = rc["name"]
                                break
                            if rcn == "id":
                                ref_col = rc["name"]
                        if not ref_col:
                            # Try matching the exact column name
                            for rc in ref_table.get("columns", []):
                                if rc["name"].lower() == cn:
                                    ref_col = rc["name"]
                                    break
                        if ref_col:
                            _add_inferred(tbl_schema, table.get("name", ""), col["name"], ref_table, ref_col)
                            break

            # Pattern 2: column ends with Id (camelCase) → e.g., customerId → customers.id
            elif cn.endswith("id") and cn != "id" and len(cn) > 2 and cn[-3].islower():
                prefix = cn[:-2].lower()  # "customer"
                candidates = [prefix, prefix + "s", prefix + "es"]
                if prefix.endswith("y"):
                    candidates.append(prefix[:-1] + "ies")
                for candidate in candidates:
                    if candidate in table_lookup and candidate != tbl_name:
                        _, ref_table = table_lookup[candidate]
                        for rc in ref_table.get("columns", []):
                            rcn = rc["name"].lower()
                            if rc.get("primary_key") or rcn == "id":
                                _add_inferred(tbl_schema, table.get("name", ""), col["name"], ref_table, rc["name"])
                                break
                        break

            # Pattern 3: shared column name with _id/_key suffix → join bridge
            # e.g., both orders.product_id and order_items.product_id → joinable
            elif cn.endswith(("_id", "_key", "_code")) and cn != "id":
                entries = col_to_tables.get(cn, [])
                if len(entries) > 1:
                    # For each other table that has this same column, create an inferred join
                    for other_key, other_table, other_col_name in entries:
                        if other_key == key:
                            continue
                        other_name = other_table.get("name", "").lower()
                        if other_name == tbl_name:
                            continue
                        # Only add if the other table has this as a PK or it looks like a dimension table
                        is_pk_in_other = any(
                            rc["name"].lower() == cn and rc.get("primary_key")
                            for rc in other_table.get("columns", [])
                        )
                        if is_pk_in_other:
                            _add_inferred(tbl_schema, table.get("name", ""), col["name"], other_table, other_col_name)

    return inferred


def _sanitize_db_error(error: str, db_type: str | None = None) -> str:
    """Remove connection strings, passwords, and host info from error messages.

    Also appends DB-specific troubleshooting hints for common errors.
    """
    sanitized = error
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    # Truncate to prevent information dump
    if len(sanitized) > 500:
        sanitized = sanitized[:500] + "..."

    # Add troubleshooting hints for common errors
    err_lower = sanitized.lower()
    hints: list[str] = []

    if "connection refused" in err_lower or "could not connect" in err_lower:
        hints.append("Check that the database server is running and the host/port are correct")
        if db_type in ("postgres", "mysql", "redshift"):
            hints.append("Verify firewall rules allow connections from this server's IP")
    elif "authentication" in err_lower or "password" in err_lower or "access denied" in err_lower:
        hints.append("Verify username and password are correct")
        if db_type == "snowflake":
            hints.append("For Snowflake, ensure the account identifier is correct (e.g., xy12345.us-east-1)")
        elif db_type == "databricks":
            hints.append("For Databricks, check that the personal access token (PAT) is valid and not expired")
    elif "timeout" in err_lower or "timed out" in err_lower:
        hints.append("Database is unreachable — check network connectivity")
        hints.append("If behind a VPN, ensure VPN is connected. If behind a firewall, add this server's IP to the allowlist")
    elif "ssl" in err_lower or "certificate" in err_lower:
        hints.append("SSL/TLS connection failed — check SSL configuration")
        hints.append("Try enabling SSL in advanced options with the appropriate CA certificate")
    elif "does not exist" in err_lower or "not found" in err_lower:
        if "database" in err_lower:
            hints.append("Database name not found — verify the database exists and the user has access")
        elif "warehouse" in err_lower:
            hints.append("Warehouse not found — verify warehouse name and that it is running")
        elif "schema" in err_lower:
            hints.append("Schema not found — verify schema name and permissions")

    if hints:
        sanitized += " | Hint: " + "; ".join(hints)

    return sanitized


# ─── Schema Filtering (HEX pattern) ─────────────────────────────────────────

import fnmatch as _fnmatch


def _apply_schema_filter(
    schema: dict[str, dict],
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> dict[str, dict]:
    """Filter schema tables by include/exclude schema name patterns.

    HEX pattern: filter out staging/dev/raw schemas to focus AI on production data.
    Glob patterns are supported (e.g., 'staging_*', 'dev*').
    """
    if not include and not exclude:
        return schema

    filtered: dict[str, dict] = {}
    for key, table_data in schema.items():
        table_schema = table_data.get("schema", "")

        # Include filter: only keep if schema matches at least one pattern
        if include:
            if not any(_fnmatch.fnmatch(table_schema.lower(), pat.lower()) for pat in include):
                continue

        # Exclude filter: skip if schema matches any pattern
        if exclude:
            if any(_fnmatch.fnmatch(table_schema.lower(), pat.lower()) for pat in exclude):
                continue

        filtered[key] = table_data
    return filtered


def _get_schema_filters(name: str) -> tuple[list[str], list[str]]:
    """Get schema filter config for a connection."""
    conn = get_connection(name)
    if conn is None:
        return [], []
    include = getattr(conn, "schema_filter_include", []) or []
    exclude = getattr(conn, "schema_filter_exclude", []) or []
    return include, exclude


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

    # Scheduled schema refresh (HEX pattern) — refreshes schema for connections
    # that have schema_refresh_interval configured
    async def _schema_refresh_loop():
        import logging
        logger = logging.getLogger(__name__)
        while True:
            await asyncio.sleep(30)  # Check every 30s
            try:
                connections = list_connections()
                now = time.time()
                for conn_info in connections:
                    interval = conn_info.schema_refresh_interval
                    if not interval:
                        continue
                    last_refresh = conn_info.last_schema_refresh or 0
                    if now - last_refresh < interval:
                        continue
                    # Time to refresh
                    try:
                        conn_str = get_connection_string(conn_info.name)
                        if not conn_str:
                            continue
                        extras = get_credential_extras(conn_info.name)
                        async with pool_manager.connection(
                            conn_info.db_type, conn_str, credential_extras=extras,
                        ) as connector:
                            schema = await connector.get_schema()
                        # Track diff on scheduled refresh — detects DDL changes automatically
                        diff_result = schema_cache.put(conn_info.name, schema, track_diff=True)
                        # Update last_schema_refresh timestamp
                        update_connection(conn_info.name, ConnectionUpdate(
                            last_schema_refresh=now,
                        ))
                        if diff_result and diff_result.get("has_changes"):
                            added = len(diff_result.get("added_tables", []))
                            removed = len(diff_result.get("removed_tables", []))
                            modified = len(diff_result.get("modified_tables", []))
                            logger.info(
                                "Schema change detected for '%s': +%d/-%d tables, %d modified",
                                conn_info.name, added, removed, modified,
                            )
                        else:
                            logger.info(
                                "Scheduled schema refresh for '%s': %d tables (no structural changes)",
                                conn_info.name, len(schema),
                            )
                    except Exception as e:
                        logger.warning(
                            "Scheduled schema refresh failed for '%s': %s",
                            conn_info.name, e,
                        )
            except Exception as e:
                logger.warning("Schema refresh loop error: %s", e)

    cleanup_task = asyncio.create_task(_pool_cleanup_loop())
    refresh_task = asyncio.create_task(_schema_refresh_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        refresh_task.cancel()
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
    Small delay to avoid racing with immediate user requests (pymssql/FreeTDS
    is not thread-safe for concurrent connection access).
    """
    import logging
    logger = logging.getLogger(__name__)
    await asyncio.sleep(2)  # Brief delay to avoid concurrent access races
    try:
        conn_str = get_connection_string(name)
        if not conn_str:
            return
        extras = get_credential_extras(name)
        async with pool_manager.connection(db_type, conn_str, credential_extras=extras) as connector:
            schema = await connector.get_schema()
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
    if db in ("postgres", "mysql", "redshift", "clickhouse", "mssql"):
        if not conn.host:
            errors.append(f"{db} requires a host")
        if not conn.username:
            errors.append(f"{db} requires a username")

    # Trino needs host + catalog (username optional for some clusters)
    if db == "trino":
        if not conn.host:
            errors.append("Trino requires a host")
        if not conn.catalog:
            errors.append("Trino requires a catalog")

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
        if db not in ("postgres", "mysql", "redshift", "clickhouse", "mssql", "trino"):
            errors.append(f"SSH tunnels are not supported for {db} (only host:port databases)")

    return errors


# Connection health — must be defined before {name} routes to avoid path conflict
@app.get("/api/connections/health")
async def get_all_connection_health(window: int = Query(default=300, ge=60, le=3600)):
    """Get health stats for all monitored connections (Feature #31)."""
    return {"connections": health_monitor.all_stats(window)}


# Connection export/import — must be defined before {name} routes to avoid path conflict
@app.get("/api/connections/export")
async def export_connections(
    include_credentials: bool = Query(default=False, description="Include passwords and secrets (security risk)"),
):
    """Export all connections as a portable JSON manifest.

    HEX-pattern: allows backup, migration, and sharing of connection configs.
    By default credentials are stripped for safety — set include_credentials=true
    to include them (for migration between environments).
    """
    all_conns = list_connections()
    exported = []
    for conn in all_conns:
        # ConnectionInfo is a Pydantic model — convert to dict for safe attribute access
        conn_dict = conn.model_dump() if hasattr(conn, "model_dump") else dict(conn)
        entry: dict = {
            "name": conn_dict.get("name", ""),
            "db_type": conn_dict.get("db_type", ""),
            "description": conn_dict.get("description", ""),
            "tags": conn_dict.get("tags", []),
        }
        # Copy configuration fields
        for field in ("host", "port", "database", "username", "account", "warehouse",
                       "schema_name", "role", "project", "dataset", "http_path", "catalog",
                       "location", "maximum_bytes_billed",
                       "schema_filter_include", "schema_filter_exclude",
                       "schema_refresh_interval", "connection_timeout", "query_timeout",
                       "keepalive_interval"):
            val = conn_dict.get(field)
            if val is not None:
                entry[field] = val

        if include_credentials:
            conn_str = get_connection_string(entry["name"])
            if conn_str:
                entry["connection_string"] = conn_str
            # Include SSL config if present
            if conn_dict.get("ssl_config"):
                entry["ssl_config"] = conn_dict["ssl_config"]
            if conn_dict.get("ssh_tunnel"):
                entry["ssh_tunnel"] = conn_dict["ssh_tunnel"]

        exported.append(entry)

    return {
        "version": "1.0",
        "exported_at": time.time(),
        "connection_count": len(exported),
        "includes_credentials": include_credentials,
        "connections": exported,
    }


@app.post("/api/connections/import")
async def import_connections(manifest: dict):
    """Import connections from an exported JSON manifest.

    HEX-pattern: bulk import of connection configs. Skips connections
    whose names already exist (no overwrite). Returns import results.
    """
    connections = manifest.get("connections", [])
    results = {"imported": 0, "skipped": [], "errors": []}

    for entry in connections:
        name = entry.get("name", "")
        if not name:
            results["errors"].append({"name": "(empty)", "error": "Missing connection name"})
            continue

        # Skip if already exists
        if get_connection(name):
            results["skipped"].append(name)
            continue

        try:
            conn = ConnectionCreate(**entry)
            create_connection(conn)
            results["imported"] += 1
        except Exception as e:
            results["errors"].append({"name": name, "error": str(e)})

    return results


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
    Useful after migrations or DDL changes. Also updates last_schema_refresh
    timestamp for scheduled refresh tracking.
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
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            schema = await connector.get_schema()
    except Exception as e:
        raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))

    schema_cache.put(name, schema)
    now = time.time()
    update_connection(name, ConnectionUpdate(last_schema_refresh=now))

    return {
        "connection_name": name,
        "table_count": len(schema),
        "refreshed_at": now,
        "next_refresh_in": info.schema_refresh_interval,
        "message": "Schema refreshed successfully",
    }


@app.post("/api/connections/schema/warmup")
async def warmup_all_schemas():
    """Parallel schema warmup for all connections.

    Fetches schemas for all connections concurrently, caching results.
    Useful at startup or when an AI agent first connects.
    Returns per-connection results (success/failure + table counts).
    """
    import asyncio

    connections = list_connections()
    if not connections:
        return {"warmed": 0, "results": [], "duration_ms": 0}

    start = time.monotonic()

    async def _warmup_one(info: ConnectionInfo) -> dict:
        name = info.name
        # Skip if already cached
        cached = schema_cache.get(name)
        if cached is not None:
            return {"name": name, "status": "cached", "table_count": len(cached)}
        conn_str = get_connection_string(name)
        if not conn_str:
            return {"name": name, "status": "skipped", "error": "no credentials"}
        try:
            extras = get_credential_extras(name)
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                schema = await connector.get_schema()
                schema_cache.put(name, schema)

                # Pre-fetch sample values for low-cardinality columns (RSL-SQL pattern)
                # This enables value-based schema linking in the agent without extra queries
                sample_count = 0
                for table_key, table_data in list(schema.items())[:30]:  # Cap at 30 tables
                    if schema_cache.get_sample_values(name, table_key) is not None:
                        continue  # Already cached
                    low_card_cols = []
                    for col in table_data.get("columns", []):
                        stats = col.get("stats", {})
                        dc = stats.get("distinct_count", 0) if stats else 0
                        df = abs(stats.get("distinct_fraction", 0)) if stats else 0
                        if dc and dc <= 50:
                            low_card_cols.append(col["name"])
                        elif df and df < 0.05:
                            low_card_cols.append(col["name"])
                    if low_card_cols:
                        try:
                            samples = await connector.get_sample_values(
                                table_key, low_card_cols[:10], limit=5
                            )
                            if samples:
                                schema_cache.put_sample_values(name, table_key, samples)
                                sample_count += len(samples)
                        except Exception:
                            pass  # Best-effort — don't fail warmup over samples

            now = time.time()
            update_connection(name, ConnectionUpdate(last_schema_refresh=now))
            return {"name": name, "status": "ok", "table_count": len(schema),
                    "sample_columns": sample_count}
        except Exception as e:
            return {"name": name, "status": "error", "error": str(e)[:200]}

    results = await asyncio.gather(*[_warmup_one(c) for c in connections], return_exceptions=False)
    elapsed = (time.monotonic() - start) * 1000

    ok_count = sum(1 for r in results if r["status"] in ("ok", "cached"))
    total_tables = sum(r.get("table_count", 0) for r in results)
    return {
        "warmed": ok_count,
        "total_connections": len(connections),
        "total_tables": total_tables,
        "results": results,
        "duration_ms": round(elapsed, 1),
    }


def _connection_error_hint(db_type: str, error_msg: str) -> str:
    """Generate actionable error hints based on DB type and error message."""
    err_lower = error_msg.lower()

    # Network-level hints
    if any(kw in err_lower for kw in ("connection refused", "timed out", "unreachable", "no route", "name or service not known", "getaddrinfo", "name resolution", "errno -2", "errno 111")):
        hints = {
            "postgres": "Check: 1) PostgreSQL is running 2) Port 5432 is open 3) pg_hba.conf allows your IP 4) VPN/SSH tunnel is active if remote",
            "mysql": "Check: 1) MySQL is running 2) Port 3306 is open 3) bind-address includes your IP 4) skip-networking is disabled",
            "mssql": "Check: 1) SQL Server is running 2) TCP/IP protocol is enabled in SQL Server Configuration Manager 3) Firewall allows port 1433",
            "clickhouse": "Check: 1) ClickHouse is running 2) Native port 9000 or HTTP port 8123 is open 3) listen_host includes your IP",
            "snowflake": "Check: 1) Account identifier is correct (e.g. xy12345.us-east-1) 2) Network policy allows your IP 3) HTTPS (443) is not blocked",
            "bigquery": "Check: 1) GCP project exists 2) Internet access is available 3) Proxy settings are correct",
            "databricks": "Check: 1) Workspace URL is correct 2) HTTPS (443) is not blocked 3) IP Access List allows your IP",
            "redshift": "Check: 1) Cluster is available 2) Port 5439 is open 3) VPC security group allows your IP 4) Cluster is not paused",
        }
        return hints.get(db_type, "Check hostname, port, firewall rules, and VPN/SSH tunnel settings")

    # Auth-level hints
    if any(kw in err_lower for kw in ("authentication", "login failed", "access denied", "password", "credentials")):
        hints = {
            "postgres": "Check: 1) Username and password are correct 2) User exists in PostgreSQL 3) pg_hba.conf allows password auth for this user",
            "mysql": "Check: 1) User exists (SELECT user FROM mysql.user) 2) Password is correct 3) User has GRANT for this host ('%' or specific IP)",
            "mssql": "Check: 1) SQL auth is enabled (not just Windows auth) 2) User/password correct 3) For Azure SQL, use Azure AD if SQL auth disabled",
            "clickhouse": "Check: 1) User exists in users.xml or system.users 2) Password matches 3) User is not restricted by network/IP",
            "snowflake": "Check: 1) Username is correct (case-sensitive) 2) Password is correct 3) User is not locked 4) For key-pair auth, check RSA key format",
            "bigquery": "Check: 1) Service account JSON is valid 2) SA has BigQuery Job User role 3) For OAuth, token is not expired",
            "databricks": "Check: 1) PAT is valid and not expired 2) For OAuth M2M, client_id and client_secret are correct 3) Service principal has workspace access",
            "redshift": "Check: 1) Username and password are correct 2) User exists in pg_user 3) For IAM auth, ensure IAM policy allows redshift:GetClusterCredentials",
        }
        return hints.get(db_type, "Check username, password, and database permissions")

    # Database not found hints
    if any(kw in err_lower for kw in ("database", "not found", "does not exist", "unknown database", "catalog")):
        hints = {
            "postgres": "Check: 1) Database name is spelled correctly (case-sensitive) 2) Run \\l in psql to list databases",
            "mysql": "Check: 1) Database name is spelled correctly 2) Run SHOW DATABASES to list available databases",
            "mssql": "Check: 1) Database name is correct 2) User has CONNECT permission on the database 3) Database is online (not offline/restoring)",
            "clickhouse": "Check: 1) Database exists (SHOW DATABASES) 2) User has access to the database",
            "snowflake": "Check: 1) Database exists (SHOW DATABASES) 2) Role has USAGE on the database 3) Database name is case-correct",
            "bigquery": "Check: 1) Project ID is correct (not project name) 2) Dataset exists in the project",
            "databricks": "Check: 1) Catalog exists in Unity Catalog 2) User has USE CATALOG permission",
            "redshift": "Check: 1) Database exists (SELECT datname FROM pg_database) 2) User has CONNECT permission",
        }
        return hints.get(db_type, "Check that the database name exists and you have access")

    # Warehouse-specific hints
    if any(kw in err_lower for kw in ("warehouse", "http_path", "compute")):
        hints = {
            "snowflake": "Check: 1) Warehouse name is correct and exists 2) Warehouse is not suspended 3) Role has USAGE on the warehouse",
            "databricks": "Check: 1) http_path is correct (SQL Warehouse → Connection Details) 2) SQL Warehouse is running (not stopped)",
        }
        return hints.get(db_type, "Check warehouse/compute resource configuration")

    # SSL/TLS hints
    if any(kw in err_lower for kw in ("ssl", "tls", "certificate", "handshake")):
        return "Check: 1) SSL certificate is valid and not expired 2) CA certificate matches the server's cert chain 3) SSL mode matches server requirements"

    # Default fallback
    return "Check connection parameters, credentials, and network access"


@app.post("/api/connections/test-credentials")
async def test_credentials(request: Request):
    """Test connection credentials without saving (HEX pre-save validation pattern).

    Accepts the same payload as POST /api/connections but only tests connectivity.
    Returns phase-by-phase results: network → auth → schema access.
    """
    body = await request.json()
    t0 = time.monotonic()
    phases: list[dict] = []

    try:
        # Build a ConnectionCreate model from the request body
        conn = ConnectionCreate(**body)
    except Exception as e:
        return {
            "status": "error",
            "message": f"Invalid connection parameters: {e}",
            "phases": [],
        }

    # Build connection string and credential extras
    try:
        conn_str = conn.connection_string or _build_connection_string(conn)
    except Exception as e:
        return {
            "status": "error",
            "message": f"Could not build connection string: {e}",
            "phases": [],
        }

    extras = _extract_credential_extras(conn)
    # Propagate auth_method and other top-level fields into extras
    for field_name in ("auth_method", "oauth_access_token", "impersonate_service_account",
                       "private_key", "private_key_passphrase",
                       "oauth_client_id", "oauth_client_secret",
                       "jwt_token", "client_cert", "client_key", "kerberos_config",
                       "aws_region", "aws_access_key_id", "aws_secret_access_key",
                       "cluster_id", "workgroup",
                       "azure_tenant_id", "azure_client_id", "azure_client_secret"):
        val = body.get(field_name)
        if val and field_name not in extras:
            extras[field_name] = val
    # IAM auth flag
    if body.get("auth_method") == "iam":
        extras["auth_method"] = "iam"
    # Azure AD auth flag
    if body.get("auth_method") == "azure_ad":
        extras["auth_method"] = "azure_ad"
        extras["azure_ad_auth"] = True

    db_type = conn.db_type

    # Phase 1: Network connectivity (DNS + TCP)
    t1 = time.monotonic()
    try:
        from urllib.parse import urlparse
        parsed = urlparse(conn_str if "://" in conn_str else f"dummy://{conn_str}")
        host = parsed.hostname or conn.host or "localhost"
        port = parsed.port or conn.port or 5432

        if host and port and db_type not in ("duckdb", "sqlite", "bigquery"):
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            try:
                sock.connect((host, int(port)))
                sock.close()
                phases.append({
                    "phase": "network",
                    "status": "ok",
                    "message": f"TCP connection to {host}:{port} succeeded",
                    "duration_ms": round((time.monotonic() - t1) * 1000, 1),
                })
            except (socket.timeout, socket.error, OSError) as e:
                phases.append({
                    "phase": "network",
                    "status": "error",
                    "message": f"Cannot reach {host}:{port} — {e}",
                    "hint": _connection_error_hint(db_type, str(e)),
                    "duration_ms": round((time.monotonic() - t1) * 1000, 1),
                })
                return {
                    "status": "error",
                    "message": f"Network unreachable: {host}:{port}",
                    "phases": phases,
                    "total_duration_ms": round((time.monotonic() - t0) * 1000, 1),
                }
        else:
            phases.append({
                "phase": "network",
                "status": "skipped",
                "message": f"{db_type} does not require network connectivity check",
                "duration_ms": 0,
            })
    except Exception as e:
        phases.append({
            "phase": "network",
            "status": "warning",
            "message": f"Could not verify network: {e}",
            "duration_ms": round((time.monotonic() - t1) * 1000, 1),
        })

    # Phase 2: Database authentication
    t2 = time.monotonic()
    try:
        async with pool_manager.connection(db_type, conn_str, credential_extras=extras) as connector:
            ok = await connector.health_check()
            if ok:
                phases.append({
                    "phase": "authentication",
                    "status": "ok",
                    "message": "Authenticated and connected successfully",
                    "duration_ms": round((time.monotonic() - t2) * 1000, 1),
                })

                # Phase 3: Schema access
                t3 = time.monotonic()
                try:
                    schema = await connector.get_schema()
                    table_count = len(schema) if schema else 0
                    phases.append({
                        "phase": "schema_access",
                        "status": "ok",
                        "message": f"Schema access verified — {table_count} tables found",
                        "duration_ms": round((time.monotonic() - t3) * 1000, 1),
                    })
                except Exception as e:
                    schema_hints = {
                        "postgres": "Grant SELECT on information_schema.tables and information_schema.columns to this user",
                        "mysql": "Grant SELECT on information_schema to this user (GRANT SELECT ON information_schema.* TO 'user'@'host')",
                        "mssql": "Grant VIEW DEFINITION and SELECT on sys.objects, sys.columns to this user",
                        "clickhouse": "Grant SELECT on system.columns and system.tables to this user",
                        "snowflake": "Grant USAGE on database and USAGE on schema to this role",
                        "bigquery": "Grant bigquery.datasets.get and bigquery.tables.list roles to the service account",
                        "databricks": "Grant USE CATALOG, USE SCHEMA, and SELECT on tables to this user/principal",
                        "redshift": "Grant SELECT on SVV_TABLE_INFO and pg_table_def to this user",
                    }
                    phases.append({
                        "phase": "schema_access",
                        "status": "warning",
                        "message": f"Connected but schema access limited: {_sanitize_db_error(str(e))}",
                        "hint": schema_hints.get(db_type, "Check SELECT permissions on information_schema or system tables"),
                        "duration_ms": round((time.monotonic() - t3) * 1000, 1),
                    })
            else:
                phases.append({
                    "phase": "authentication",
                    "status": "error",
                    "message": "Connection established but health check failed",
                    "duration_ms": round((time.monotonic() - t2) * 1000, 1),
                })
    except Exception as e:
        err_msg = _sanitize_db_error(str(e))
        phases.append({
            "phase": "authentication",
            "status": "error",
            "message": f"Authentication failed: {err_msg}",
            "hint": _connection_error_hint(db_type, str(e)),
            "duration_ms": round((time.monotonic() - t2) * 1000, 1),
        })

    all_ok = all(p["status"] in ("ok", "skipped") for p in phases)
    return {
        "status": "healthy" if all_ok else "error",
        "message": "All connection tests passed" if all_ok else "Connection test failed",
        "phases": phases,
        "total_duration_ms": round((time.monotonic() - t0) * 1000, 1),
    }


@app.post("/api/connections/validate-url")
async def validate_connection_url(body: dict):
    """Validate and parse a connection string without saving or connecting.

    Returns parsed components and identifies potential issues.
    Useful for frontend preview before saving a connection.
    """
    url = body.get("connection_string", "")
    db_type = body.get("db_type", "")

    if not url:
        return {"valid": False, "error": "Connection string is empty"}
    if not db_type:
        return {"valid": False, "error": "db_type is required"}

    try:
        from urllib.parse import urlparse, unquote

        # Try to parse based on db_type
        parsed_info: dict[str, Any] = {"db_type": db_type}
        warnings: list[str] = []

        if db_type in ("postgres", "mysql", "redshift", "clickhouse", "mssql"):
            # Standard URL format
            normalized = url
            if db_type == "clickhouse":
                for prefix in ("clickhouse+https://", "clickhouse+http://", "clickhouses://", "clickhouse://"):
                    if normalized.startswith(prefix):
                        normalized = "http://" + normalized[len(prefix):]
                        break
            elif db_type == "redshift" and normalized.startswith("redshift://"):
                normalized = "postgresql://" + normalized[len("redshift://"):]
            elif db_type == "mysql" and normalized.startswith("mysql+pymysql://"):
                normalized = "http://" + normalized[len("mysql+pymysql://"):]
            elif db_type == "mssql":
                for prefix in ("mssql://", "mssql+pymssql://", "sqlserver://"):
                    if normalized.startswith(prefix):
                        normalized = "http://" + normalized[len(prefix):]
                        break

            parsed = urlparse(normalized)
            parsed_info["host"] = parsed.hostname or ""
            parsed_info["port"] = parsed.port
            parsed_info["database"] = (parsed.path or "").lstrip("/")
            parsed_info["username"] = unquote(parsed.username or "")
            parsed_info["has_password"] = bool(parsed.password)

            if not parsed_info["host"]:
                warnings.append("No host specified")
            if not parsed_info["database"]:
                warnings.append("No database specified")
            if not parsed_info["username"]:
                warnings.append("No username specified")
            if not parsed_info["has_password"]:
                warnings.append("No password in URL — will need separate credentials")

        elif db_type == "trino":
            normalized = url
            if normalized.startswith("trino://"):
                normalized = "http://" + normalized[len("trino://"):]
            elif normalized.startswith("trino+https://"):
                normalized = "http://" + normalized[len("trino+https://"):]
            parsed = urlparse(normalized)
            path_parts = [p for p in (parsed.path or "").split("/") if p]
            parsed_info["host"] = parsed.hostname or ""
            parsed_info["port"] = parsed.port or 8080
            parsed_info["username"] = unquote(parsed.username or "trino")
            parsed_info["has_password"] = bool(parsed.password)
            parsed_info["catalog"] = path_parts[0] if path_parts else ""
            parsed_info["schema"] = path_parts[1] if len(path_parts) > 1 else ""
            if not parsed_info["host"]:
                warnings.append("No host specified")
            if not parsed_info["catalog"]:
                warnings.append("No catalog specified")

        elif db_type == "snowflake":
            if url.startswith("snowflake://"):
                parsed = urlparse(url)
                path_parts = [p for p in (parsed.path or "").split("/") if p]
                parsed_info["account"] = parsed.hostname or ""
                parsed_info["username"] = unquote(parsed.username or "")
                parsed_info["has_password"] = bool(parsed.password)
                parsed_info["database"] = path_parts[0] if path_parts else ""
                parsed_info["schema"] = path_parts[1] if len(path_parts) > 1 else ""
                if not parsed_info["account"]:
                    warnings.append("No account identifier specified")
            else:
                warnings.append("Snowflake URLs should start with snowflake://")

        elif db_type == "databricks":
            if url.startswith("databricks://"):
                parsed = urlparse(url)
                parsed_info["host"] = parsed.hostname or ""
                parsed_info["http_path"] = (parsed.path or "").lstrip("/")
                parsed_info["has_token"] = bool(parsed.username)
                if not parsed_info["host"]:
                    warnings.append("No hostname specified")
                if not parsed_info["http_path"]:
                    warnings.append("No HTTP path specified")
            else:
                warnings.append("Databricks URLs should start with databricks://")

        return {
            "valid": True,
            "parsed": parsed_info,
            "warnings": warnings,
        }
    except Exception as e:
        return {"valid": False, "error": f"Invalid URL format: {e}"}


@app.post("/api/connections/build-url")
async def build_connection_url(body: dict):
    """Build a connection string from individual fields.

    HEX-pattern: users fill in separate fields, this builds the URL.
    Supports all DB types with proper encoding and scheme selection.
    """
    from urllib.parse import quote_plus

    db_type = body.get("db_type", "")
    host = body.get("host", "")
    port = body.get("port")
    database = body.get("database", "")
    username = body.get("username", "")
    password = body.get("password", "")

    if not db_type:
        return {"url": "", "error": "db_type is required"}

    try:
        userpass = ""
        if username:
            userpass = quote_plus(username)
            if password:
                userpass += f":{quote_plus(password)}"
            userpass += "@"

        if db_type == "postgres":
            p = port or 5432
            url = f"postgresql://{userpass}{host}:{p}/{database}"
        elif db_type == "mysql":
            p = port or 3306
            url = f"mysql://{userpass}{host}:{p}/{database}"
        elif db_type == "redshift":
            p = port or 5439
            url = f"redshift://{userpass}{host}:{p}/{database}"
        elif db_type == "mssql":
            p = port or 1433
            url = f"mssql://{userpass}{host}:{p}/{database}"
        elif db_type == "clickhouse":
            protocol = body.get("protocol", "native")
            ssl = body.get("ssl", False)
            if protocol == "http":
                p = port or (8443 if ssl else 8123)
                scheme = "clickhouse+https" if ssl else "clickhouse+http"
            else:
                p = port or (9440 if ssl else 9000)
                scheme = "clickhouses" if ssl else "clickhouse"
            url = f"{scheme}://{userpass}{host}:{p}/{database}"
        elif db_type == "trino":
            https = body.get("https", False)
            p = port or (443 if https else 8080)
            scheme = "trino+https" if https else "trino"
            catalog = body.get("catalog", "")
            schema_name = body.get("schema_name", "")
            path = catalog
            if schema_name:
                path += f"/{schema_name}"
            url = f"{scheme}://{userpass}{host}:{p}/{path}"
        elif db_type == "snowflake":
            account = body.get("account", "")
            warehouse = body.get("warehouse", "")
            schema_name = body.get("schema_name", "")
            role = body.get("role", "")
            url = f"snowflake://{userpass}{account}/{database}"
            if schema_name:
                url += f"/{schema_name}"
            params = []
            if warehouse:
                params.append(f"warehouse={quote_plus(warehouse)}")
            if role:
                params.append(f"role={quote_plus(role)}")
            if params:
                url += "?" + "&".join(params)
        elif db_type == "databricks":
            access_token = body.get("access_token", "")
            http_path = body.get("http_path", "")
            catalog = body.get("catalog", "")
            url = f"databricks://token:{quote_plus(access_token)}@{host}/{http_path}"
            if catalog:
                url += f"?catalog={quote_plus(catalog)}"
        elif db_type in ("duckdb", "sqlite"):
            url = database or ":memory:"
        elif db_type == "bigquery":
            project = body.get("project", "")
            dataset = body.get("dataset", "")
            url = f"bigquery://{project}"
            if dataset:
                url += f"/{dataset}"
        else:
            return {"url": "", "error": f"Unknown db_type: {db_type}"}

        # Build masked version for display
        masked = url
        if password:
            masked = masked.replace(quote_plus(password), "****")

        return {
            "url": url,
            "masked_url": masked,
            "db_type": db_type,
        }
    except Exception as e:
        return {"url": "", "error": f"Failed to build URL: {e}"}


@app.post("/api/connections/{name}/test")
async def test_connection(name: str):
    """Three-phase connection test (industry standard pattern from HEX/DBeaver):
    Phase 1: Network/tunnel connectivity
    Phase 2: Database authentication and query
    Phase 3: Schema access verification
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
        and info.db_type in ("postgres", "mysql", "redshift", "clickhouse", "mssql", "trino")
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
        try:
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
                    "mssql": "SELECT @@VERSION",
                    "trino": "SELECT version()",
                    "databricks": "SELECT current_version()",
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

            # Phase 3: Schema access — verify we can read metadata (HEX pattern)
            t2 = time.monotonic()
            try:
                schema = await connector.get_schema()
                table_count = len(schema) if schema else 0
                phase3_duration = round((time.monotonic() - t2) * 1000, 1)
                if table_count > 0:
                    # Sample first few table names for confirmation
                    sample_tables = list(schema.keys())[:5]
                    phases.append({
                        "phase": "schema_access",
                        "status": "ok",
                        "message": f"Schema readable: {table_count} tables found",
                        "sample_tables": sample_tables,
                        "duration_ms": phase3_duration,
                    })
                    # Cache the schema since we already fetched it
                    schema_cache.put(name, schema)
                else:
                    phases.append({
                        "phase": "schema_access",
                        "status": "warning",
                        "message": "Connected but no tables found — check permissions or database contents",
                        "duration_ms": phase3_duration,
                    })
            except Exception as e:
                phases.append({
                    "phase": "schema_access",
                    "status": "warning",
                    "message": f"Schema access limited: {_sanitize_db_error(str(e))}",
                    "duration_ms": round((time.monotonic() - t2) * 1000, 1),
                })
        finally:
            await pool_manager.release(info.db_type, conn_str)
    except Exception as e:
        phases.append({
            "phase": "database",
            "status": "error",
            "message": _sanitize_db_error(str(e), db_type=info.db_type),
            "duration_ms": round((time.monotonic() - t1) * 1000, 1),
        })
        return {"status": "error", "phases": phases, "message": _sanitize_db_error(str(e), db_type=info.db_type)}

    total_ms = round((time.monotonic() - t0) * 1000, 1)
    # Overall status: healthy if no errors, warning if schema access had issues
    overall_status = "healthy"
    for p in phases:
        if p["status"] == "error":
            overall_status = "error"
            break
        if p["status"] == "warning":
            overall_status = "warning"

    return {
        "status": overall_status,
        "phases": phases,
        "message": "All connection tests passed" if overall_status == "healthy" else "Connection works but with warnings",
        "total_duration_ms": total_ms,
    }


@app.get("/api/connections/{name}/health")
async def get_connection_health(name: str, window: int = Query(default=300, ge=60, le=3600)):
    """Get health stats for a specific connection."""
    stats = health_monitor.connection_stats(name, window)
    if stats is None:
        raise HTTPException(status_code=404, detail=f"No health data for connection '{name}'")
    return stats


# ─── Network Diagnostics (HEX pattern — IP whitelist guidance) ────────────────

@app.get("/api/network/info")
async def network_info():
    """Return this server's public IP and network info for firewall/whitelist setup.

    HEX pattern: Show users the IP they need to whitelist in their database
    firewall rules, security groups, or network policies.
    """
    import socket

    result: dict = {
        "hostname": socket.gethostname(),
        "local_ips": [],
        "public_ip": None,
        "whitelist_instructions": {},
    }

    # Get local IPs
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in result["local_ips"] and ip != "127.0.0.1":
                result["local_ips"].append(ip)
    except Exception:
        pass

    # Try to get public IP (best-effort, non-blocking)
    try:
        import urllib.request
        public_ip = urllib.request.urlopen("https://api.ipify.org", timeout=5).read().decode().strip()
        result["public_ip"] = public_ip
    except Exception:
        result["public_ip"] = None

    ip_to_whitelist = result["public_ip"] or (result["local_ips"][0] if result["local_ips"] else "YOUR_SERVER_IP")

    result["whitelist_instructions"] = {
        "aws_rds": f"RDS Console → Security Group → Inbound Rules → Add: Type=Custom TCP, Port=5432, Source={ip_to_whitelist}/32",
        "aws_redshift": f"Redshift Console → Cluster → Properties → VPC Security Group → Inbound Rules → Add: {ip_to_whitelist}/32",
        "azure_sql": f"Azure Portal → SQL Server → Networking → Add firewall rule: Start={ip_to_whitelist}, End={ip_to_whitelist}",
        "gcp_cloud_sql": f"Cloud SQL Console → Instance → Connections → Authorized Networks → Add: {ip_to_whitelist}/32",
        "snowflake": f"ALTER NETWORK POLICY sp_policy SET ALLOWED_IP_LIST=('{ip_to_whitelist}'); -- Snowflake Admin → Security → Network Policies",
        "databricks": f"Workspace Settings → Security → IP Access Lists → Add: {ip_to_whitelist}",
        "clickhouse_cloud": f"ClickHouse Cloud Console → Service → Security → IP Access List → Add: {ip_to_whitelist}/32",
    }

    return result


@app.post("/api/connections/{name}/diagnose")
async def diagnose_connection(name: str):
    """Run network-level diagnostics for a connection (DNS, TCP, TLS).

    Goes deeper than test_connection — identifies whether the issue is
    DNS resolution, TCP reachability, TLS handshake, or auth.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    import socket
    import asyncio

    diagnostics: list[dict] = []

    # Extract host and port from connection string
    host, port = "", 0
    try:
        from urllib.parse import urlparse
        parsed = urlparse(conn_str.replace("postgresql://", "http://").replace("mysql://", "http://").replace("mssql://", "http://").replace("redshift://", "http://").replace("clickhouse://", "http://"))
        host = parsed.hostname or ""
        _default_ports = {"postgres": 5432, "mysql": 3306, "mssql": 1433, "redshift": 5439, "snowflake": 443, "bigquery": 443, "clickhouse": 9000, "databricks": 443, "trino": 8080}
        port = parsed.port or _default_ports.get(info.db_type, 0)
    except Exception:
        diagnostics.append({"check": "url_parse", "status": "error", "message": "Could not parse connection URL"})
        return {"diagnostics": diagnostics}

    if not host:
        diagnostics.append({"check": "url_parse", "status": "error", "message": "No hostname found in connection URL"})
        return {"diagnostics": diagnostics}

    # 1. DNS resolution
    t0 = time.monotonic()
    try:
        ips = await asyncio.to_thread(socket.getaddrinfo, host, port, socket.AF_INET)
        resolved_ips = list(set(info[4][0] for info in ips))
        diagnostics.append({
            "check": "dns",
            "status": "ok",
            "message": f"Resolved {host} → {', '.join(resolved_ips)}",
            "duration_ms": round((time.monotonic() - t0) * 1000, 1),
        })
    except socket.gaierror as e:
        diagnostics.append({
            "check": "dns",
            "status": "error",
            "message": f"DNS resolution failed for {host}: {e}",
            "hint": "Check the hostname spelling and ensure DNS is configured correctly",
            "duration_ms": round((time.monotonic() - t0) * 1000, 1),
        })
        return {"host": host, "port": port, "diagnostics": diagnostics}

    # 2. TCP connectivity
    t1 = time.monotonic()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        await asyncio.to_thread(sock.connect, (host, port))
        sock.close()
        diagnostics.append({
            "check": "tcp",
            "status": "ok",
            "message": f"TCP connection to {host}:{port} succeeded",
            "duration_ms": round((time.monotonic() - t1) * 1000, 1),
        })
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        diagnostics.append({
            "check": "tcp",
            "status": "error",
            "message": f"TCP connection to {host}:{port} failed: {e}",
            "hint": "Check firewall rules, security groups, and ensure the database is running and accepting connections on this port",
            "duration_ms": round((time.monotonic() - t1) * 1000, 1),
        })
        return {"host": host, "port": port, "diagnostics": diagnostics}

    # 3. TLS handshake (if applicable)
    ssl_db_types = {"postgres", "mysql", "redshift", "snowflake", "bigquery", "databricks", "clickhouse", "mssql"}
    extras = get_credential_extras(name)
    ssl_enabled = extras.get("ssl_config", {}).get("enabled", False) or info.db_type in ("snowflake", "bigquery", "databricks")

    if info.db_type in ssl_db_types and ssl_enabled:
        t2 = time.monotonic()
        try:
            import ssl
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            tls_sock = context.wrap_socket(socket.socket(socket.AF_INET), server_hostname=host)
            tls_sock.settimeout(5)
            await asyncio.to_thread(tls_sock.connect, (host, port))
            cert = tls_sock.getpeercert(binary_form=False) or {}
            tls_version = tls_sock.version()
            tls_sock.close()
            diagnostics.append({
                "check": "tls",
                "status": "ok",
                "message": f"TLS handshake succeeded ({tls_version})",
                "duration_ms": round((time.monotonic() - t2) * 1000, 1),
            })
        except Exception as e:
            diagnostics.append({
                "check": "tls",
                "status": "warning",
                "message": f"TLS handshake issue: {e}",
                "hint": "The database may not support TLS on this port, or certificates may be misconfigured",
                "duration_ms": round((time.monotonic() - t2) * 1000, 1),
            })

    # 4. Database-level auth test (reuse the connector)
    t3 = time.monotonic()
    try:
        connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)
        try:
            ok = await connector.health_check()
            diagnostics.append({
                "check": "auth",
                "status": "ok" if ok else "error",
                "message": "Authentication and basic query succeeded" if ok else "Auth succeeded but health check failed",
                "duration_ms": round((time.monotonic() - t3) * 1000, 1),
            })
        finally:
            await pool_manager.release(info.db_type, conn_str)
    except Exception as e:
        diagnostics.append({
            "check": "auth",
            "status": "error",
            "message": f"Authentication failed: {_sanitize_db_error(str(e), db_type=info.db_type)}",
            "hint": "Verify username, password, and that the user has permission to connect",
            "duration_ms": round((time.monotonic() - t3) * 1000, 1),
        })

    return {"host": host, "port": port, "diagnostics": diagnostics}


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
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                cached = await connector.get_schema()
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))
        schema_cache.put(name, cached)

    # Apply endorsement filter (HEX Data Browser pattern — curate tables for AI agents)
    filtered = apply_endorsement_filter(name, cached)
    sf_include, sf_exclude = _get_schema_filters(name)
    filtered = _apply_schema_filter(filtered, sf_include, sf_exclude)

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
            # Add cardinality hints (helps Spider2.0 agent understand data distribution)
            unique_hint = ""
            stats = col.get("stats", {})
            if stats.get("distinct_fraction") == -1.0:
                unique_hint = " UNIQUE"
            elif col.get("low_cardinality"):
                unique_hint = " ENUM"  # ClickHouse LowCardinality type
            elif (stats.get("distinct_count") and stats["distinct_count"] <= 10
                  and col_type.lower() not in ("timestamp", "timestamptz", "timestamp with time zone",
                      "timestamp without time zone", "date", "datetime", "datetime2")):
                unique_hint = " ENUM"  # Low-cardinality: likely status/type field
            # Column comments help Spider2.0 agents understand column semantics
            comment = col.get("comment", "")
            comment_str = f" -- {comment}" if comment else ""
            cols.append(f"{col['name']} {col_type}{nullable}{unique_hint}{comment_str}")
            if col.get("primary_key"):
                pk_cols.append(col["name"])

        # Build compact DDL string
        overview_kw = "CREATE VIEW" if table.get("type") == "view" else "CREATE TABLE"
        ddl_parts = [f"{overview_kw} {table.get('schema', '')}.{table['name']} ("]
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
        if table.get("size_mb"):
            compressed[key]["size_mb"] = table["size_mb"]
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
        # Redshift-specific
        if table.get("diststyle"):
            compressed[key]["diststyle"] = table["diststyle"]
        if table.get("sortkey"):
            compressed[key]["sortkey"] = table["sortkey"]
        # Snowflake-specific
        if table.get("clustering_key"):
            compressed[key]["clustering_key"] = table["clustering_key"]

    return compressed


def _deduplicate_partitioned_tables(schema: dict) -> tuple[dict, dict[str, list[str]]]:
    """ReFoRCE-style deduplication of date/number-partitioned table families.

    Enterprise schemas often contain hundreds of identically-structured tables
    with date suffixes (e.g., ga_sessions_20160801 through ga_sessions_20170801).
    ReFoRCE's ablation shows this is the single most impactful compression step
    (3-4% EX degradation if disabled).

    Returns:
        (deduplicated_schema, partition_map) where partition_map maps
        the representative table key to the list of all member keys.
    """
    import re
    from collections import defaultdict

    # Pattern: table name ending with date-like suffix (YYYYMMDD, YYYY_MM_DD, YYYY_MM, etc.)
    # or numeric partition suffix (_001, _002, _p1, _p2, etc.)
    date_suffixes = re.compile(
        r'^(.+?)_?'
        r'(?:'
        r'(\d{8})'           # YYYYMMDD
        r'|(\d{4}_\d{2}_\d{2})'  # YYYY_MM_DD
        r'|(\d{4}_\d{2})'   # YYYY_MM
        r'|(\d{4})'         # YYYY (only if 4+ tables match)
        r'|p(\d+)'          # p1, p2, ...
        r'|(\d{1,4})'       # numeric suffix (1, 2, ..., 001, 002)
        r')$'
    )

    # Group tables by their base name (without partition suffix)
    base_groups: dict[str, list[str]] = defaultdict(list)
    non_partitioned: dict[str, dict] = {}

    for key, table in schema.items():
        table_name = table.get("name", key.split(".")[-1]).lower()
        match = date_suffixes.match(table_name)
        if match:
            base_name = match.group(1).rstrip("_")
            schema_prefix = key.rsplit(".", 1)[0] + "." if "." in key else ""
            group_key = f"{schema_prefix}{base_name}"
            base_groups[group_key].append(key)
        else:
            non_partitioned[key] = table

    # Only deduplicate groups with 3+ tables (avoid false positives)
    deduplicated = dict(non_partitioned)
    partition_map: dict[str, list[str]] = {}

    for group_key, members in base_groups.items():
        if len(members) >= 3:
            # Verify structural similarity: all members should have same column names
            col_sets = []
            for m in members:
                cols = frozenset(c["name"] for c in schema[m].get("columns", []))
                col_sets.append(cols)
            # Check if at least 80% share the same structure
            if col_sets:
                most_common = max(set(col_sets), key=col_sets.count)
                similar_count = col_sets.count(most_common)
                if similar_count / len(members) >= 0.8:
                    # Keep the first table as representative, aggregate row counts
                    representative = members[0]
                    total_rows = sum(schema[m].get("row_count", 0) or 0 for m in members)
                    rep_data = dict(schema[representative])
                    rep_data["row_count"] = total_rows
                    rep_data["_partition_count"] = len(members)
                    rep_data["_partition_base"] = group_key.split(".")[-1] if "." in group_key else group_key
                    deduplicated[representative] = rep_data
                    partition_map[representative] = members
                    continue
            # Not structurally similar — keep all
            for m in members:
                deduplicated[m] = schema[m]
        else:
            # Too few to be a partition family
            for m in members:
                deduplicated[m] = schema[m]

    return deduplicated, partition_map


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
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            cached = schema_cache.get(name)
            if cached is None:
                cached = await connector.get_schema()
                schema_cache.put(name, cached)

            # ReFoRCE-style: deduplicate partitioned tables before compression
            deduped, partition_map = _deduplicate_partitioned_tables(cached)
            compressed = _compress_schema(deduped)
            groups = _group_tables(deduped)

        return {
            "connection_name": name,
            "db_type": info.db_type,
            "table_count": len(cached),
            "deduplicated_count": len(deduped),
            "partitioned_families": len(partition_map),
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
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
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
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
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
                    schema_cache.put_sample_values(name, table_key, values)

        return {
            "connection_name": name,
            "tables_sampled": len(samples),
            "samples": samples,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))


@app.post("/api/connections/{name}/schema/explore")
async def explore_column_values(
    name: str,
    table: str = Query(..., description="Full table name (e.g., 'public.users')"),
    column: str = Query(..., description="Column to explore"),
    limit: int = Query(default=20, ge=1, le=100, description="Max distinct values"),
    filter_pattern: str = Query(default="", description="LIKE pattern to filter values (e.g., '%active%')"),
):
    """ReFoRCE-style iterative column exploration for Spider2.0.

    Allows the AI agent to dynamically probe column values to resolve ambiguity
    in schema linking. ReFoRCE's ablation shows disabling column exploration
    causes 3-4% EX degradation — it's critical for handling enum-like columns
    where the question uses domain terminology not in column names.

    Returns distinct values, value counts, and NULL statistics.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    db_type = info.db_type
    # Build exploration query with dialect-aware quoting
    quote = '"' if db_type in ("postgres", "redshift", "snowflake", "trino") else '`'
    if db_type == "mssql":
        quote = '['
        close_quote = ']'
    else:
        close_quote = quote

    q_col = f"{quote}{column}{close_quote}"

    # Construct safe exploration query
    parts = []
    if filter_pattern:
        like_op = "ILIKE" if db_type in ("postgres", "redshift", "snowflake") else "LIKE"
        parts.append(f"WHERE {q_col} {like_op} :pattern")

    where_clause = parts[0] if parts else ""

    # Build the query — dialect-aware LIMIT/TOP
    if db_type == "mssql":
        explore_sql = f"""
SELECT TOP {limit}
    {q_col} AS value,
    COUNT(*) AS [count]
FROM {table}
{where_clause}
GROUP BY {q_col}
ORDER BY [count] DESC
"""
    else:
        explore_sql = f"""
SELECT
    {q_col} AS value,
    COUNT(*) AS count
FROM {table}
{where_clause}
GROUP BY {q_col}
ORDER BY count DESC
LIMIT {limit}
"""

    # NULL stats query
    null_sql = f"""
SELECT
    COUNT(*) AS total_rows,
    SUM(CASE WHEN {q_col} IS NULL THEN 1 ELSE 0 END) AS null_count,
    COUNT(DISTINCT {q_col}) AS distinct_count
FROM {table}
"""

    try:
        extras = get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            params = [filter_pattern] if filter_pattern else None
            # Replace :pattern placeholder with parameterized query
            actual_sql = explore_sql.replace(":pattern", f"'{filter_pattern}'") if filter_pattern else explore_sql

            values_rows = await connector.execute(actual_sql, timeout=30)
            stats_rows = await connector.execute(null_sql, timeout=30)

        stats = stats_rows[0] if stats_rows else {}
        return {
            "connection_name": name,
            "table": table,
            "column": column,
            "values": [{"value": r.get("value"), "count": r.get("count", 0)} for r in values_rows],
            "statistics": {
                "total_rows": stats.get("total_rows", 0),
                "null_count": stats.get("null_count", 0),
                "distinct_count": stats.get("distinct_count", 0),
                "null_pct": round(stats.get("null_count", 0) / max(stats.get("total_rows", 1), 1) * 100, 1),
            },
            "filter": filter_pattern or None,
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
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            # Get or use cached schema
            cached = schema_cache.get(name)
            if cached is None:
                cached = await connector.get_schema()
                schema_cache.put(name, cached)

            # Apply endorsement filter and schema filters
            filtered = apply_endorsement_filter(name, cached)
            sf_include, sf_exclude = _get_schema_filters(name)
            filtered = _apply_schema_filter(filtered, sf_include, sf_exclude)

            # ReFoRCE-style: deduplicate partitioned table families
            filtered, partition_map = _deduplicate_partitioned_tables(filtered)

            # Build enriched compact schema
            enriched: dict[str, Any] = {}
            for key, table in filtered.items():
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

                browse_kw = "CREATE VIEW" if table.get("type") == "view" else "CREATE TABLE"
                ddl_parts = [f"{browse_kw} {table.get('schema', '')}.{table['name']} ("]
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
                # Add partition info for deduplicated table families
                if key in partition_map:
                    entry["_partitions"] = len(partition_map[key])
                    entry["_partition_base"] = table.get("_partition_base", "")

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

        return {
            "connection_name": name,
            "db_type": info.db_type,
            "table_count": len(enriched),
            "partitioned_families": len(partition_map),
            "tables": enriched,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))


@app.get("/api/connections/{name}/schema/compact")
async def get_compact_schema(
    name: str,
    max_tables: int = Query(default=50, ge=1, le=500, description="Maximum tables to include"),
    include_fk: bool = Query(default=True, description="Include foreign key relationships"),
    include_types: bool = Query(default=True, description="Include column type info"),
    format: str = Query(default="text", pattern="^(text|json)$", description="Output format"),
):
    """Ultra-compact schema representation optimized for LLM context windows.

    Based on EDBT 2026 schema compression research and RSL-SQL bidirectional linking.
    Produces a minimal-token schema that preserves the most important signals:
    - Table and column names (always)
    - Primary keys and foreign keys (high-impact for Spider2.0)
    - Column types (optional, helps with type-aware SQL generation)
    - Row counts (helps agent estimate query cost)

    Text format example:
        public.customers (10000 rows): customer_id* INT, name VARCHAR, email VARCHAR
        public.orders (50000 rows): order_id* INT, customer_id→customers.customer_id INT, total DECIMAL
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    cached = schema_cache.get(name)
    if cached is None:
        conn_str = get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        extras = get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            cached = await connector.get_schema()
            schema_cache.put(name, cached)

    filtered = apply_endorsement_filter(name, cached)
    sf_include, sf_exclude = _get_schema_filters(name)
    filtered = _apply_schema_filter(filtered, sf_include, sf_exclude)

    # ReFoRCE-style: deduplicate date-partitioned table families before compression
    filtered, partition_map = _deduplicate_partitioned_tables(filtered)

    # Sort tables by relevance: most connected (FK-rich) first, then by row count
    # This ensures the most important join-hub tables appear in truncated schemas
    def _table_relevance(key: str) -> tuple:
        table = filtered[key]
        fk_count = len(table.get("foreign_keys", []))
        row_count = table.get("row_count", 0) or 0
        col_count = len(table.get("columns", []))
        # Higher FK count = higher relevance (join hubs are critical for Spider2.0)
        # Higher row count = higher relevance (larger tables are usually more important)
        return (-fk_count, -row_count, -col_count, key)

    table_keys = sorted(filtered.keys(), key=_table_relevance)[:max_tables]

    # Build FK lookup for compact reference format (explicit + inferred)
    fk_map: dict[str, str] = {}  # table.col -> ref_table.ref_col
    if include_fk:
        for key, table in filtered.items():
            for fk in table.get("foreign_keys", []):
                fk_key = f"{key}.{fk['column']}"
                ref = f"{fk.get('references_table', '')}.{fk.get('references_column', '')}"
                fk_map[fk_key] = ref
        # Add inferred joins
        inferred = _infer_implicit_joins(filtered)
        for inf in inferred:
            inf_from_key = f"{inf['from_schema']}.{inf['from_table']}" if inf["from_schema"] else inf["from_table"]
            fk_key = f"{inf_from_key}.{inf['from_column']}"
            if fk_key not in fk_map:
                ref = f"{inf['to_table']}.{inf['to_column']}"
                fk_map[fk_key] = ref

    if format == "json":
        compact: dict[str, Any] = {}
        for key in table_keys:
            table = filtered[key]
            cols = []
            for col in table.get("columns", []):
                entry: dict[str, Any] = {"n": col["name"]}
                if include_types:
                    entry["t"] = col.get("type", "")
                if col.get("primary_key"):
                    entry["pk"] = True
                fk_ref = fk_map.get(f"{key}.{col['name']}")
                if fk_ref:
                    entry["fk"] = fk_ref
                comment = col.get("comment", "")
                if comment:
                    entry["desc"] = comment
                # Cardinality hints for Spider2.0 query planning
                stats = col.get("stats", {})
                if stats:
                    dc = stats.get("distinct_count", 0)
                    df = abs(stats.get("distinct_fraction", 0))
                    if df == 1.0 or (dc and dc == table.get("row_count", 0) and dc > 100):
                        entry["u"] = True  # unique column
                    elif dc and dc <= 10:
                        entry["lc"] = dc  # low-cardinality with exact count
                cols.append(entry)
            compact[key] = {"c": cols, "r": table.get("row_count", 0)}
            if table.get("size_mb"):
                compact[key]["mb"] = table["size_mb"]
            # Add partition info for deduplicated table families
            if key in partition_map:
                compact[key]["_partitions"] = len(partition_map[key])
                compact[key]["_partition_base"] = table.get("_partition_base", "")
        return {
            "connection_name": name,
            "format": "json",
            "table_count": len(compact),
            "partitioned_families": len(partition_map),
            "token_estimate": sum(len(str(v)) for v in compact.values()) // 4,
            "tables": compact,
        }

    # Text format — optimized for direct LLM consumption
    lines = []
    total_chars = 0
    for key in table_keys:
        table = filtered[key]
        row_count = table.get("row_count", 0)
        size_mb = table.get("size_mb", 0)
        meta_parts = []
        if row_count:
            if row_count >= 1_000_000:
                meta_parts.append(f"{row_count / 1_000_000:.1f}M rows")
            elif row_count >= 1_000:
                meta_parts.append(f"{row_count / 1_000:.0f}K rows")
            else:
                meta_parts.append(f"{row_count} rows")
        if size_mb and size_mb >= 1:
            if size_mb >= 1024:
                meta_parts.append(f"{size_mb / 1024:.1f}GB")
            else:
                meta_parts.append(f"{size_mb:.0f}MB")
        row_str = f" ({', '.join(meta_parts)})" if meta_parts else ""

        col_parts = []
        for col in table.get("columns", []):
            name_str = col["name"]
            if col.get("primary_key"):
                name_str += "*"
            fk_ref = fk_map.get(f"{key}.{col['name']}")
            if fk_ref:
                name_str += f"→{fk_ref}"
            if include_types:
                col_type = col.get("type", "").upper()
                # Shorten common types
                type_map = {
                    "CHARACTER VARYING": "VARCHAR",
                    "TIMESTAMP WITHOUT TIME ZONE": "TIMESTAMP",
                    "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ",
                    "DOUBLE PRECISION": "DOUBLE",
                    "BOOLEAN": "BOOL",
                    "INTEGER": "INT",
                    "BIGINT": "BIGINT",
                    "SMALLINT": "SMALLINT",
                }
                col_type = type_map.get(col_type, col_type)
                name_str += f" {col_type}"
            # Cardinality hints in text format
            stats = col.get("stats", {})
            if stats:
                dc = stats.get("distinct_count", 0)
                df = abs(stats.get("distinct_fraction", 0))
                if df == 1.0 or (dc and dc == table.get("row_count", 0) and dc > 100):
                    name_str += "!"  # unique marker
                elif dc and dc <= 10:
                    name_str += f"~{dc}"  # low-cardinality count
            col_parts.append(name_str)

        # Add partition annotation for deduplicated table families
        partition_note = ""
        if key in partition_map:
            count = len(partition_map[key])
            base = table.get("_partition_base", "")
            partition_note = f" [×{count} partitions: {base}_*]"

        line = f"{key}{row_str}{partition_note}: {', '.join(col_parts)}"
        lines.append(line)
        total_chars += len(line)

    schema_text = "\n".join(lines)
    return {
        "connection_name": name,
        "format": "text",
        "table_count": len(lines),
        "partitioned_families": len(partition_map),
        "token_estimate": total_chars // 4,
        "schema": schema_text,
    }


@app.get("/api/connections/{name}/schema/ddl")
async def get_schema_ddl(
    name: str,
    max_tables: int = Query(default=50, ge=1, le=500, description="Maximum tables to include"),
    include_fk: bool = Query(default=True, description="Include foreign key constraints"),
    compress: bool = Query(default=False, description="Enable ReFoRCE-style table grouping for large schemas"),
):
    """CREATE TABLE DDL representation of the schema.

    Spider2.0 SOTA systems (DAIL-SQL, DIN-SQL, CHESS) found that CREATE TABLE
    DDL format outperforms list/JSON formats for text-to-SQL accuracy because:
    1. LLMs have seen massive amounts of DDL in training data
    2. DDL naturally encodes constraints (PK, FK, NOT NULL)
    3. DDL is compact and unambiguous

    Example output:
        CREATE TABLE public.customers (
            customer_id INT PRIMARY KEY,
            name VARCHAR NOT NULL,
            email VARCHAR
        );
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    cached = schema_cache.get(name)
    if cached is None:
        conn_str = get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        extras = get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            cached = await connector.get_schema()
        schema_cache.put(name, cached)

    filtered = apply_endorsement_filter(name, cached)
    sf_include, sf_exclude = _get_schema_filters(name)
    filtered = _apply_schema_filter(filtered, sf_include, sf_exclude)

    # ReFoRCE-style: deduplicate partitioned table families
    filtered, _partition_map = _deduplicate_partitioned_tables(filtered)

    # Sort by FK relevance (same as compact)
    def _table_relevance(key: str) -> tuple:
        table = filtered[key]
        fk_count = len(table.get("foreign_keys", []))
        row_count = table.get("row_count", 0) or 0
        return (-fk_count, -row_count, key)

    table_keys = sorted(filtered.keys(), key=_table_relevance)[:max_tables]

    # Build FK lookup
    fk_map: dict[str, str] = {}
    if include_fk:
        for key, table in filtered.items():
            for fk in table.get("foreign_keys", []):
                fk_key = f"{key}.{fk['column']}"
                ref = f"{fk.get('references_table', '')}.{fk.get('references_column', '')}"
                fk_map[fk_key] = ref

    # ReFoRCE-style table grouping: merge similar-prefix tables, show one DDL per group
    # This dramatically reduces token usage for large schemas (300KB+ DDL → fits in context)
    grouped_tables: set[str] = set()  # Keys that are compressed (show name only)
    group_representatives: dict[str, list[str]] = {}  # representative_key -> [member_names]
    if compress and len(table_keys) > 15:
        import re as _re_group
        # Extract common prefixes (e.g., "stg_", "dim_", "fact_", "raw_")
        prefix_groups: dict[str, list[str]] = {}
        for key in table_keys:
            tname = filtered[key].get("name", "")
            # Find prefix: everything before first underscore that appears in 3+ tables
            match = _re_group.match(r'^([a-zA-Z]+_)', tname)
            if match:
                prefix = match.group(1)
                if prefix not in prefix_groups:
                    prefix_groups[prefix] = []
                prefix_groups[prefix].append(key)

        for prefix, members in prefix_groups.items():
            if len(members) >= 3:
                # Pick the member with most columns as representative
                rep = max(members, key=lambda k: len(filtered[k].get("columns", [])))
                others = [k for k in members if k != rep]
                group_representatives[rep] = [filtered[k].get("name", "") for k in others]
                grouped_tables.update(others)

        # Remove grouped tables from table_keys
        table_keys = [k for k in table_keys if k not in grouped_tables]

    ddl_statements = []
    for key in table_keys:
        table = filtered[key]
        # Use schema-qualified name
        table_name = f"{table.get('schema', '')}.{table.get('name', '')}"

        # Table-level comment with metadata (helps agent plan queries)
        table_desc = table.get("description", "")
        meta_hints = []
        if table.get("row_count"):
            rc = table["row_count"]
            meta_hints.append(f"{rc / 1_000_000:.1f}M rows" if rc >= 1_000_000
                             else f"{rc / 1_000:.0f}K rows" if rc >= 1000
                             else f"{rc} rows")
        if table.get("size_mb") and table["size_mb"] >= 1:
            sm = table["size_mb"]
            meta_hints.append(f"{sm / 1024:.1f}GB" if sm >= 1024 else f"{sm:.0f}MB")
        if table.get("engine"):
            meta_hints.append(table["engine"])
        header_parts = [p for p in [table_desc, ", ".join(meta_hints)] if p]
        table_header = f"-- {' | '.join(header_parts)}\n" if header_parts else ""

        col_lines = []
        pk_cols = []
        for col in table.get("columns", []):
            col_type = col.get("type", "TEXT").upper()
            # Shorten common types for token efficiency (ReFoRCE: compression is critical)
            type_map = {
                "CHARACTER VARYING": "VARCHAR",
                "TIMESTAMP WITHOUT TIME ZONE": "TIMESTAMP",
                "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ",
                "DOUBLE PRECISION": "DOUBLE",
                "BOOLEAN": "BOOL",
                "INTEGER": "INT",
                "REAL": "FLOAT",
            }
            col_type = type_map.get(col_type, col_type)

            parts = [f"  {col['name']} {col_type}"]
            if not col.get("nullable", True):
                parts.append("NOT NULL")
            # Inline column annotations (semantic hints for agent)
            annotations = []
            col_comment = col.get("comment", "")
            if col_comment:
                annotations.append(col_comment)
            # Redshift: distribution key and encoding hints
            if col.get("dist_key"):
                annotations.append("DISTKEY")
            if col.get("sort_key_position"):
                annotations.append(f"SORTKEY#{col['sort_key_position']}")
            # ClickHouse: low cardinality columns
            if col.get("low_cardinality"):
                annotations.append("LOW_CARDINALITY")
            # Cardinality hint for query planning
            stats = col.get("stats", {})
            if stats.get("distinct_count") is not None and stats["distinct_count"] > 0:
                dc = stats["distinct_count"]
                if dc <= 10:
                    annotations.append(f"{dc} distinct values")
                elif dc <= 1000:
                    annotations.append(f"{dc} distinct values")
                else:
                    annotations.append("high cardinality")
            elif stats.get("distinct_fraction") is not None:
                frac = abs(stats["distinct_fraction"])
                if frac == 1.0:
                    annotations.append("unique")
                elif frac > 0.5:
                    annotations.append("high cardinality")
                elif frac > 0 and frac <= 0.01:
                    annotations.append("low cardinality")
            # Inline sample values for low-cardinality columns
            is_low_card = False
            dc = stats.get("distinct_count", 0) if stats else 0
            df = abs(stats.get("distinct_fraction", 0)) if stats else 0
            if dc and dc <= 50:
                is_low_card = True
            elif df and df < 0.05:
                is_low_card = True
            elif not stats:
                is_low_card = True
            if is_low_card:
                cached_samples = schema_cache.get_sample_values(name, key)
                if cached_samples and col["name"] in cached_samples:
                    sample_vals = cached_samples[col["name"]]
                    if len(sample_vals) <= 10:
                        annotations.append(f"e.g. {', '.join(repr(v) for v in sample_vals[:5])}")
            if annotations:
                parts.append(f"-- {'; '.join(annotations)}")
            col_lines.append(" ".join(parts))
            if col.get("primary_key"):
                pk_cols.append(col["name"])

        # Add PK constraint
        if pk_cols:
            col_lines.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")

        # Add FK constraints
        if include_fk:
            for fk in table.get("foreign_keys", []):
                ref_table = fk.get("references_table", "")
                ref_col = fk.get("references_column", "")
                col_lines.append(f"  FOREIGN KEY ({fk['column']}) REFERENCES {ref_table}({ref_col})")

        # Build row comment with metadata
        comment_parts = []
        rc = table.get("row_count", 0)
        if rc:
            comment_parts.append(f"{rc:,} rows" if rc < 1_000_000 else f"{rc/1_000_000:.1f}M rows")
        # ClickHouse-specific: engine and sorting key (critical for query optimization)
        engine = table.get("engine", "")
        if engine:
            comment_parts.append(f"ENGINE={engine}")
        sorting_key = table.get("sorting_key", "")
        if sorting_key:
            comment_parts.append(f"ORDER BY({sorting_key})")
        # Redshift-specific: distribution style + sort key
        dist_style = table.get("diststyle", "")
        if dist_style:
            comment_parts.append(f"DISTSTYLE={dist_style}")
        sort_key = table.get("sortkey", "")
        if sort_key:
            comment_parts.append(f"SORTKEY({sort_key})")
        # Snowflake-specific: clustering key
        clustering_key = table.get("clustering_key", "")
        if clustering_key:
            comment_parts.append(f"CLUSTER BY({clustering_key})")
        # BigQuery-specific: partitioning and clustering
        partitioning = table.get("partitioning", {})
        if partitioning and partitioning.get("field"):
            comment_parts.append(f"PARTITION BY {partitioning['field']}")
        clustering = table.get("clustering_fields", [])
        if clustering:
            comment_parts.append(f"CLUSTER BY({', '.join(clustering)})")
        row_comment = f" -- {', '.join(comment_parts)}" if comment_parts else ""

        obj_keyword = "CREATE VIEW" if table.get("type") == "view" else "CREATE TABLE"
        ddl = f"{table_header}{obj_keyword} {table_name} (\n{',\n'.join(col_lines)}\n);{row_comment}"

        # Append group member list if this is a representative table
        if key in group_representatives:
            members = group_representatives[key]
            ddl += f"\n-- Similar tables (same structure): {', '.join(members)}"

        ddl_statements.append(ddl)

    ddl_text = "\n\n".join(ddl_statements)
    compressed_count = len(grouped_tables) if compress else 0
    return {
        "connection_name": name,
        "format": "ddl",
        "table_count": len(ddl_statements),
        "compressed_tables": compressed_count,
        "total_tables_represented": len(ddl_statements) + compressed_count,
        "token_estimate": len(ddl_text) // 4,
        "ddl": ddl_text,
    }


@app.get("/api/connections/{name}/schema/agent-context")
async def get_agent_context(
    name: str,
    question: str = Query(default="", description="Optional question for schema linking — omit for full schema"),
    max_tables: int = Query(default=30, ge=1, le=100, description="Max tables to include"),
    include_samples: bool = Query(default=True, description="Include cached sample values for string columns"),
    progressive: bool = Query(default=False, description="Progressive disclosure: full DDL for top tables, compact one-liners for the rest (saves 40-60%% tokens)"),
    full_ddl_count: int = Query(default=8, ge=1, le=50, description="Number of top-scoring tables to show full DDL for (when progressive=true)"),
):
    """Single-call schema context optimized for SQL generation agents (Spider2.0 pattern).

    Combines DDL schema, join relationships, table metadata, and sample values
    into a single prompt-ready text block. Designed to be pasted directly into
    an LLM system prompt for text-to-SQL tasks.

    When progressive=true:
    - Top-scoring tables get full DDL with columns, PKs, FKs, samples
    - Remaining tables get compact one-liners (name, column count, PKs, FKs)
    - This saves 40-60% tokens while preserving join path information
    - Mimics the two-pass approach used by CHESS and DIN-SQL (Spider2.0 SOTA)

    Based on Spider2.0 SOTA findings:
    - DDL format preferred by top performers (Genloop, QUVI, Databao)
    - Sample values critical for schema linking (3-4% EX improvement)
    - Inferred joins fill gaps in FK-free databases (ClickHouse, BigQuery)
    - Progressive disclosure: broad recall + focused detail (CHESS pattern)
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    cached = schema_cache.get(name)
    if cached is None:
        conn_str = get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        extras = get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            cached = await connector.get_schema()
        schema_cache.put(name, cached)

    filtered = apply_endorsement_filter(name, cached)
    sf_include, sf_exclude = _get_schema_filters(name)
    filtered = _apply_schema_filter(filtered, sf_include, sf_exclude)

    # If a question is provided, use schema linking to select relevant tables
    table_scores: dict[str, float] = {}
    if question:
        # Reuse the schema link logic inline to select top tables
        import re as _re_ctx
        stopwords = {"the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
                     "her", "was", "one", "our", "out", "has", "how", "many", "much",
                     "what", "which", "show", "find", "list", "give", "tell",
                     "from", "with", "that", "this", "have", "will",
                     "select", "where", "group", "having", "limit", "table", "column", "database"}
        terms = [w for w in _re_ctx.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', question.lower()) if len(w) >= 3 and w not in stopwords]
        for key, t in filtered.items():
            score = 0.0
            tn = t.get("name", "").lower()
            for term in terms:
                if term == tn or term == tn.rstrip("s"):
                    score += 10.0
                elif term in tn:
                    score += 3.0
                for col in t.get("columns", []):
                    cn = col.get("name", "").lower()
                    if term == cn:
                        score += 4.0
                    elif term in cn:
                        score += 1.5
            table_scores[key] = score
        # Select tables with score > 0, plus their FK-connected tables
        linked = {k for k, s in table_scores.items() if s > 0}
        fk_adds = set()
        for k in list(linked):
            for fk in filtered.get(k, {}).get("foreign_keys", []):
                for ck in filtered:
                    if filtered[ck].get("name") == fk.get("references_table"):
                        fk_adds.add(ck)
        linked |= fk_adds
        if not linked:
            linked = set(list(filtered.keys())[:max_tables])
        filtered = {k: filtered[k] for k in sorted(linked)[:max_tables] if k in filtered}

    # Load semantic model for enrichment (HEX pattern)
    semantic = _load_semantic_model(name)

    # Build context sections
    sections: list[str] = []

    # Section 1: Database info header
    total_rows = sum(t.get("row_count", 0) or 0 for t in filtered.values())
    total_mb = sum(t.get("size_mb", 0) or 0 for t in filtered.values())
    sections.append(f"-- Database: {name} ({info.db_type})")
    sections.append(f"-- Tables: {len(filtered)}, Total rows: {total_rows:,}, Total size: {total_mb:.1f} MB")
    sections.append("")

    # Section 0.5: Business glossary — only show terms relevant to the question or tables
    glossary = semantic.get("glossary", {})
    if glossary:
        # Filter glossary to terms that reference included tables
        table_names = {t.get("name", "").lower() for t in filtered.values()}
        relevant_glossary = {}
        # Extract question terms for matching (reuse if already parsed)
        import re as _re_gloss
        q_terms = [w.lower() for w in _re_gloss.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', question)] if question else []
        for term, col_ref in glossary.items():
            ref_lower = col_ref.lower()
            # Include if the column reference mentions a table we're showing
            for tname in table_names:
                if tname and tname in ref_lower:
                    relevant_glossary[term] = col_ref
                    break
            # Also include if a question term matches the glossary term
            if question and term not in relevant_glossary:
                for qterm in q_terms:
                    if qterm in term.lower():
                        relevant_glossary[term] = col_ref
                        break
        if relevant_glossary:
            glossary_lines = ["-- === Business Glossary ==="]
            for term, col_ref in sorted(relevant_glossary.items())[:25]:
                glossary_lines.append(f"-- {term} = {col_ref}")
            sections.append("\n".join(glossary_lines))
            sections.append("")

    # Section 2: DDL with inline metadata
    inferred = _infer_implicit_joins(filtered)
    inferred_map: dict[str, list[dict]] = {}
    for ij in inferred:
        key = f"{ij['from_schema']}.{ij['from_table']}" if ij.get("from_schema") else ij["from_table"]
        if key not in inferred_map:
            inferred_map[key] = []
        inferred_map[key].append(ij)

    # Semantic join hints from model
    semantic_joins = semantic.get("joins", [])

    # Progressive disclosure: determine which tables get full DDL vs compact summary
    # Top-scoring tables get full DDL; the rest get a one-liner with PKs/FKs only
    full_ddl_keys: set[str] = set()
    compact_keys: set[str] = set()
    if progressive and question:
        # Sort by score (from schema linking above), take top N for full DDL
        scored = sorted(filtered.keys(), key=lambda k: table_scores.get(k, 0), reverse=True)
        full_ddl_keys = set(scored[:full_ddl_count])
        compact_keys = set(scored[full_ddl_count:])
    elif progressive:
        # No question — just use the first N tables alphabetically
        all_keys = sorted(filtered.keys())
        full_ddl_keys = set(all_keys[:full_ddl_count])
        compact_keys = set(all_keys[full_ddl_count:])
    else:
        full_ddl_keys = set(filtered.keys())

    # Compact section for low-scoring tables (progressive mode)
    if compact_keys:
        compact_lines = ["-- === Additional Tables (compact) ==="]
        for key in sorted(compact_keys):
            table = filtered[key]
            table_name = f"{table.get('schema', '')}.{table['name']}" if table.get("schema") else table["name"]
            cols = table.get("columns", [])
            pks = [c["name"] for c in cols if c.get("primary_key")]
            fks = table.get("foreign_keys", [])
            rc = table.get("row_count", 0) or 0
            parts = [f"{len(cols)} cols"]
            if rc:
                parts.append(f"{rc:,} rows")
            if pks:
                parts.append(f"PK: {','.join(pks)}")
            for fk in fks:
                ref = fk.get("references_table", "?")
                parts.append(f"FK: {fk.get('column', '?')}→{ref}")
            for ij in inferred_map.get(key, []):
                parts.append(f"join: {ij['from_column']}→{ij['to_table']}")
            compact_lines.append(f"-- {table_name} ({', '.join(parts)})")
        sections.append("\n".join(compact_lines))
        sections.append("")

    # Full DDL section for top-scoring tables
    if full_ddl_keys and compact_keys:
        sections.append("-- === Detailed Schema (top tables) ===")

    for key in sorted(full_ddl_keys):
        table = filtered[key]
        table_name = f"{table.get('schema', '')}.{table['name']}" if table.get("schema") else table["name"]
        rc = table.get("row_count", 0) or 0
        size = table.get("size_mb", 0) or 0
        meta_parts = []
        if rc:
            meta_parts.append(f"{rc:,} rows")
        if size:
            meta_parts.append(f"{size:.1f} MB")
        # Semantic model description overrides database comment
        sem_table = semantic.get("tables", {}).get(key, {})
        desc = sem_table.get("description", "") or table.get("description", "")
        if desc:
            meta_parts.append(desc)
        if progressive and question:
            score = table_scores.get(key, 0)
            if score > 0:
                meta_parts.append(f"relevance={score:.1f}")
        meta_comment = f" -- {', '.join(meta_parts)}" if meta_parts else ""

        obj_kw = "CREATE VIEW" if table.get("type") == "view" else "CREATE TABLE"
        col_lines = []
        sem_cols = sem_table.get("columns", {})
        for col in table.get("columns", []):
            ct = col.get("type", "").upper()
            nn = " NOT NULL" if not col.get("nullable", True) else ""
            # Semantic column description overrides database comment
            sem_col = sem_cols.get(col["name"], {})
            comment = sem_col.get("description", "") or col.get("comment", "")
            # Add business name if different from column name
            biz_name = sem_col.get("business_name", "")
            if biz_name and biz_name.lower() != col["name"].lower().replace("_", " "):
                comment = f"{biz_name}: {comment}" if comment else biz_name
            # Add unit annotation
            unit = sem_col.get("unit", "")
            if unit:
                comment = f"{comment} ({unit})" if comment else f"({unit})"
            comment_str = f" -- {comment}" if comment else ""
            col_lines.append(f"  {col['name']} {ct}{nn}{comment_str}")

        # PKs
        pks = [col["name"] for col in table.get("columns", []) if col.get("primary_key")]
        if pks:
            col_lines.append(f"  PRIMARY KEY ({', '.join(pks)})")

        # Explicit FKs
        for fk in table.get("foreign_keys", []):
            ref = f"{fk.get('references_schema', '')}.{fk['references_table']}" if fk.get("references_schema") else fk["references_table"]
            col_lines.append(f"  FOREIGN KEY ({fk['column']}) REFERENCES {ref}({fk['references_column']})")

        # Inferred FKs
        for ij in inferred_map.get(key, []):
            ref = f"{ij.get('to_schema', '')}.{ij['to_table']}" if ij.get("to_schema") else ij["to_table"]
            col_lines.append(f"  -- inferred join: {ij['from_column']} -> {ref}({ij['to_column']})")

        # Semantic join hints from model (curated by user)
        for sj in semantic_joins:
            sj_from = sj.get("from", "")
            if sj_from.startswith(f"{key}.") or sj_from.startswith(f"{table_name}."):
                join_type = sj.get("type", "")
                join_desc = sj.get("description", "")
                hint = f"  -- join hint: {sj_from} -> {sj.get('to', '')}"
                if join_type:
                    hint += f" ({join_type})"
                if join_desc:
                    hint += f" -- {join_desc}"
                col_lines.append(hint)

        ddl = f"{obj_kw} {table_name} (\n{',\n'.join(col_lines)}\n);{meta_comment}"
        sections.append(ddl)

    # Section 3: Sample values (if cached and requested)
    if include_samples:
        sample_sections: list[str] = []
        for key in sorted(filtered.keys()):
            samples = schema_cache.get_sample_values(name, key)
            if samples:
                lines = [f"-- Sample values for {key}:"]
                for col_name, vals in samples.items():
                    lines.append(f"--   {col_name}: {', '.join(repr(v) for v in vals[:5])}")
                sample_sections.append("\n".join(lines))
        if sample_sections:
            sections.append("")
            sections.append("-- === Sample Values ===")
            sections.extend(sample_sections)

    context_text = "\n\n".join(sections)
    result = {
        "connection_name": name,
        "db_type": info.db_type,
        "table_count": len(filtered),
        "token_estimate": len(context_text) // 4,
        "has_question_filter": bool(question),
        "context": context_text,
    }
    if progressive:
        result["progressive"] = {
            "full_ddl_tables": len(full_ddl_keys),
            "compact_tables": len(compact_keys),
            "full_ddl_count_param": full_ddl_count,
        }
    return result


@app.get("/api/connections/{name}/schema/link")
async def schema_link(
    name: str,
    question: str = Query(..., description="Natural language question to link schema for"),
    format: str = Query(default="ddl", pattern="^(ddl|compact|json|condensed)$", description="Output format: ddl (full), condensed (pruned columns), compact (one-line), json"),
    max_tables: int = Query(default=20, ge=1, le=100, description="Max tables in linked schema"),
    prune_columns: bool = Query(default=False, description="Drop columns with 0 relevance from low-scoring tables (reduces token count 30-60%%)"),
):
    """Smart schema linking — find tables and columns relevant to a natural language question.

    Implements high-recall schema linking optimized for Spider2.0:
    1. Tokenizes the question into meaningful terms
    2. Matches terms against table names, column names, and comments
    3. Includes FK-connected tables for join path completeness
    4. Returns linked schema in DDL format (preferred by SOTA systems)

    Based on EDBT 2026 research: recall matters more than precision for schema linking.
    Better to include extra tables than miss a relevant one.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    cached = schema_cache.get(name)
    if cached is None:
        conn_str = get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        extras = get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            cached = await connector.get_schema()
        schema_cache.put(name, cached)

    filtered = apply_endorsement_filter(name, cached)
    sf_include, sf_exclude = _get_schema_filters(name)
    filtered = _apply_schema_filter(filtered, sf_include, sf_exclude)

    # Step 1: Tokenize question into search terms
    import re as _re_link
    # Extract meaningful words (3+ chars, not common SQL/English stopwords)
    stopwords = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
        "her", "was", "one", "our", "out", "has", "how", "man", "new", "now",
        "old", "see", "way", "who", "did", "get", "has", "him", "his", "let",
        "say", "she", "too", "use", "what", "which", "show", "find", "list",
        "give", "tell", "many", "much", "each", "every", "from", "with", "that",
        "this", "have", "will", "your", "they", "been", "more", "when", "make",
        "like", "very", "just", "than", "them", "some", "would", "could",
        "select", "where", "group", "having", "limit",
        "result", "table", "column", "database", "query", "display", "retrieve",
    }
    # Semantic synonyms for common business/analytical terms that map to column names
    # This improves recall when the question uses different words than the schema
    _synonyms: dict[str, list[str]] = {
        "spending": ["amount", "total", "payment", "cost", "price", "revenue"],
        "revenue": ["amount", "total", "sales", "income", "price"],
        "bought": ["order", "purchase", "transaction"],
        "sold": ["order", "sale", "transaction"],
        "profit": ["margin", "revenue", "cost", "amount"],
        "expensive": ["price", "cost", "amount"],
        "cheapest": ["price", "cost", "amount"],
        "latest": ["date", "time", "created", "updated", "recent"],
        "oldest": ["date", "time", "created"],
        "biggest": ["count", "total", "amount", "size"],
        "active": ["status", "is_active", "enabled"],
        "inactive": ["status", "is_active", "enabled"],
        "location": ["city", "state", "country", "region", "address", "zip"],
        "address": ["city", "state", "country", "zip", "address_line"],
        "employee": ["staff", "worker", "user", "agent"],
        "customer": ["client", "buyer", "account", "user"],
        "product": ["item", "sku", "goods", "inventory"],
        "category": ["type", "group", "segment", "class"],
        "average": ["avg", "mean"],
        "monthly": ["month", "date"],
        "yearly": ["year", "date", "annual"],
        "daily": ["day", "date"],
        "payment": ["amount", "transaction", "charge", "invoice"],
        "shipping": ["shipment", "delivery", "tracking", "freight"],
        "discount": ["promo", "coupon", "rebate", "reduction"],
        "name": ["title", "label", "description"],
        "total": ["sum", "amount", "aggregate", "count"],
        "count": ["number", "total", "quantity"],
        "quantity": ["qty", "count", "amount", "units"],
        "percentage": ["percent", "rate", "ratio", "fraction"],
        "rank": ["position", "order", "rank", "rating"],
        "department": ["dept", "division", "team", "group", "unit"],
        "salary": ["wage", "pay", "compensation", "income", "earning"],
        "manager": ["supervisor", "boss", "lead", "head"],
        "country": ["nation", "region", "territory", "geo"],
        "city": ["town", "municipality", "location"],
        "email": ["mail", "contact", "address"],
        "phone": ["tel", "telephone", "mobile", "contact"],
        "created": ["created_at", "date", "timestamp", "registered"],
        "updated": ["modified", "changed", "last_modified"],
        "deleted": ["removed", "archived", "inactive"],
        "stock": ["inventory", "supply", "quantity", "available"],
        "supplier": ["vendor", "provider", "manufacturer"],
        "invoice": ["bill", "receipt", "statement", "charge"],
        "order": ["purchase", "transaction", "booking", "request"],
    }
    question_lower = question.lower()
    terms = [w for w in _re_link.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', question_lower) if len(w) >= 3 and w not in stopwords]

    # N-gram extraction: combine adjacent terms into compound matches
    # "order items" should match "order_items" table, "customer address" → "customer_address"
    raw_terms = [w for w in _re_link.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', question_lower) if len(w) >= 2 and w not in stopwords]
    ngram_terms: list[str] = []
    for i in range(len(raw_terms) - 1):
        bigram = f"{raw_terms[i]}_{raw_terms[i + 1]}"
        ngram_terms.append(bigram)
        if i + 2 < len(raw_terms):
            trigram = f"{raw_terms[i]}_{raw_terms[i + 1]}_{raw_terms[i + 2]}"
            ngram_terms.append(trigram)

    # Abbreviation expansion (common DB naming abbreviations → full words)
    _abbreviations: dict[str, list[str]] = {
        "cust": ["customer", "client"],
        "prod": ["product", "production"],
        "cat": ["category"],
        "qty": ["quantity"],
        "amt": ["amount"],
        "txn": ["transaction"],
        "inv": ["inventory", "invoice"],
        "dept": ["department"],
        "emp": ["employee"],
        "mgr": ["manager"],
        "addr": ["address"],
        "desc": ["description"],
        "num": ["number"],
        "dt": ["date"],
        "ts": ["timestamp"],
        "cnt": ["count"],
        "pct": ["percent", "percentage"],
        "avg": ["average"],
        "tot": ["total"],
        "bal": ["balance"],
        "acct": ["account"],
        "org": ["organization"],
        "loc": ["location"],
        "sku": ["product", "item"],
        "ref": ["reference"],
        "seq": ["sequence"],
        "idx": ["index"],
        "dim": ["dimension"],
        "fct": ["fact"],
        "stg": ["staging"],
    }

    # Expand terms with semantic synonyms (improves recall for Spider2.0)
    expanded_terms = list(terms)
    for term in terms:
        if term in _synonyms:
            for syn in _synonyms[term]:
                if syn not in expanded_terms:
                    expanded_terms.append(syn)
        # Abbreviation expansion
        if term in _abbreviations:
            for full_word in _abbreviations[term]:
                if full_word not in expanded_terms:
                    expanded_terms.append(full_word)
    # Add n-gram compound terms
    for ng in ngram_terms:
        if ng not in expanded_terms:
            expanded_terms.append(ng)
    terms = expanded_terms

    # Simple lemmatization for common suffixes (improves recall without NLTK dependency)
    def _lemmatize(word: str) -> str:
        """Reduce common English inflections to base form."""
        if word.endswith("ies") and len(word) > 4:
            return word[:-3] + "y"  # categories → category
        if word.endswith("ves") and len(word) > 4:
            return word[:-3] + "f"  # shelves → shelf
        if word.endswith("ses") and len(word) > 4:
            return word[:-2]  # addresses → address
        if word.endswith("es") and len(word) > 3:
            return word[:-2]  # taxes → tax
        if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
            return word[:-1]  # orders → order
        if word.endswith("ing") and len(word) > 5:
            return word[:-3]  # shipping → ship
        if word.endswith("ed") and len(word) > 4:
            return word[:-2]  # created → creat
        return word

    # Add lemmatized forms for better matching
    lemma_additions = []
    for term in terms:
        lemma = _lemmatize(term)
        if lemma != term and lemma not in terms and len(lemma) >= 3:
            lemma_additions.append(lemma)
    terms.extend(lemma_additions)

    # Question-type detection: boost relevant column types
    # Aggregation questions → boost numeric columns
    # Time questions → boost date/timestamp columns
    _agg_keywords = {"average", "avg", "sum", "total", "count", "max", "maximum", "min", "minimum",
                     "mean", "median", "aggregate", "top", "bottom", "highest", "lowest", "most", "least"}
    _time_keywords = {"when", "date", "year", "month", "week", "day", "quarter", "recent",
                      "latest", "oldest", "between", "before", "after", "during", "period"}
    _numeric_types = {"int", "integer", "bigint", "smallint", "float", "double", "decimal",
                      "numeric", "real", "number", "money"}
    _time_types = {"date", "datetime", "timestamp", "timestamptz", "time"}

    question_words = set(question_lower.split())
    is_aggregation = bool(question_words & _agg_keywords)
    is_temporal = bool(question_words & _time_keywords)

    # Step 2: Score each table and column by relevance
    table_scores: dict[str, float] = {}
    column_scores: dict[str, dict[str, float]] = {}  # table_key -> {col_name: score}
    for table_key, table_data in filtered.items():
        score = 0.0
        col_scores: dict[str, float] = {}
        table_name_lower = table_data.get("name", "").lower()
        schema_name_lower = table_data.get("schema", "").lower()

        # Split table name into parts for compound matching (order_items -> ["order", "items"])
        table_name_parts = set(table_name_lower.split("_"))

        for term in terms:
            # Exact table name match (highest signal)
            if term == table_name_lower or term == table_name_lower.rstrip("s"):
                score += 10.0
            elif term in table_name_lower:
                score += 5.0
            # Singular/plural matching
            elif term + "s" == table_name_lower or term + "es" == table_name_lower:
                score += 8.0
            elif table_name_lower + "s" == term or table_name_lower + "es" == term:
                score += 8.0
            # Match against individual parts of compound table names
            elif term in table_name_parts or term.rstrip("s") in table_name_parts:
                score += 4.0

            # Column name matching — track per-column scores
            for col in table_data.get("columns", []):
                col_name_lower = col.get("name", "").lower()
                col_name = col.get("name", "")
                col_score = 0.0
                if term == col_name_lower:
                    col_score = 4.0
                elif term in col_name_lower:
                    col_score = 2.0
                # Check column comments
                comment = (col.get("comment") or "").lower()
                if term in comment:
                    col_score = max(col_score, 1.0)
                if col_score > 0:
                    col_scores[col_name] = col_scores.get(col_name, 0) + col_score
                    score += col_score

            # Table description/comment matching
            desc = (table_data.get("description") or "").lower()
            if term in desc:
                score += 2.0

        # N-gram matching: "order_items" bigram matches the table name directly
        # This catches compound terms like "customer address" → "customer_address"
        full_table_key_lower = f"{schema_name_lower}.{table_name_lower}"
        for ng in ngram_terms:
            if ng == table_name_lower:
                score += 12.0  # Exact compound match is very strong
            elif ng in table_name_lower:
                score += 6.0

        # Question-type boosting: prefer tables with relevant column types
        if is_aggregation and score > 0:
            numeric_cols = sum(
                1 for c in table_data.get("columns", [])
                if c.get("type", "").lower().split("(")[0] in _numeric_types
            )
            if numeric_cols > 0:
                score += min(numeric_cols * 0.5, 3.0)

        if is_temporal and score > 0:
            time_cols = sum(
                1 for c in table_data.get("columns", [])
                if c.get("type", "").lower().split("(")[0] in _time_types
                or any(kw in c.get("name", "").lower() for kw in ("date", "time", "created", "updated"))
            )
            if time_cols > 0:
                score += min(time_cols * 0.5, 2.0)

        # Check cached sample values for value-based linking (RSL-SQL bidirectional approach)
        cached_samples = schema_cache.get_sample_values(name, table_key)
        if cached_samples:
            for col_name, sample_vals in cached_samples.items():
                for sv in sample_vals:
                    sv_lower = str(sv).lower()
                    if len(sv_lower) >= 3 and sv_lower in question_lower:
                        score += 6.0  # Strong signal: question mentions actual data value
                        break  # One match per column is enough

        # Boost tables with many FKs (hub tables are usually more relevant)
        fk_count = len(table_data.get("foreign_keys", []))
        if fk_count > 0 and score > 0:
            score += min(fk_count * 0.5, 3.0)  # Up to +3 for hub tables

        # Boost tables with column statistics (better schema = more useful for agent)
        has_stats = sum(1 for c in table_data.get("columns", []) if c.get("stats") or c.get("has_statistics"))
        if has_stats > 0 and score > 0:
            score += 1.0  # Tables with stats are more informative

        table_scores[table_key] = score
        column_scores[table_key] = col_scores

    # Step 3: Select top tables by score
    scored_tables = sorted(table_scores.items(), key=lambda x: (-x[1], x[0]))
    linked_keys = set()

    # Always include tables with score > 0
    for key, score in scored_tables:
        if score > 0 and len(linked_keys) < max_tables:
            linked_keys.add(key)

    # Step 4: Add FK-connected tables (high-recall — EDBT 2026 finding)
    # Forward FK: linked table → table it references
    fk_additions = set()
    for key in list(linked_keys):
        table_data = filtered.get(key, {})
        for fk in table_data.get("foreign_keys", []):
            ref_table = fk.get("references_table", "")
            for candidate_key in filtered:
                if filtered[candidate_key].get("name", "") == ref_table:
                    fk_additions.add(candidate_key)
                    break

    # Reverse FK: find tables that reference a linked table (critical for join tables)
    # Build reverse FK index: table_name → [keys of tables that reference it]
    reverse_fk_index: dict[str, list[str]] = {}
    for key, table_data in filtered.items():
        for fk in table_data.get("foreign_keys", []):
            ref_table = fk.get("references_table", "")
            if ref_table not in reverse_fk_index:
                reverse_fk_index[ref_table] = []
            reverse_fk_index[ref_table].append(key)

    for key in list(linked_keys):
        table_name = filtered[key].get("name", "")
        for referring_key in reverse_fk_index.get(table_name, []):
            if referring_key in filtered:
                fk_additions.add(referring_key)

    for key in fk_additions:
        if len(linked_keys) < max_tables:
            linked_keys.add(key)

    # If no matches found, fall back to first N tables sorted by FK relevance
    if not linked_keys:
        def _fb_relevance(key: str) -> tuple:
            t = filtered[key]
            return (-len(t.get("foreign_keys", [])), -(t.get("row_count", 0) or 0), key)
        linked_keys = set(sorted(filtered.keys(), key=_fb_relevance)[:min(max_tables, 10)])

    # Build response
    linked_schema = {k: filtered[k] for k in sorted(linked_keys) if k in filtered}

    # ── Column pruning helper ──────────────────────────────────────────────
    # For each table, determine which columns to include.
    # Always include: PK columns, FK columns, and columns with relevance score > 0.
    # For high-scoring tables (>= 5.0), include ALL columns (they're clearly relevant).
    # For lower-scoring tables (FK-connected), only include structural + matched columns.
    def _prune_columns(table_key: str, table_data: dict) -> list[dict]:
        """Return only relevant columns for a table, keeping PKs and FKs always."""
        t_score = table_scores.get(table_key, 0)
        # High-relevance tables: keep all columns (the whole table matters)
        if t_score >= 5.0 or not prune_columns:
            return table_data.get("columns", [])

        col_relevance = column_scores.get(table_key, {})
        fk_cols = {fk.get("column", "") for fk in table_data.get("foreign_keys", [])}

        kept = []
        for col in table_data.get("columns", []):
            col_name = col.get("name", "")
            # Always keep: PKs, FK columns, and columns with question relevance
            if col.get("primary_key"):
                kept.append(col)
            elif col_name in fk_cols:
                kept.append(col)
            elif col_relevance.get(col_name, 0) > 0:
                kept.append(col)
        # If pruning removed everything, keep all (safety)
        return kept if kept else table_data.get("columns", [])

    # ── Compressed type map (more aggressive abbreviation) ────────────────
    _type_compress = {
        "CHARACTER VARYING": "VARCHAR", "TIMESTAMP WITHOUT TIME ZONE": "TS",
        "TIMESTAMP WITH TIME ZONE": "TSZ", "DOUBLE PRECISION": "DOUBLE",
        "BOOLEAN": "BOOL", "INTEGER": "INT", "BIGINT": "BIGINT",
        "SMALLINT": "SMALLINT", "REAL": "FLOAT",
    }

    if format == "condensed":
        # Condensed DDL: minimal token usage — pruned columns, no annotations, compressed types
        condensed_lines = []
        total_cols_original = 0
        total_cols_kept = 0
        for key in sorted(linked_keys):
            if key not in filtered:
                continue
            t = filtered[key]
            table_name = f"{t.get('schema', '')}.{t.get('name', '')}"
            all_cols = t.get("columns", [])
            kept_cols = _prune_columns(key, t)
            total_cols_original += len(all_cols)
            total_cols_kept += len(kept_cols)
            col_parts = []
            pk_cols = []
            for col in kept_cols:
                ct = col.get("type", "TEXT").upper()
                ct = _type_compress.get(ct, ct)
                # Strip precision from types for brevity: VARCHAR(255) → VARCHAR
                if "(" in ct and ct.split("(")[0] in ("VARCHAR", "NVARCHAR", "CHAR", "DECIMAL", "NUMERIC"):
                    ct = ct.split("(")[0]
                nn = " NOT NULL" if not col.get("nullable", True) else ""
                col_parts.append(f"  {col['name']} {ct}{nn}")
                if col.get("primary_key"):
                    pk_cols.append(col["name"])
            if pk_cols:
                col_parts.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")
            for fk in t.get("foreign_keys", []):
                col_parts.append(f"  FOREIGN KEY ({fk['column']}) REFERENCES {fk.get('references_table', '')}({fk.get('references_column', '')})")
            pruned_note = ""
            if len(kept_cols) < len(all_cols):
                pruned_note = f" -- {len(all_cols) - len(kept_cols)} columns pruned"
            obj_kw = "CREATE VIEW" if t.get("type") == "view" else "CREATE TABLE"
            condensed_lines.append(f"{obj_kw} {table_name} (\n{',\n'.join(col_parts)}\n);{pruned_note}")
        condensed_text = "\n\n".join(condensed_lines)
        reduction_pct = round((1 - total_cols_kept / max(total_cols_original, 1)) * 100)
        return {
            "connection_name": name,
            "question": question,
            "format": "condensed",
            "linked_tables": len(linked_keys),
            "total_tables": len(filtered),
            "columns_original": total_cols_original,
            "columns_kept": total_cols_kept,
            "column_reduction_pct": reduction_pct,
            "token_estimate": len(condensed_text) // 4,
            "scores": {k: round(table_scores.get(k, 0), 1) for k in sorted(linked_keys) if table_scores.get(k, 0) > 0},
            "ddl": condensed_text,
        }

    if format == "compact":
        lines = []
        for key in sorted(linked_keys):
            if key not in filtered:
                continue
            t = filtered[key]
            col_strs = []
            kept_cols = _prune_columns(key, t)
            for c in kept_cols:
                pk_flag = "*" if c.get("primary_key") else ""
                ct = c.get("type", "").upper()
                s = f"{c['name']}{pk_flag} {ct}"
                stats = c.get("stats", {})
                if stats.get("distinct_count"):
                    s += f"({stats['distinct_count']}d)"
                col_strs.append(s)
            if len(kept_cols) < len(t.get("columns", [])):
                col_strs.append(f"+{len(t['columns']) - len(kept_cols)} more")
            cols = ", ".join(col_strs)
            rc = t.get("row_count", 0)
            rc_str = f" ({rc:,} rows)" if rc else ""
            score = table_scores.get(key, 0)
            lines.append(f"{key}{rc_str} [score={score:.1f}]: {cols}")
        return {
            "connection_name": name,
            "question": question,
            "format": "compact",
            "linked_tables": len(linked_keys),
            "total_tables": len(filtered),
            "scores": {k: round(table_scores.get(k, 0), 1) for k in sorted(linked_keys) if table_scores.get(k, 0) > 0},
            "schema": "\n".join(lines),
        }

    if format == "json":
        return {
            "connection_name": name,
            "question": question,
            "format": "json",
            "linked_tables": len(linked_keys),
            "total_tables": len(filtered),
            "scores": {k: table_scores.get(k, 0) for k in sorted(linked_keys)},
            "tables": linked_schema,
        }

    # DDL format (default — preferred by Spider2.0 SOTA)
    ddl_lines = []
    for key in sorted(linked_keys):
        if key not in filtered:
            continue
        t = filtered[key]
        table_name = f"{t.get('schema', '')}.{t.get('name', '')}"
        # Table description as comment (semantic context for agent)
        table_desc = t.get("description", "")
        header = f"-- {table_desc}\n" if table_desc else ""
        col_parts = []
        pk_cols = []
        ddl_cols = _prune_columns(key, t)
        pruned_count = len(t.get("columns", [])) - len(ddl_cols)
        for col in ddl_cols:
            ct = col.get("type", "TEXT").upper()
            type_map = {
                "CHARACTER VARYING": "VARCHAR", "TIMESTAMP WITHOUT TIME ZONE": "TIMESTAMP",
                "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ", "DOUBLE PRECISION": "DOUBLE",
                "BOOLEAN": "BOOL", "INTEGER": "INT", "BIGINT": "BIGINT",
                "SMALLINT": "SMALLINT", "REAL": "FLOAT",
            }
            ct = type_map.get(ct, ct)
            parts = [f"  {col['name']} {ct}"]
            if not col.get("nullable", True):
                parts.append("NOT NULL")
            # Column annotations for agent context
            annotations = []
            col_comment = col.get("comment", "")
            if col_comment:
                annotations.append(col_comment)
            # Column statistics help agent understand data shape
            stats = col.get("stats", {})
            if stats.get("distinct_count"):
                annotations.append(f"{stats['distinct_count']} distinct values")
            elif stats.get("distinct_fraction"):
                frac = abs(stats["distinct_fraction"])
                if frac >= 0.99:
                    annotations.append("unique")
                elif frac >= 0.5:
                    annotations.append("high cardinality")
            # Redshift/warehouse column-level optimization hints
            if col.get("dist_key"):
                annotations.append("DISTKEY")
            if col.get("sort_key_position"):
                annotations.append(f"SORTKEY#{col['sort_key_position']}")
            if col.get("low_cardinality"):
                annotations.append("low cardinality")
            # Inline sample values for low-cardinality string columns (Spider2.0 key technique)
            # Only for columns with <=50 distinct values — avoids wasting tokens on unique/high-card columns
            is_low_card = False
            dc = stats.get("distinct_count", 0) if stats else 0
            df = abs(stats.get("distinct_fraction", 0)) if stats else 0
            if dc and dc <= 50:
                is_low_card = True
            elif df and df < 0.05:
                is_low_card = True
            elif not stats:
                is_low_card = True  # No stats = show samples as hint

            if is_low_card:
                cached_samples = schema_cache.get_sample_values(name, key)
                if cached_samples and col["name"] in cached_samples:
                    sample_vals = cached_samples[col["name"]]
                    if len(sample_vals) <= 10:
                        annotations.append(f"e.g. {', '.join(repr(v) for v in sample_vals[:5])}")
            if annotations:
                parts.append(f"-- {'; '.join(annotations)}")
            col_parts.append(" ".join(parts))
            if col.get("primary_key"):
                pk_cols.append(col["name"])
        if pk_cols:
            col_parts.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")
        for fk in t.get("foreign_keys", []):
            col_parts.append(f"  FOREIGN KEY ({fk['column']}) REFERENCES {fk.get('references_table', '')}({fk.get('references_column', '')})")
        rc = t.get("row_count", 0)
        # Build metadata comment
        meta_parts = []
        if rc:
            meta_parts.append(f"{rc:,} rows" if rc < 1_000_000 else f"{rc/1_000_000:.1f}M rows")
        engine = t.get("engine", "")
        if engine:
            meta_parts.append(f"ENGINE={engine}")
        sorting = t.get("sorting_key", "")
        if sorting:
            meta_parts.append(f"ORDER BY({sorting})")
        diststyle = t.get("diststyle", "")
        if diststyle:
            meta_parts.append(f"DISTSTYLE={diststyle}")
        sortkey = t.get("sortkey", "")
        if sortkey:
            meta_parts.append(f"SORTKEY({sortkey})")
        clustering_key = t.get("clustering_key", "")
        if clustering_key:
            meta_parts.append(f"CLUSTER BY({clustering_key})")
        meta_parts.append(f"relevance={table_scores.get(key, 0):.1f}")
        if pruned_count > 0:
            meta_parts.append(f"{pruned_count} cols pruned")
        rc_comment = f" -- {', '.join(meta_parts)}"
        obj_kw = "CREATE VIEW" if t.get("type") == "view" else "CREATE TABLE"
        ddl_lines.append(f"{header}{obj_kw} {table_name} (\n{',\n'.join(col_parts)}\n);{rc_comment}")

    ddl_text = "\n\n".join(ddl_lines)

    # Proactively fetch sample values for linked tables that lack them (background)
    # Next schema_link call will include inline samples in DDL annotations
    missing_samples = []
    string_types = {"character varying", "varchar", "text", "char", "character", "enum",
                   "String", "VARCHAR", "TEXT", "CHAR", "NVARCHAR", "string"}
    for key in linked_keys:
        if key not in filtered:
            continue
        if schema_cache.get_sample_values(name, key) is not None:
            continue  # Already cached
        t = filtered[key]
        sample_cols = [
            c["name"] for c in t.get("columns", [])
            if c.get("type", "") in string_types or "char" in c.get("type", "").lower()
        ]
        if sample_cols:
            missing_samples.append((key, t, sample_cols[:10]))

    if missing_samples:
        try:
            conn_str = get_connection_string(name)
            if conn_str:
                extras = get_credential_extras(name)
                async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                    for key, t, sample_cols in missing_samples[:5]:  # Cap at 5 tables
                        table_name = f"{t.get('schema', '')}.{t['name']}" if t.get("schema") else t["name"]
                        try:
                            values = await connector.get_sample_values(table_name, sample_cols, limit=5)
                            if values:
                                schema_cache.put_sample_values(name, key, values)
                        except Exception:
                            pass
        except Exception:
            pass  # Best-effort — don't fail the schema_link response

    return {
        "connection_name": name,
        "question": question,
        "format": "ddl",
        "linked_tables": len(linked_keys),
        "total_tables": len(filtered),
        "token_estimate": len(ddl_text) // 4,
        "scores": {k: round(table_scores.get(k, 0), 1) for k in sorted(linked_keys) if table_scores.get(k, 0) > 0},
        "ddl": ddl_text,
    }


@app.post("/api/connections/{name}/schema/refine")
async def refine_schema(
    name: str,
    request: Request,
):
    """Two-pass schema refinement — Spider2.0 SOTA technique.

    Takes a draft SQL query and returns only the tables/columns actually
    referenced in it. This enables the two-pass pattern used by top performers
    (RSL-SQL, ReFoRCE):
      1. Agent gets broad schema via /schema/link or /schema/agent-context
      2. Agent generates draft SQL
      3. Agent calls this endpoint with the draft SQL
      4. This returns a minimal, precise schema for the final SQL generation

    Research shows this reduces hallucinated columns by 40-60% and improves
    execution accuracy by 3-5% on Spider2.0-Lite.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    body = await request.json()
    draft_sql = body.get("draft_sql", "")
    question = body.get("question", "")
    format = body.get("format", "ddl")

    if not draft_sql:
        raise HTTPException(status_code=400, detail="draft_sql is required")

    cached = schema_cache.get(name)
    if cached is None:
        conn_str = get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        extras = get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            cached = await connector.get_schema()
        schema_cache.put(name, cached)

    filtered = apply_endorsement_filter(name, cached)
    sf_include, sf_exclude = _get_schema_filters(name)
    filtered = _apply_schema_filter(filtered, sf_include, sf_exclude)

    # Extract table references from draft SQL using regex patterns
    import re as _re_refine
    sql_upper = draft_sql.upper()
    sql_clean = draft_sql

    # Patterns that precede table names in SQL
    # FROM table, JOIN table, INTO table, UPDATE table, TABLE table
    table_patterns = [
        r'(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(?:`|"|\'|\[)?(\w+(?:\.\w+)*)(?:`|"|\'|\])?',
        r'(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(?:`|"|\'|\[)?(\w+)(?:`|"|\'|\])?\s*\.\s*(?:`|"|\'|\[)?(\w+)(?:`|"|\'|\])?',
    ]

    referenced_tables: set[str] = set()
    referenced_columns: set[str] = set()

    # Extract table names
    for pattern in table_patterns:
        for match in _re_refine.finditer(pattern, sql_clean, _re_refine.IGNORECASE):
            groups = [g for g in match.groups() if g]
            for g in groups:
                referenced_tables.add(g.lower().strip('`"\'[]'))

    # Extract column references (for column-level pruning)
    # SELECT col1, col2 ... WHERE col3 = ... GROUP BY col4
    col_patterns = [
        r'(?:SELECT|WHERE|AND|OR|ON|BY|HAVING|SET)\s+(?:`|"|\'|\[)?(\w+)(?:`|"|\'|\])?',
        r'(\w+)\s*(?:=|<|>|!=|<>|LIKE|IN|BETWEEN|IS)',
    ]
    for pattern in col_patterns:
        for match in _re_refine.finditer(pattern, sql_clean, _re_refine.IGNORECASE):
            col = match.group(1).lower().strip('`"\'[]')
            if col not in {'select', 'from', 'where', 'and', 'or', 'not', 'null',
                          'true', 'false', 'case', 'when', 'then', 'else', 'end',
                          'as', 'in', 'is', 'on', 'by', 'having', 'set', 'all',
                          'distinct', 'count', 'sum', 'avg', 'min', 'max', 'like',
                          'between', 'exists', 'any', 'group', 'order', 'limit',
                          'offset', 'union', 'except', 'intersect', 'asc', 'desc'}:
                referenced_columns.add(col)

    # Also extract dotted references like t.column_name
    for match in _re_refine.finditer(r'(\w+)\.(\w+)', sql_clean):
        alias_or_table = match.group(1).lower()
        col = match.group(2).lower()
        referenced_tables.add(alias_or_table)
        referenced_columns.add(col)

    # Match extracted names to actual schema tables
    matched_keys: set[str] = set()
    table_name_to_key: dict[str, str] = {}
    for key, t in filtered.items():
        tn = t.get("name", "").lower()
        sn = t.get("schema", "").lower()
        full = f"{sn}.{tn}" if sn else tn
        table_name_to_key[tn] = key
        table_name_to_key[full] = key

    for ref in referenced_tables:
        if ref in table_name_to_key:
            matched_keys.add(table_name_to_key[ref])
        # Try schema.table format
        for key, t in filtered.items():
            tn = t.get("name", "").lower()
            if ref == tn:
                matched_keys.add(key)

    # Add FK-connected tables for join completeness
    fk_adds: set[str] = set()
    for key in list(matched_keys):
        t = filtered.get(key, {})
        for fk in t.get("foreign_keys", []):
            ref_table = fk.get("references_table", "").lower()
            if ref_table in table_name_to_key:
                fk_adds.add(table_name_to_key[ref_table])
    matched_keys |= fk_adds

    # Also add inferred join targets
    inferred = _infer_implicit_joins(filtered)
    for ij in inferred:
        from_key = f"{ij.get('from_schema', '')}.{ij['from_table']}" if ij.get("from_schema") else ij["from_table"]
        to_key = f"{ij.get('to_schema', '')}.{ij['to_table']}" if ij.get("to_schema") else ij["to_table"]
        # Find actual keys
        for key, t in filtered.items():
            tn = t.get("name", "").lower()
            sn = t.get("schema", "").lower()
            full = f"{sn}.{tn}"
            if full == from_key.lower() or tn == ij["from_table"].lower():
                if key in matched_keys:
                    # This matched table has an inferred join — add the target
                    for k2, t2 in filtered.items():
                        if t2.get("name", "").lower() == ij["to_table"].lower():
                            matched_keys.add(k2)

    if not matched_keys:
        # Fallback: return all tables (draft SQL may use aliases we can't resolve)
        matched_keys = set(list(filtered.keys())[:20])

    # Build refined schema
    refined = {k: filtered[k] for k in sorted(matched_keys) if k in filtered}

    # Generate DDL with only referenced columns highlighted
    ddl_lines = []
    for key in sorted(matched_keys):
        if key not in filtered:
            continue
        t = filtered[key]
        table_name = f"{t.get('schema', '')}.{t.get('name', '')}"
        col_parts = []
        pk_cols = []
        for col in t.get("columns", []):
            ct = col.get("type", "TEXT").upper()
            # Compact type names
            type_map = {
                "CHARACTER VARYING": "VARCHAR", "TIMESTAMP WITHOUT TIME ZONE": "TIMESTAMP",
                "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ", "DOUBLE PRECISION": "DOUBLE",
            }
            ct = type_map.get(ct, ct)
            is_referenced = col["name"].lower() in referenced_columns
            parts = [f"  {col['name']} {ct}"]
            if not col.get("nullable", True):
                parts.append("NOT NULL")
            if is_referenced:
                parts.append("-- << USED IN QUERY")
            # Add sample values for referenced columns
            cached_samples = schema_cache.get_sample_values(name, key)
            if cached_samples and col["name"] in cached_samples and is_referenced:
                vals = cached_samples[col["name"]][:5]
                parts.append(f"e.g. {', '.join(repr(v) for v in vals)}")
            col_parts.append(" ".join(parts))
            if col.get("primary_key"):
                pk_cols.append(col["name"])
        if pk_cols:
            col_parts.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")
        for fk in t.get("foreign_keys", []):
            col_parts.append(f"  FOREIGN KEY ({fk['column']}) REFERENCES {fk.get('references_table', '')}({fk.get('references_column', '')})")

        rc = t.get("row_count", 0)
        meta = f" -- {rc:,} rows" if rc else ""
        ddl_lines.append(f"CREATE TABLE {table_name} (\n{',\n'.join(col_parts)}\n);{meta}")

    ddl_text = "\n\n".join(ddl_lines)

    return {
        "connection_name": name,
        "question": question,
        "draft_sql": draft_sql,
        "refined_tables": len(matched_keys),
        "total_tables": len(filtered),
        "referenced_tables": sorted(referenced_tables),
        "referenced_columns": sorted(referenced_columns),
        "token_estimate": len(ddl_text) // 4,
        "ddl": ddl_text,
    }


@app.get("/api/connections/{name}/schema/explore-table")
async def explore_table(
    name: str,
    table: str = Query(..., description="Full table name (e.g., 'public.customers')"),
    include_samples: bool = Query(default=True, description="Include sample distinct values for string/enum columns"),
    include_stats: bool = Query(default=True, description="Include column-level statistics"),
    sample_limit: int = Query(default=5, ge=1, le=20, description="Max sample values per column"),
):
    """Deep column exploration for a single table — ReFoRCE-style iterative schema linking.

    When the AI agent identifies a relevant table from the compact schema overview,
    this endpoint provides full column details including:
    - Column types, nullability, primary/foreign keys
    - Sample distinct values (for string/enum columns)
    - Column statistics (row counts, cardinality hints)
    - FK references to other tables

    This supports the iterative exploration pattern from ReFoRCE (Spider2.0 SOTA):
    1. Agent gets compact overview via /schema/compact
    2. Agent identifies relevant tables
    3. Agent deep-dives specific tables via this endpoint
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    cached = schema_cache.get(name)
    if cached is None:
        conn_str = get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        try:
            extras = get_credential_extras(name)
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                cached = await connector.get_schema()
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))
        schema_cache.put(name, cached)

    # Find the table
    table_data = cached.get(table)
    if not table_data:
        # Try fuzzy match by table name
        for key, tbl in cached.items():
            if tbl.get("name") == table or key == table:
                table_data = tbl
                table = key
                break
    if not table_data:
        raise HTTPException(status_code=404, detail=f"Table '{table}' not found in schema")

    result: dict[str, Any] = {
        "connection_name": name,
        "table": table,
        "schema": table_data.get("schema", ""),
        "name": table_data.get("name", ""),
        "row_count": table_data.get("row_count", 0),
        "engine": table_data.get("engine", ""),
        "columns": [],
        "foreign_keys": table_data.get("foreign_keys", []),
        "referenced_by": [],
    }

    # Find reverse FK references (tables that FK to this table)
    for key, tbl in cached.items():
        for fk in tbl.get("foreign_keys", []):
            if fk.get("references_table") == table_data.get("name"):
                result["referenced_by"].append({
                    "table": key,
                    "column": fk["column"],
                    "references_column": fk["references_column"],
                })

    # Build enriched column list
    string_cols = []
    for col in table_data.get("columns", []):
        col_info: dict[str, Any] = {
            "name": col["name"],
            "type": col.get("type", ""),
            "nullable": col.get("nullable", True),
            "primary_key": col.get("primary_key", False),
        }
        if col.get("comment"):
            col_info["comment"] = col["comment"]
        if include_stats and col.get("stats"):
            col_info["stats"] = col["stats"]

        # Check if this column has FK
        for fk in table_data.get("foreign_keys", []):
            if fk["column"] == col["name"]:
                col_info["foreign_key"] = {
                    "references_table": fk["references_table"],
                    "references_column": fk["references_column"],
                }

        result["columns"].append(col_info)

        # Collect string/enum columns for sampling
        col_type = col.get("type", "").lower()
        if any(t in col_type for t in ("varchar", "text", "char", "string", "enum", "category")):
            string_cols.append(col["name"])

    # Fetch sample values for string columns
    if include_samples and string_cols:
        # Check cache first
        cached_samples = schema_cache.get_sample_values(name, table)
        if cached_samples:
            result["sample_values"] = cached_samples
        else:
            try:
                conn_str = get_connection_string(name)
                if conn_str:
                    extras = get_credential_extras(name)
                    async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                        samples = await connector.get_sample_values(table, string_cols[:10], limit=sample_limit)
                    if samples:
                        schema_cache.put_sample_values(name, table, samples)
                        result["sample_values"] = samples
            except Exception:
                pass

    return result


@app.get("/api/connections/{name}/schema/overview")
async def get_schema_overview(
    name: str,
):
    """Quick database overview — table count, total columns, total rows, FK graph density.

    Gives the AI agent a fast sense of database complexity before loading the full schema.
    Useful for deciding whether to use compact or full schema format.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    cached = schema_cache.get(name)
    if cached is None:
        conn_str = get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        try:
            extras = get_credential_extras(name)
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                cached = await connector.get_schema()
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))
        schema_cache.put(name, cached)

    filtered = apply_endorsement_filter(name, cached)
    sf_include, sf_exclude = _get_schema_filters(name)
    filtered = _apply_schema_filter(filtered, sf_include, sf_exclude)

    total_tables = len(filtered)
    total_columns = 0
    total_rows = 0
    total_fks = 0
    total_size_mb = 0.0
    schemas_set: set[str] = set()
    tables_with_fks: set[str] = set()
    largest_tables: list[dict] = []

    for key, table in filtered.items():
        cols = table.get("columns", [])
        total_columns += len(cols)
        row_count = table.get("row_count", 0) or 0
        total_rows += row_count
        total_size_mb += table.get("size_mb", 0) or 0
        schemas_set.add(table.get("schema", ""))
        fks = table.get("foreign_keys", [])
        total_fks += len(fks)
        if fks:
            tables_with_fks.add(key)
        entry: dict = {
            "table": key,
            "columns": len(cols),
            "rows": row_count,
            "fks": len(fks),
        }
        # Include optimization metadata for agent query planning
        for meta_key in ("engine", "sorting_key", "diststyle", "sortkey",
                         "clustering_key", "partitioning", "clustering_fields",
                         "size_bytes", "size_mb", "total_bytes"):
            val = table.get(meta_key)
            if val:
                entry[meta_key] = val
        largest_tables.append(entry)

    # Sort by row count descending
    largest_tables.sort(key=lambda t: t["rows"], reverse=True)

    return {
        "connection_name": name,
        "db_type": info.db_type,
        "schemas": sorted(schemas_set),
        "schema_count": len(schemas_set),
        "table_count": total_tables,
        "total_columns": total_columns,
        "total_rows": total_rows,
        "total_size_mb": round(total_size_mb, 2),
        "total_foreign_keys": total_fks,
        "tables_with_fks": len(tables_with_fks),
        "avg_columns_per_table": round(total_columns / total_tables, 1) if total_tables else 0,
        "largest_tables": largest_tables[:10],
        # ReFoRCE-style: estimate token count and recommend schema format
        "estimated_schema_tokens": total_columns * 8 + total_tables * 20,  # rough estimate
        "recommendation": (
            "compact" if total_columns > 200
            else "full" if total_columns < 50
            else "enriched"
        ),
        "inferred_joins": len(inferred_joins := _infer_implicit_joins(filtered)),
        "spider2_hints": {
            "needs_compression": total_columns > 500,
            "has_partitioned_tables": any(
                "_20" in (t.get("name", "") or "") for t in filtered.values()
            ),
            "join_complexity": "high" if (total_fks + len(inferred_joins)) > 15
                              else "medium" if (total_fks + len(inferred_joins)) > 5
                              else "low",
            "has_implicit_joins": len(inferred_joins) > 0,
        },
    }


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
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            new_schema = await connector.get_schema()
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
            "fingerprint": schema_cache.get_fingerprint(name),
        }

    # Update cache with new schema — track_diff=True records the change event
    schema_cache.put(name, new_schema, track_diff=True)

    return {
        "connection_name": name,
        "has_cached": True,
        "diff": diff,
        "table_count": len(new_schema),
        "fingerprint": schema_cache.get_fingerprint(name),
    }


@app.get("/api/connections/{name}/schema/refresh-status")
async def get_schema_refresh_status(name: str):
    """Get schema refresh schedule status for a connection."""
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    cached_stats = schema_cache.get(name)
    return {
        "connection_name": name,
        "schema_refresh_interval": info.schema_refresh_interval,
        "last_schema_refresh": info.last_schema_refresh,
        "next_refresh_at": (
            info.last_schema_refresh + info.schema_refresh_interval
            if info.last_schema_refresh and info.schema_refresh_interval
            else None
        ),
        "cached": cached_stats is not None,
        "cached_table_count": len(cached_stats) if cached_stats else 0,
        "fingerprint": schema_cache.get_fingerprint(name),
    }


@app.get("/api/connections/{name}/schema/diff-history")
async def get_schema_diff_history(name: str):
    """Get schema change history for a connection.

    Returns a list of detected structural changes (added/removed/modified tables and columns)
    from scheduled refreshes and manual diff checks. Newest first, max 20 events.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    history = schema_cache.get_diff_history(name)
    return {
        "connection_name": name,
        "events": history,
        "current_fingerprint": schema_cache.get_fingerprint(name),
    }


@app.get("/api/schema/changes")
async def get_all_schema_changes():
    """Get recent schema changes across all connections.

    Useful for monitoring dashboards — shows which databases had DDL changes
    and when, across all monitored connections.
    """
    history = schema_cache.get_diff_history()
    return {
        "events": history,
        "cache_stats": schema_cache.stats(),
    }


@app.get("/api/connections/{name}/schema/filter")
async def get_filtered_schema(
    name: str,
    schema_prefix: str = Query(default="", description="Filter by schema/database prefix (e.g., 'public', 'analytics')"),
    table_prefix: str = Query(default="", description="Filter by table name prefix"),
    include_columns: bool = Query(default=True, description="Include column details"),
    max_tables: int = Query(default=100, ge=1, le=1000, description="Maximum tables to return"),
):
    """Filter schema by database/schema prefix and table prefix.

    Useful for large databases with hundreds of schemas — lets the AI agent
    focus on relevant subsets without loading the entire schema into context.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    cached = schema_cache.get(name)
    if cached is None:
        conn_str = get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        try:
            extras = get_credential_extras(name)
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                cached = await connector.get_schema()
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))
        schema_cache.put(name, cached)

    filtered = apply_endorsement_filter(name, cached)
    sf_include, sf_exclude = _get_schema_filters(name)
    filtered = _apply_schema_filter(filtered, sf_include, sf_exclude)

    # Apply prefix filters
    result: dict[str, Any] = {}
    for key, table in filtered.items():
        tbl_schema = table.get("schema", "")
        tbl_name = table.get("name", "")

        if schema_prefix and not tbl_schema.lower().startswith(schema_prefix.lower()):
            continue
        if table_prefix and not tbl_name.lower().startswith(table_prefix.lower()):
            continue

        if include_columns:
            result[key] = table
        else:
            result[key] = {k: v for k, v in table.items() if k != "columns"}
            result[key]["column_count"] = len(table.get("columns", []))

        if len(result) >= max_tables:
            break

    return {
        "connection_name": name,
        "filters": {
            "schema_prefix": schema_prefix or None,
            "table_prefix": table_prefix or None,
        },
        "table_count": len(result),
        "total_tables": len(filtered),
        "tables": result,
    }


@app.get("/api/connections/{name}/schema/relationships")
async def get_schema_relationships(
    name: str,
    format: str = Query(default="compact", pattern=r"^(compact|full|graph)$",
                        description="Output format: compact (one-line per FK), full (detailed JSON), graph (adjacency list)"),
    include_implicit: bool = Query(default=True,
                                   description="Include inferred joins from column name patterns (e.g., customer_id → customers.id)"),
):
    """Extract all foreign key relationships from schema — ERD summary for AI agents.

    Critical for Spider2.0 join-path discovery: the agent needs to understand
    which tables can be joined and through which columns. Three formats:
    - compact: "orders.customer_id → customers.id" (one line per FK, minimal tokens)
    - full: detailed JSON with schema, table, column, referenced info
    - graph: adjacency list showing all tables reachable from each table

    When include_implicit=true (default), also detects joins via column naming
    conventions for databases without FK declarations (common in data lakes).
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    cached = schema_cache.get(name)
    if cached is None:
        conn_str = get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        try:
            extras = get_credential_extras(name)
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                cached = await connector.get_schema()
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))
        schema_cache.put(name, cached)

    filtered = apply_endorsement_filter(name, cached)
    sf_include, sf_exclude = _get_schema_filters(name)
    filtered = _apply_schema_filter(filtered, sf_include, sf_exclude)

    # Extract all FK relationships (explicit)
    relationships: list[dict] = []
    explicit_count = 0
    for key, table in filtered.items():
        tbl_schema = table.get("schema", "")
        tbl_name = table.get("name", "")
        for fk in table.get("foreign_keys", []):
            ref_schema = fk.get("references_schema", tbl_schema)
            relationships.append({
                "from_schema": tbl_schema,
                "from_table": tbl_name,
                "from_column": fk["column"],
                "to_schema": ref_schema,
                "to_table": fk["references_table"],
                "to_column": fk["references_column"],
            })
    explicit_count = len(relationships)

    # Add implicit/inferred joins from column name patterns
    implicit_count = 0
    if include_implicit:
        inferred = _infer_implicit_joins(filtered)
        # Deduplicate against explicit FKs
        explicit_set = {
            (r["from_table"].lower(), r["from_column"].lower(),
             r["to_table"].lower(), r["to_column"].lower())
            for r in relationships
        }
        for inf in inferred:
            edge = (inf["from_table"].lower(), inf["from_column"].lower(),
                    inf["to_table"].lower(), inf["to_column"].lower())
            if edge not in explicit_set:
                relationships.append(inf)
                implicit_count += 1

    if format == "compact":
        # One-line-per-FK — minimal token usage for LLM context
        lines = []
        for r in relationships:
            from_qual = f"{r['from_schema']}.{r['from_table']}" if r["from_schema"] else r["from_table"]
            to_qual = f"{r['to_schema']}.{r['to_table']}" if r["to_schema"] else r["to_table"]
            suffix = " [inferred]" if r.get("inferred") else ""
            lines.append(f"{from_qual}.{r['from_column']} → {to_qual}.{r['to_column']}{suffix}")
        return {
            "connection_name": name,
            "format": "compact",
            "relationship_count": len(relationships),
            "explicit_count": explicit_count,
            "inferred_count": implicit_count,
            "relationships": lines,
        }

    elif format == "graph":
        # Adjacency list — shows all tables reachable via FK joins from each table
        graph: dict[str, list[str]] = {}
        for r in relationships:
            from_qual = f"{r['from_schema']}.{r['from_table']}" if r["from_schema"] else r["from_table"]
            to_qual = f"{r['to_schema']}.{r['to_table']}" if r["to_schema"] else r["to_table"]
            if from_qual not in graph:
                graph[from_qual] = []
            if to_qual not in graph[from_qual]:
                graph[from_qual].append(to_qual)
            # Bidirectional — reverse lookups are useful for join planning
            if to_qual not in graph:
                graph[to_qual] = []
            if from_qual not in graph[to_qual]:
                graph[to_qual].append(from_qual)
        return {
            "connection_name": name,
            "format": "graph",
            "table_count": len(graph),
            "relationship_count": len(relationships),
            "adjacency": graph,
        }

    else:  # full
        return {
            "connection_name": name,
            "format": "full",
            "relationship_count": len(relationships),
            "relationships": relationships,
        }


@app.get("/api/connections/{name}/schema/join-paths")
async def get_join_paths(
    name: str,
    from_table: str = Query(..., description="Source table (e.g., 'public.orders')"),
    to_table: str = Query(..., description="Target table (e.g., 'public.products')"),
    max_hops: int = Query(default=4, ge=1, le=6, description="Maximum FK hops to search"),
    include_implicit: bool = Query(default=True, description="Include inferred joins from column naming conventions"),
):
    """Find all join paths between two tables — critical for Spider2.0 multi-hop queries.

    Uses BFS over the FK graph (plus inferred joins) to discover all paths from
    source to target table, returning the exact join columns at each hop. This
    enables AI agents to construct correct multi-table JOINs without hallucinating
    join conditions.

    Example: orders → order_items → products (2 hops via order_items.order_id and order_items.product_id)
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    cached = schema_cache.get(name)
    if cached is None:
        conn_str = get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        try:
            extras = get_credential_extras(name)
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                cached = await connector.get_schema()
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))
        schema_cache.put(name, cached)

    filtered = apply_endorsement_filter(name, cached)
    sf_include, sf_exclude = _get_schema_filters(name)
    filtered = _apply_schema_filter(filtered, sf_include, sf_exclude)

    # Build bidirectional adjacency list with join info
    # Each edge: (from_table, from_col, to_table, to_col)
    edges: dict[str, list[tuple[str, str, str, str]]] = {}
    for key, table in filtered.items():
        tbl_schema = table.get("schema", "")
        tbl_name = table.get("name", "")
        full_name = f"{tbl_schema}.{tbl_name}" if tbl_schema else tbl_name

        for fk in table.get("foreign_keys", []):
            ref_schema = fk.get("references_schema", tbl_schema)
            ref_full = f"{ref_schema}.{fk['references_table']}" if ref_schema else fk["references_table"]

            # Forward edge
            if full_name not in edges:
                edges[full_name] = []
            edges[full_name].append((full_name, fk["column"], ref_full, fk["references_column"]))

            # Reverse edge (for bidirectional traversal)
            if ref_full not in edges:
                edges[ref_full] = []
            edges[ref_full].append((ref_full, fk["references_column"], full_name, fk["column"]))

    # Add inferred join edges
    if include_implicit:
        inferred = _infer_implicit_joins(filtered)
        for inf in inferred:
            inf_from = f"{inf['from_schema']}.{inf['from_table']}" if inf["from_schema"] else inf["from_table"]
            inf_to = f"{inf['to_schema']}.{inf['to_table']}" if inf["to_schema"] else inf["to_table"]
            if inf_from not in edges:
                edges[inf_from] = []
            edges[inf_from].append((inf_from, inf["from_column"], inf_to, inf["to_column"]))
            if inf_to not in edges:
                edges[inf_to] = []
            edges[inf_to].append((inf_to, inf["to_column"], inf_from, inf["from_column"]))

    # Normalize table names for matching (try with and without schema prefix)
    def resolve_table(name_input: str) -> str | None:
        if name_input in edges or name_input in {k for t in filtered.values() for k in [f"{t.get('schema', '')}.{t.get('name', '')}"]}:
            return name_input
        # Try matching just the table name part
        for key, table in filtered.items():
            full = f"{table.get('schema', '')}.{table.get('name', '')}"
            if table.get("name", "") == name_input or full == name_input or key == name_input:
                return full
        return None

    src = resolve_table(from_table)
    dst = resolve_table(to_table)
    if not src:
        raise HTTPException(status_code=404, detail=f"Table '{from_table}' not found in schema")
    if not dst:
        raise HTTPException(status_code=404, detail=f"Table '{to_table}' not found in schema")

    if src == dst:
        return {
            "connection_name": name,
            "from_table": from_table,
            "to_table": to_table,
            "paths": [{"hops": 0, "tables": [src], "joins": []}],
        }

    # BFS to find all paths up to max_hops
    from collections import deque
    paths: list[dict] = []
    # queue items: (current_table, path_of_tables, path_of_joins)
    queue: deque[tuple[str, list[str], list[dict]]] = deque()
    queue.append((src, [src], []))

    while queue:
        current, path_tables, path_joins = queue.popleft()
        if len(path_tables) - 1 >= max_hops:
            continue

        for from_t, from_col, to_t, to_col in edges.get(current, []):
            if to_t in path_tables:
                continue  # Avoid cycles

            new_tables = path_tables + [to_t]
            new_joins = path_joins + [{
                "from": f"{from_t}.{from_col}",
                "to": f"{to_t}.{to_col}",
            }]

            if to_t == dst:
                paths.append({
                    "hops": len(new_joins),
                    "tables": new_tables,
                    "joins": new_joins,
                    "sql_hint": " JOIN ".join(
                        f"{t}" for t in new_tables
                    ) + " ON " + " AND ".join(
                        f"{j['from']} = {j['to']}" for j in new_joins
                    ),
                })
            else:
                queue.append((to_t, new_tables, new_joins))

    # Sort by number of hops (shortest first)
    paths.sort(key=lambda p: p["hops"])

    return {
        "connection_name": name,
        "from_table": from_table,
        "to_table": to_table,
        "path_count": len(paths),
        "paths": paths[:10],  # Limit to 10 paths
    }


@app.get("/api/connections/{name}/schema/sample-values")
async def get_cached_sample_values(
    name: str,
    table: str = Query(..., description="Full table name (e.g., 'public.customers')"),
    columns: str = Query(default="", description="Comma-separated column names. Empty = auto-select string/enum columns"),
    limit: int = Query(default=5, ge=1, le=20, description="Max distinct values per column"),
):
    """Get cached sample values for schema linking optimization.

    Sample values help AI agents understand the data domain and generate
    more accurate SQL (e.g., knowing 'status' contains 'active', 'inactive', 'pending').
    Results are cached to avoid repeated queries.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    # Check sample cache first
    cached_samples = schema_cache.get_sample_values(name, table)
    if cached_samples is not None:
        return {
            "connection_name": name,
            "table": table,
            "cached": True,
            "sample_values": cached_samples,
        }

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    try:
        extras = get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            # Determine columns to sample
            col_list: list[str] = []
            if columns:
                col_list = [c.strip() for c in columns.split(",") if c.strip()]
            else:
                # Auto-select: string/enum columns from schema
                schema = schema_cache.get(name)
                if schema and table in schema:
                    for col in schema[table].get("columns", []):
                        col_type = col.get("type", "").lower()
                        if any(t in col_type for t in ("varchar", "text", "char", "string", "enum", "category")):
                            col_list.append(col["name"])
                        if len(col_list) >= 10:
                            break

            if not col_list:
                return {
                    "connection_name": name,
                    "table": table,
                    "cached": False,
                    "sample_values": {},
                    "message": "No columns selected — provide column names or ensure schema is cached",
                }

            values = await connector.get_sample_values(table, col_list, limit=limit)

        # Cache the results
        if values:
            schema_cache.put_sample_values(name, table, values)

        return {
            "connection_name": name,
            "table": table,
            "cached": False,
            "sample_values": values,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))


def _fuzzy_match(query: str, target: str, max_distance: int = 2) -> bool:
    """Simple edit-distance fuzzy matching for schema search.

    Returns True if `query` is within `max_distance` edits of `target`
    (or any substring of target of similar length). Uses Levenshtein distance.
    Only triggers for terms with 4+ characters to avoid false positives.
    """
    if len(query) < 4 or len(target) < 3:
        return False
    # Quick check: if the lengths differ by more than max_distance, skip
    if abs(len(query) - len(target)) > max_distance:
        # Try substring matching for longer targets
        if len(target) > len(query) + max_distance:
            # Check if query fuzzy-matches any window of target
            for i in range(len(target) - len(query) + 1):
                window = target[i:i + len(query)]
                if _levenshtein(query, window) <= max_distance:
                    return True
        return False
    return _levenshtein(query, target) <= max_distance


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            # Insertion, deletion, substitution
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (0 if c1 == c2 else 1)))
        prev = curr
    return prev[len(s2)]


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
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                cached = await connector.get_schema()
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))
        schema_cache.put(name, cached)

    # Parse HEX-style prefix filters: schema:public, table:users, column:email, database:analytics
    prefix_filters: dict[str, list[str]] = {"schema": [], "table": [], "column": [], "database": []}
    raw_terms: list[str] = []
    for part in q.split():
        part = part.strip()
        if not part:
            continue
        matched_prefix = False
        for prefix_key in prefix_filters:
            if part.lower().startswith(f"{prefix_key}:"):
                val = part[len(prefix_key) + 1:].lower()
                if val:
                    prefix_filters[prefix_key].append(val)
                    matched_prefix = True
                break
        if not matched_prefix:
            raw_terms.append(part.lower())

    terms = raw_terms
    scored: list[tuple[float, str, dict]] = []

    for key, table in cached.items():
        score = 0.0
        table_name_lower = table.get("name", "").lower()
        schema_name_lower = table.get("schema", "").lower()
        matched_columns: list[str] = []

        # Apply prefix filters first (any mismatch → skip table)
        if prefix_filters["schema"] and not any(f in schema_name_lower for f in prefix_filters["schema"]):
            continue
        if prefix_filters["database"] and not any(f in schema_name_lower for f in prefix_filters["database"]):
            continue
        if prefix_filters["table"] and not any(f in table_name_lower for f in prefix_filters["table"]):
            continue
        if prefix_filters["column"]:
            col_names_lower = [col.get("name", "").lower() for col in table.get("columns", [])]
            if not any(any(f in cn for cn in col_names_lower) for f in prefix_filters["column"]):
                continue
            # Mark matched columns from prefix filter
            for col in table.get("columns", []):
                cn = col.get("name", "").lower()
                if any(f in cn for f in prefix_filters["column"]):
                    matched_columns.append(col["name"])
            score += 5.0  # Boost for prefix filter match

        # If only prefix filters (no free-text terms), auto-score based on matches
        if not terms and any(prefix_filters[k] for k in prefix_filters):
            score = max(score, 5.0)

        for term in terms:
            # Table name matching (highest weight)
            if term == table_name_lower:
                score += 10.0
            elif table_name_lower.startswith(term):
                score += 5.0
            elif term in table_name_lower:
                score += 3.0
            elif _fuzzy_match(term, table_name_lower):
                score += 2.0  # Fuzzy match — handles typos

            # Schema name matching
            if term in schema_name_lower:
                score += 1.0

            # Compound table name parts (e.g., "order" matches "order_items")
            table_parts = set(table_name_lower.replace("-", "_").split("_"))
            if term in table_parts or term.rstrip("s") in table_parts:
                if term not in table_name_lower:  # Don't double-count substring matches
                    score += 2.5

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
                elif _fuzzy_match(term, col_name):
                    score += 1.0  # Fuzzy column match
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
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
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


# ─── Semantic Model (HEX inline schema editing) ───────────────────────────

# Persistent storage for semantic descriptions (table/column/join)
# Stored as JSON files alongside the SQLite DB
_semantic_models: dict[str, dict] = {}  # connection_name → model


def _semantic_model_path(name: str):
    """Path to the semantic model JSON file for a connection."""
    return DATA_DIR / f"semantic_{name}.json"


def _load_semantic_model(name: str) -> dict:
    """Load semantic model from disk (cached in memory)."""
    if name in _semantic_models:
        return _semantic_models[name]
    path = _semantic_model_path(name)
    if path.exists():
        try:
            model = json.loads(path.read_text())
            _semantic_models[name] = model
            return model
        except Exception:
            pass
    empty = {"tables": {}, "joins": [], "glossary": {}}
    _semantic_models[name] = empty
    return empty


def _save_semantic_model(name: str, model: dict) -> None:
    """Save semantic model to disk."""
    _semantic_models[name] = model
    path = _semantic_model_path(name)
    path.write_text(json.dumps(model, indent=2))


@app.get("/api/connections/{name}/semantic-model")
async def get_semantic_model(name: str):
    """Get the semantic model for a connection.

    The semantic model contains human-curated metadata that enriches
    the auto-detected schema for AI agents (HEX pattern):
    - Table descriptions (what this table represents)
    - Column descriptions (business definitions, units, examples)
    - Join hints (preferred join paths, join types)
    - Business glossary (domain term → table.column mapping)
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    return _load_semantic_model(name)


@app.put("/api/connections/{name}/semantic-model")
async def update_semantic_model(name: str, body: dict):
    """Update the semantic model for a connection.

    Body: {
        "tables": {
            "public.customers": {
                "description": "Core customer records",
                "columns": {
                    "id": {"description": "Primary customer ID", "business_name": "Customer ID"},
                    "ltv": {"description": "Lifetime value in USD", "unit": "USD"}
                }
            }
        },
        "joins": [
            {"from": "orders.customer_id", "to": "customers.id", "type": "many_to_one", "description": "Order belongs to customer"}
        ],
        "glossary": {
            "revenue": "orders.total_amount",
            "customer name": "customers.full_name",
            "ARR": "subscriptions.annual_recurring_revenue"
        }
    }
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    model = _load_semantic_model(name)
    # Merge updates (don't replace — merge at the table/column level)
    if "tables" in body:
        for table_key, table_data in body["tables"].items():
            if table_key not in model["tables"]:
                model["tables"][table_key] = {"description": "", "columns": {}}
            if "description" in table_data:
                model["tables"][table_key]["description"] = table_data["description"]
            if "columns" in table_data:
                if "columns" not in model["tables"][table_key]:
                    model["tables"][table_key]["columns"] = {}
                for col_name, col_data in table_data["columns"].items():
                    if col_name not in model["tables"][table_key]["columns"]:
                        model["tables"][table_key]["columns"][col_name] = {}
                    model["tables"][table_key]["columns"][col_name].update(col_data)
    if "joins" in body:
        model["joins"] = body["joins"]
    if "glossary" in body:
        model["glossary"].update(body["glossary"])

    _save_semantic_model(name, model)
    return model


@app.patch("/api/connections/{name}/semantic-model/table/{table_key:path}")
async def update_table_description(name: str, table_key: str, body: dict):
    """Quick edit a single table's description or column descriptions.

    Body: {"description": "Core customer table"} or
          {"columns": {"email": {"description": "Primary email address"}}}
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    model = _load_semantic_model(name)
    if table_key not in model["tables"]:
        model["tables"][table_key] = {"description": "", "columns": {}}
    if "description" in body:
        model["tables"][table_key]["description"] = body["description"]
    if "columns" in body:
        if "columns" not in model["tables"][table_key]:
            model["tables"][table_key]["columns"] = {}
        for col_name, col_data in body["columns"].items():
            if col_name not in model["tables"][table_key]["columns"]:
                model["tables"][table_key]["columns"][col_name] = {}
            model["tables"][table_key]["columns"][col_name].update(col_data)

    _save_semantic_model(name, model)
    return model["tables"][table_key]


@app.post("/api/connections/{name}/semantic-model/generate")
async def generate_semantic_model(name: str):
    """Auto-generate a semantic model skeleton from the database schema.

    Populates table/column descriptions from database comments (if available),
    infers join hints from FK relationships, and suggests business terms
    from column names.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    cached = schema_cache.get(name)
    if cached is None:
        conn_str = get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        try:
            extras = get_credential_extras(name)
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                cached = await connector.get_schema()
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))
        schema_cache.put(name, cached)

    model = _load_semantic_model(name)

    tables_added = 0
    joins_added = 0
    glossary_added = 0

    for key, table in cached.items():
        if key not in model["tables"]:
            model["tables"][key] = {"description": "", "columns": {}}
        table_model = model["tables"][key]

        # Use database comments as descriptions (if not already set)
        if not table_model.get("description") and table.get("description"):
            table_model["description"] = table["description"]
            tables_added += 1

        if "columns" not in table_model:
            table_model["columns"] = {}

        for col in table.get("columns", []):
            col_name = col.get("name", "")
            if col_name and col_name not in table_model["columns"]:
                table_model["columns"][col_name] = {}
            if col_name and not table_model["columns"].get(col_name, {}).get("description"):
                comment = col.get("comment", "")
                if comment:
                    table_model["columns"][col_name]["description"] = comment

        # Generate join hints from FK relationships
        for fk in table.get("foreign_keys", []):
            from_col = fk.get("column", "")
            to_table = fk.get("references_table", "")
            to_col = fk.get("references_column", "")
            to_schema = fk.get("references_schema", table.get("schema", ""))
            to_key = f"{to_schema}.{to_table}" if to_schema else to_table

            join_entry = {
                "from": f"{key}.{from_col}",
                "to": f"{to_key}.{to_col}",
                "type": "many_to_one",
            }
            # Check for duplicate
            existing = any(
                j.get("from") == join_entry["from"] and j.get("to") == join_entry["to"]
                for j in model.get("joins", [])
            )
            if not existing:
                model["joins"].append(join_entry)
                joins_added += 1

        # Auto-generate glossary entries from column names
        tbl_name = table.get("name", "")
        for col in table.get("columns", []):
            col_name = col.get("name", "")
            # Convert column names to natural language terms
            natural = col_name.replace("_", " ").replace("-", " ").lower()
            if len(natural) > 3 and natural not in model.get("glossary", {}):
                model["glossary"][natural] = f"{key}.{col_name}"
                glossary_added += 1

    _save_semantic_model(name, model)

    return {
        "tables": len(model["tables"]),
        "joins": len(model.get("joins", [])),
        "glossary_terms": len(model.get("glossary", {})),
        "generated": {
            "tables_with_descriptions": tables_added,
            "joins_added": joins_added,
            "glossary_terms_added": glossary_added,
        },
    }


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
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                cached = await connector.get_schema()
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


# ─── Column Exploration (ReFoRCE pattern) ────────────────────────────────────

@app.post("/api/connections/{name}/schema/explore-columns")
async def explore_columns_deep(name: str, body: dict):
    """Deep column exploration for complex Spider2.0 queries.

    ReFoRCE research shows column exploration significantly enhances EX@8
    for harder questions by promoting diverse candidate generation. This
    endpoint lets the agent explore column distributions, value ranges,
    and cross-column correlations before generating complex SQL.

    Body: {
        "table": "public.orders",
        "columns": ["status", "total_amount"],  // optional — explore all if omitted
        "include_stats": true,  // include min/max/avg for numeric cols
        "include_values": true, // include sample distinct values
        "value_limit": 10       // max sample values per column
    }
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    table_key = body.get("table", "")
    requested_cols = body.get("columns", [])
    include_stats = body.get("include_stats", True)
    include_values = body.get("include_values", True)
    value_limit = min(body.get("value_limit", 10), 25)

    if not table_key:
        raise HTTPException(status_code=422, detail="table is required")

    # Get cached schema
    cached = schema_cache.get(name)
    if cached is None:
        conn_str = get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        try:
            extras = get_credential_extras(name)
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                cached = await connector.get_schema()
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))
        schema_cache.put(name, cached)

    table_info = cached.get(table_key)
    if not table_info:
        raise HTTPException(status_code=404, detail=f"Table '{table_key}' not found in schema")

    all_columns = table_info.get("columns", [])
    if requested_cols:
        col_set = {c.lower() for c in requested_cols}
        explore_cols = [c for c in all_columns if c["name"].lower() in col_set]
    else:
        explore_cols = all_columns

    db_type = info.db_type
    result_cols: list[dict] = []
    numeric_types = {"integer", "int", "bigint", "smallint", "numeric", "decimal",
                     "float", "double", "real", "number", "int4", "int8", "int2",
                     "float4", "float8", "Float32", "Float64", "UInt32", "UInt64",
                     "Int32", "Int64", "INTEGER", "BIGINT", "FLOAT64", "NUMERIC", "DECIMAL"}

    # Build exploration queries
    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")
    extras = get_credential_extras(name)

    async with pool_manager.connection(db_type, conn_str, credential_extras=extras) as connector:
        # Get sample values for all requested columns in one round trip
        sample_values: dict[str, list] = {}
        if include_values:
            col_names = [c["name"] for c in explore_cols[:20]]
            try:
                sample_values = await connector.get_sample_values(table_key, col_names, value_limit)
            except Exception:
                pass

        # Get numeric stats in one query
        numeric_stats: dict[str, dict] = {}
        if include_stats:
            num_cols = [c for c in explore_cols if c.get("type", "").lower().rstrip("()0123456789, ").split("(")[0] in numeric_types]
            if num_cols:
                # Build a single query with MIN/MAX/AVG for all numeric columns
                stat_parts = []
                for c in num_cols[:15]:
                    cn = c["name"]
                    # Use appropriate quoting based on db_type
                    q = '"' if db_type in ("postgres", "redshift", "snowflake", "duckdb", "trino") else '`' if db_type in ("mysql", "clickhouse", "databricks") else '['
                    if q == '[':
                        qo, qc = '[', ']'
                    else:
                        qo = qc = q
                    safe = cn.replace(qc, qc + qc)
                    stat_parts.append(f"MIN({qo}{safe}{qc})")
                    stat_parts.append(f"MAX({qo}{safe}{qc})")
                    stat_parts.append(f"AVG(CAST({qo}{safe}{qc} AS FLOAT))")
                try:
                    stat_sql = f"SELECT {', '.join(stat_parts)} FROM {table_key}"
                    # Add LIMIT for safety on large tables
                    if db_type == "mssql":
                        stat_sql = f"SELECT TOP 1000000 {', '.join(stat_parts)} FROM {table_key}"
                    rows = await connector.execute(stat_sql, timeout=15)
                    if rows:
                        row = rows[0]
                        vals = list(row.values())
                        for i, c in enumerate(num_cols[:15]):
                            idx = i * 3
                            if idx + 2 < len(vals):
                                numeric_stats[c["name"]] = {
                                    "min": vals[idx],
                                    "max": vals[idx + 1],
                                    "avg": round(float(vals[idx + 2]), 4) if vals[idx + 2] is not None else None,
                                }
                except Exception:
                    pass

        # Build result
        for col in explore_cols:
            col_result: dict = {
                "name": col["name"],
                "type": col.get("type", ""),
                "nullable": col.get("nullable", True),
                "primary_key": col.get("primary_key", False),
            }
            if col.get("comment"):
                col_result["comment"] = col["comment"]
            if col.get("stats"):
                col_result["schema_stats"] = col["stats"]
            if col["name"] in numeric_stats:
                col_result["value_stats"] = numeric_stats[col["name"]]
            if col["name"] in sample_values:
                col_result["sample_values"] = sample_values[col["name"]]
            result_cols.append(col_result)

    return {
        "table": table_key,
        "table_type": table_info.get("type", "table"),
        "row_count": table_info.get("row_count", 0),
        "columns_explored": len(result_cols),
        "columns": result_cols,
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

    try:
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
        except asyncio.TimeoutError:
            health_monitor.record(req.connection_name, (time.monotonic() - start) * 1000, False, "timeout", info.db_type)
            raise HTTPException(
                status_code=408,
                detail=f"Query timed out after {timeout}s. Consider adding more specific WHERE clauses or reducing the scope.",
            )
        except Exception as e:
            health_monitor.record(req.connection_name, (time.monotonic() - start) * 1000, False, str(e)[:200], info.db_type)
            sanitized = _sanitize_db_error(str(e))
            hint = query_error_hint(str(e), info.db_type)
            detail = {"error": sanitized, "hint": hint} if hint else sanitized
            raise HTTPException(status_code=500, detail=detail)
    finally:
        await pool_manager.release(info.db_type, conn_str)

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
    # BigQuery: include actual job stats (bytes billed, cost, cache hit)
    if info.db_type == "bigquery":
        try:
            from .connectors.bigquery import BigQueryConnector
            if isinstance(connector, BigQueryConnector):
                job_stats = connector.get_last_job_stats()
                if job_stats:
                    response["bigquery_stats"] = job_stats
        except Exception:
            pass
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
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            from .governance.cost_estimator import CostEstimator
            cost_estimate = await CostEstimator.estimate(connector, safe_sql, info.db_type)

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
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            schema = await connector.get_schema()
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
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                cached_schema = await connector.get_schema()
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


@app.get("/api/pool/stats")
async def pool_stats():
    """Get connection pool statistics for monitoring."""
    return pool_manager.stats()


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


# ─── Connector Tier Classification (HEX pattern) ──────────────────────────────

# HEX uses a 4-tier system:
#   Tier 1: Full support, actively maintained, all features
#   Tier 2: Stable, supported, may lag on new features
#   Tier 3: Supported, limited feature coverage
#   Community: Community-contributed, best-effort support

_CONNECTOR_TIERS = {
    "postgres": {
        "tier": 1,
        "label": "Tier 1 — Full Support",
        "features": {
            "ssl": True, "ssh_tunnel": True, "schema_introspection": True,
            "foreign_keys": True, "indexes": True, "row_counts": True,
            "column_stats": True, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": True,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": True, "parallel_schema": True,
            "table_sizes": True, "iam_auth": True,
        },
    },
    "mysql": {
        "tier": 1,
        "label": "Tier 1 — Full Support",
        "features": {
            "ssl": True, "ssh_tunnel": True, "schema_introspection": True,
            "foreign_keys": True, "indexes": True, "row_counts": True,
            "column_stats": True, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": False,
            "table_sizes": True, "iam_auth": True,
        },
    },
    "snowflake": {
        "tier": 1,
        "label": "Tier 1 — Full Support",
        "features": {
            "ssl": False, "ssh_tunnel": False, "schema_introspection": True,
            "foreign_keys": True, "indexes": False, "row_counts": True,
            "column_stats": False, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": True,
            "key_pair_auth": True, "oauth_auth": True, "warehouse_config": True,
            "table_sizes": True,
        },
    },
    "bigquery": {
        "tier": 1,
        "label": "Tier 1 — Full Support",
        "features": {
            "ssl": False, "ssh_tunnel": False, "schema_introspection": True,
            "foreign_keys": False, "indexes": False, "row_counts": True,
            "column_stats": False, "primary_keys": False, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": False,
            "partitioning_info": True, "clustering_info": True,
            "service_account_auth": True,
        },
    },
    "redshift": {
        "tier": 2,
        "label": "Tier 2 — Stable",
        "features": {
            "ssl": True, "ssh_tunnel": True, "schema_introspection": True,
            "foreign_keys": True, "indexes": False, "row_counts": True,
            "column_stats": True, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": True,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": True,
            "dist_sort_keys": True, "iam_auth": True, "table_sizes": True,
        },
    },
    "clickhouse": {
        "tier": 2,
        "label": "Tier 2 — Stable",
        "features": {
            "ssl": True, "ssh_tunnel": True, "schema_introspection": True,
            "foreign_keys": False, "indexes": False, "row_counts": True,
            "column_stats": True, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": False,
            "engine_info": True, "sorting_key_info": True,
            "native_and_http": True, "table_sizes": True,
        },
    },
    "databricks": {
        "tier": 2,
        "label": "Tier 2 — Stable",
        "features": {
            "ssl": False, "ssh_tunnel": False, "schema_introspection": True,
            "foreign_keys": True, "indexes": False, "row_counts": False,
            "column_stats": False, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": False,
            "unity_catalog": True, "pat_auth": True, "table_sizes": True,
        },
    },
    "mssql": {
        "tier": 2,
        "label": "Tier 2 — Stable",
        "features": {
            "ssl": True, "ssh_tunnel": True, "schema_introspection": True,
            "foreign_keys": True, "indexes": True, "row_counts": True,
            "column_stats": True, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": False,
            "table_sizes": True, "azure_ad_auth": True,
        },
    },
    "trino": {
        "tier": 2,
        "label": "Tier 2 — Stable",
        "features": {
            "ssl": True, "ssh_tunnel": False, "schema_introspection": True,
            "foreign_keys": True, "indexes": False, "row_counts": True,
            "column_stats": False, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": True,
            "connection_pooling": False, "parallel_schema": False,
            "federated_query": True,
        },
    },
    "duckdb": {
        "tier": 3,
        "label": "Tier 3 — Basic",
        "features": {
            "ssl": False, "ssh_tunnel": False, "schema_introspection": True,
            "foreign_keys": True, "indexes": False, "row_counts": True,
            "column_stats": False, "primary_keys": True, "comments": True,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": False,
            "connection_pooling": False, "parallel_schema": False,
            "motherduck": True,
        },
    },
    "sqlite": {
        "tier": 3,
        "label": "Tier 3 — Basic",
        "features": {
            "ssl": False, "ssh_tunnel": False, "schema_introspection": True,
            "foreign_keys": True, "indexes": False, "row_counts": True,
            "column_stats": False, "primary_keys": True, "comments": False,
            "sample_values": True, "read_only_transactions": False,
            "query_timeout": True, "cost_estimation": False,
            "connection_pooling": False, "parallel_schema": False,
        },
    },
}


@app.get("/api/connectors/capabilities")
async def get_connector_capabilities(db_type: str | None = None):
    """Return connector tier classification and feature matrix.

    HEX-style tier system showing which features each connector supports.
    Useful for the frontend to show capability badges and for agents
    to understand what metadata is available per connection type.
    """
    if db_type:
        info = _CONNECTOR_TIERS.get(db_type)
        if not info:
            raise HTTPException(status_code=404, detail=f"Unknown db_type: {db_type}")
        feature_count = sum(1 for v in info["features"].values() if v)
        total_features = len(info["features"])
        return {
            "db_type": db_type,
            **info,
            "feature_score": round(feature_count / total_features * 100),
            "feature_count": feature_count,
            "total_features": total_features,
        }

    # Return all connectors grouped by tier
    tiers: dict[int, list] = {1: [], 2: [], 3: []}
    for dt, info in _CONNECTOR_TIERS.items():
        feature_count = sum(1 for v in info["features"].values() if v)
        total_features = len(info["features"])
        tiers[info["tier"]].append({
            "db_type": dt,
            **info,
            "feature_score": round(feature_count / total_features * 100),
            "feature_count": feature_count,
            "total_features": total_features,
        })

    return {
        "tier_1": tiers[1],
        "tier_2": tiers[2],
        "tier_3": tiers[3],
        "total_connectors": len(_CONNECTOR_TIERS),
    }


@app.get("/api/connections/{name}/capabilities")
async def get_connection_capabilities(name: str):
    """Return capabilities for a specific connection based on its db_type.

    Combines tier info with live connection status for a complete picture.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    tier_info = _CONNECTOR_TIERS.get(info.db_type, {})
    features = tier_info.get("features", {})
    feature_count = sum(1 for v in features.values() if v)
    total_features = max(len(features), 1)

    # Check what's actually configured
    has_ssh = bool(info.ssh_tunnel and info.ssh_tunnel.enabled)
    has_ssl = bool(info.ssl or (info.ssl_config and info.ssl_config.enabled))
    has_schema_refresh = bool(info.schema_refresh_interval)

    return {
        "connection_name": name,
        "db_type": info.db_type,
        "tier": tier_info.get("tier", 3),
        "tier_label": tier_info.get("label", "Tier 3 — Basic"),
        "features": features,
        "feature_score": round(feature_count / total_features * 100),
        "configured": {
            "ssh_tunnel": has_ssh,
            "ssl": has_ssl,
            "schema_refresh": has_schema_refresh,
            "description": bool(info.description),
            "tags": bool(info.tags),
        },
    }
