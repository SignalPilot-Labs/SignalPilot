"""Connection CRUD and management endpoints."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Any
from urllib.parse import quote_plus, urlparse, unquote, parse_qs

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..auth import UserID
from ..connectors.health_monitor import health_monitor
from ..connectors.pool_manager import pool_manager
from ..connectors.schema_cache import schema_cache
from ..models import ConnectionCreate, ConnectionUpdate
from ..network_validation import validate_connection_params
from ..scope_guard import RequireScope, require_scopes
from ..store import (
    CredentialEncryptionError,
    _build_connection_string,
    _extract_credential_extras,
)
from .deps import StoreD, sanitize_db_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Helper: validate connection params
# ---------------------------------------------------------------------------

def _validate_connection_params(conn: ConnectionCreate) -> list[str]:
    """Validate connection parameters before persisting. Returns list of error messages."""
    from ..deployment import is_cloud_mode
    errors: list[str] = []

    # Cloud mode: reject file-based local database connections
    if is_cloud_mode() and conn.db_type in ("duckdb", "sqlite"):
        db_path = conn.connection_string or conn.database or ""
        if db_path and db_path != ":memory:" and not db_path.startswith("md:"):
            errors.append(f"File-based {conn.db_type} connections are not available in cloud mode")
            return errors

    if conn.connection_string:
        if conn.db_type in ("duckdb", "sqlite"):
            pass  # Local file paths are sandboxed — no DATA_DIR restriction needed
        else:
            try:
                validate_connection_params(conn.host, conn.port, conn.db_type, conn.connection_string)
            except ValueError as e:
                errors.append(str(e))
        return errors

    try:
        validate_connection_params(conn.host, conn.port, conn.db_type, None)
    except ValueError as e:
        errors.append(str(e))

    db = conn.db_type

    if db in ("postgres", "mysql", "redshift", "clickhouse", "mssql"):
        if not conn.host:
            errors.append(f"{db} requires a host")
        if not conn.username:
            errors.append(f"{db} requires a username")

    if db == "trino":
        if not conn.host:
            errors.append("Trino requires a host")
        if not conn.catalog:
            errors.append("Trino requires a catalog")

    if db == "snowflake":
        if not conn.account:
            errors.append("Snowflake requires an account identifier")
        if not conn.username:
            errors.append("Snowflake requires a username")

    if db == "bigquery":
        if not conn.project:
            errors.append("BigQuery requires a GCP project ID")
        if not conn.credentials_json:
            errors.append("BigQuery requires service account credentials JSON")

    if db == "databricks":
        if not conn.host:
            errors.append("Databricks requires a server hostname")
        if not conn.http_path:
            errors.append("Databricks requires an HTTP path (SQL warehouse endpoint)")
        if not conn.access_token:
            errors.append("Databricks requires a personal access token")

    if db in ("duckdb", "sqlite"):
        if not conn.database:
            errors.append(f"{db} requires a database file path (or :memory:)")

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


# ---------------------------------------------------------------------------
# Helper: auto schema refresh
# ---------------------------------------------------------------------------

async def _auto_schema_refresh(name: str, db_type: str, store):
    """Background task: fetch schema for newly created connections."""
    await asyncio.sleep(2)
    try:
        conn_str = await store.get_connection_string(name)
        if not conn_str:
            return
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(db_type, conn_str, credential_extras=extras) as connector:
            schema = await connector.get_schema()
            schema_cache.put(name, schema)
            logger.info("Auto-refreshed schema for new connection '%s': %d tables", name, len(schema))

            _cat_names = {"status", "state", "type", "category", "region", "country",
                          "city", "role", "department", "channel", "source", "currency"}
            _str_types = {"varchar", "nvarchar", "text", "char", "character varying", "string"}
            for table_key, table_data in list(schema.items())[:20]:
                sample_cols = []
                for col in table_data.get("columns", []):
                    cn = col.get("name", "").lower()
                    ct = col.get("type", "").lower().split("(")[0]
                    stats = col.get("stats", {})
                    dc = stats.get("distinct_count", 0) if stats else 0
                    if (dc and dc <= 50) or (ct in _str_types and (cn in _cat_names or cn.endswith("_type") or cn.endswith("_status"))):
                        sample_cols.append(col["name"])
                if sample_cols:
                    try:
                        values = await connector.get_sample_values(table_key, sample_cols[:10], limit=5)
                        if values:
                            schema_cache.put_sample_values(name, table_key, values)
                    except Exception:
                        pass
    except Exception as e:
        logger.warning("Auto-schema-refresh failed for '%s': %s", name, e)


# ---------------------------------------------------------------------------
# Helper: connection error hints
# ---------------------------------------------------------------------------

def _connection_error_hint(db_type: str, error_msg: str) -> str:
    """Generate actionable error hints based on DB type and error message."""
    err_lower = error_msg.lower()

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

    if any(kw in err_lower for kw in ("warehouse", "http_path", "compute")):
        hints = {
            "snowflake": "Check: 1) Warehouse name is correct and exists 2) Warehouse is not suspended 3) Role has USAGE on the warehouse",
            "databricks": "Check: 1) http_path is correct (SQL Warehouse -> Connection Details) 2) SQL Warehouse is running (not stopped)",
        }
        return hints.get(db_type, "Check warehouse/compute resource configuration")

    if any(kw in err_lower for kw in ("ssl", "tls", "certificate", "handshake")):
        return "Check: 1) SSL certificate is valid and not expired 2) CA certificate matches the server's cert chain 3) SSL mode matches server requirements"

    return "Check connection parameters, credentials, and network access"


# ---------------------------------------------------------------------------
# Connector tier classification
# ---------------------------------------------------------------------------

_CONNECTOR_TIERS = {
    "postgres": {
        "tier": 1, "label": "Tier 1 — Full Support",
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
        "tier": 1, "label": "Tier 1 — Full Support",
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
        "tier": 1, "label": "Tier 1 — Full Support",
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
        "tier": 1, "label": "Tier 1 — Full Support",
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
        "tier": 2, "label": "Tier 2 — Stable",
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
        "tier": 2, "label": "Tier 2 — Stable",
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
        "tier": 2, "label": "Tier 2 — Stable",
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
        "tier": 2, "label": "Tier 2 — Stable",
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
        "tier": 2, "label": "Tier 2 — Stable",
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
        "tier": 3, "label": "Tier 3 — Basic",
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
        "tier": 3, "label": "Tier 3 — Basic",
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/connections", dependencies=[RequireScope("read")])
async def get_connections(store: StoreD):
    return await store.list_connections()


@router.post("/connections", status_code=201, dependencies=[RequireScope("write")])
async def add_connection(conn: ConnectionCreate, store: StoreD):
    errors = _validate_connection_params(conn)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})
    try:
        info = await store.create_connection(conn)
    except ValueError:
        raise HTTPException(status_code=409, detail="Connection already exists or invalid parameters")

    asyncio.create_task(_auto_schema_refresh(info.name, info.db_type, store))
    return info


@router.get("/connections/health", dependencies=[RequireScope("read")])
async def get_all_connection_health(_: UserID, window: int = Query(default=300, ge=60, le=3600)):
    """Get health stats for all monitored connections."""
    return {"connections": health_monitor.all_stats(window)}


@router.get("/connections/stats", dependencies=[RequireScope("read")])
async def get_connections_stats(store: StoreD):
    """Dashboard-level statistics for all connections."""
    connections = await store.list_connections()
    stats: list[dict] = []
    for conn in connections:
        conn_dict = conn.model_dump() if hasattr(conn, "model_dump") else dict(conn)
        name = conn_dict.get("name", "")
        db_type = conn_dict.get("db_type", "")
        entry: dict[str, Any] = {
            "name": name,
            "db_type": db_type,
            "description": conn_dict.get("description", ""),
            "tags": conn_dict.get("tags", []),
        }
        cached = schema_cache.get(name)
        if cached:
            entry["schema_tables"] = len(cached)
            entry["schema_columns"] = sum(len(t.get("columns", [])) for t in cached.values())
            entry["total_rows"] = sum(t.get("row_count", 0) or 0 for t in cached.values())
            total_mb = sum(t.get("size_mb", 0) or 0 for t in cached.values())
            if total_mb:
                entry["total_size_mb"] = round(total_mb, 2)
            entry["schema_cached"] = True
            fp = schema_cache.get_fingerprint(name)
            if fp:
                entry["schema_fingerprint"] = fp
        else:
            entry["schema_cached"] = False

        health = health_monitor.connection_stats(name, 300)
        if health:
            entry["health_status"] = health.get("status", "unknown")
            entry["latency_p50_ms"] = health.get("latency_p50_ms")
            entry["error_rate"] = health.get("error_rate", 0)
        else:
            entry["health_status"] = "unknown"

        pool_stats_data = pool_manager.stats()
        for p in pool_stats_data.get("pools", []):
            if name in p.get("key", ""):
                entry["pool_idle_seconds"] = p.get("idle_seconds", 0)
                break

        stats.append(entry)
    return {"connections": stats, "total": len(stats)}


class ExportRequest(BaseModel):
    include_credentials: bool
    confirm: bool


@router.post("/connections/export", dependencies=[RequireScope("write")])
async def export_connections(
    body: ExportRequest,
    store: StoreD,
    request: Request,
):
    """Export all connections as a portable JSON manifest.

    Requires explicit confirmation via POST body.
    Credential export is audit-logged.
    Exporting credentials requires admin scope in addition to write scope.
    """
    if body.include_credentials:
        require_scopes(request, "admin")

    if not body.confirm:
        return JSONResponse(
            status_code=400,
            content={"error": "Export requires confirm=true in the request body."},
        )

    logger.warning(
        "Credential export requested by user %s, include_credentials=%s",
        store.user_id,
        body.include_credentials,
    )

    all_conns = await store.list_connections()
    exported = []
    for conn in all_conns:
        conn_dict = conn.model_dump() if hasattr(conn, "model_dump") else dict(conn)
        entry: dict = {
            "name": conn_dict.get("name", ""),
            "db_type": conn_dict.get("db_type", ""),
            "description": conn_dict.get("description", ""),
            "tags": conn_dict.get("tags", []),
        }
        for field in ("host", "port", "database", "username", "account", "warehouse",
                       "schema_name", "role", "project", "dataset", "http_path", "catalog",
                       "location", "maximum_bytes_billed",
                       "schema_filter_include", "schema_filter_exclude",
                       "schema_refresh_interval", "connection_timeout", "query_timeout",
                       "keepalive_interval"):
            val = conn_dict.get(field)
            if val is not None:
                entry[field] = val

        if body.include_credentials:
            try:
                conn_str = await store.get_connection_string(entry["name"])
                if conn_str:
                    entry["connection_string"] = conn_str
            except CredentialEncryptionError:
                return JSONResponse(
                    status_code=422,
                    content={"error": "Failed to decrypt connection credentials."},
                )
            if conn_dict.get("ssl_config"):
                entry["ssl_config"] = conn_dict["ssl_config"]
            if conn_dict.get("ssh_tunnel"):
                entry["ssh_tunnel"] = conn_dict["ssh_tunnel"]

        exported.append(entry)

    return {
        "version": "1.0",
        "exported_at": time.time(),
        "connection_count": len(exported),
        "includes_credentials": body.include_credentials,
        "connections": exported,
    }


@router.post("/connections/import", dependencies=[RequireScope("write")])
async def import_connections(manifest: dict, store: StoreD):
    """Import connections from an exported JSON manifest."""
    connections = manifest.get("connections", [])
    if len(connections) > 500:
        raise HTTPException(status_code=422, detail="Maximum 500 connections per import")
    results = {"imported": 0, "skipped": [], "errors": []}

    for entry in connections:
        name = entry.get("name", "")
        if not name:
            results["errors"].append({"name": "(empty)", "error": "Missing connection name"})
            continue

        if await store.get_connection(name):
            results["skipped"].append(name)
            continue

        try:
            conn = ConnectionCreate(**entry)
            errors = _validate_connection_params(conn)
            if errors:
                results["errors"].append({"name": name, "error": errors[0]})
                continue
            await store.create_connection(conn)
            results["imported"] += 1
        except Exception as e:
            results["errors"].append({"name": name, "error": "Failed to import connection"})

    return results


@router.get("/connections/{name}", dependencies=[RequireScope("read")])
async def get_connection_detail(name: str, store: StoreD):
    conn = await store.get_connection(name)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    return conn


@router.delete("/connections/{name}", status_code=204, dependencies=[RequireScope("write")])
async def remove_connection(name: str, store: StoreD):
    if not await store.delete_connection(name):
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    schema_cache.invalidate(name)


@router.put("/connections/{name}", dependencies=[RequireScope("write")])
async def edit_connection(name: str, update: ConnectionUpdate, store: StoreD):
    """Update an existing connection. Only provided fields are changed."""
    existing = await store.get_connection(name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    update_data = update.model_dump(exclude_none=True)
    if update_data:
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

    old_conn_str = await store.get_connection_string(name)

    try:
        result = await store.update_connection(name, update)
    except CredentialEncryptionError:
        return JSONResponse(
            status_code=422,
            content={"error": "Failed to update connection credentials."},
        )
    if not result:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    schema_cache.invalidate(name)
    if old_conn_str:
        await pool_manager.close_pool(old_conn_str)

    return result


@router.post("/connections/{name}/clone", dependencies=[RequireScope("write")])
async def clone_connection(name: str, store: StoreD, new_name: str = Query(..., min_length=1, max_length=64)):
    """Clone an existing connection with a new name."""
    existing = await store.get_connection(name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    if await store.get_connection(new_name):
        raise HTTPException(status_code=409, detail=f"Connection '{new_name}' already exists")

    clone_desc = f"Clone of {name}" if not existing.description else f"{existing.description} (clone)"
    create_data: dict = {
        "name": new_name,
        "db_type": existing.db_type,
        "description": clone_desc,
    }
    for field in ("host", "port", "database", "username", "account", "warehouse",
                   "schema_name", "role", "project", "dataset", "http_path", "catalog"):
        val = getattr(existing, field, None)
        if val is not None:
            create_data[field] = val

    conn_str = await store.get_connection_string(name)
    if conn_str:
        create_data["connection_string"] = conn_str

    conn = ConnectionCreate(**create_data)
    try:
        result = await store.create_connection(conn)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return result


@router.post("/connections/{name}/schema/refresh", dependencies=[RequireScope("write")])
async def refresh_connection_schema(name: str, store: StoreD):
    """Force-refresh the cached schema for a connection."""
    info = await store.get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    schema_cache.invalidate(name)

    try:
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            schema = await connector.get_schema()
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e)))

    schema_cache.put(name, schema)
    now = time.time()
    await store.update_connection(name, ConnectionUpdate(last_schema_refresh=now))

    return {
        "connection_name": name,
        "table_count": len(schema),
        "refreshed_at": now,
        "next_refresh_in": info.schema_refresh_interval,
        "message": "Schema refreshed successfully",
    }


@router.post("/connections/schema/warmup", dependencies=[RequireScope("write")])
async def warmup_all_schemas(store: StoreD):
    """Parallel schema warmup for all connections."""
    from ..models import ConnectionInfo  # noqa: F811 — local import for type hint in inner func

    connections = await store.list_connections()
    if not connections:
        return {"warmed": 0, "results": [], "duration_ms": 0}

    start = time.monotonic()

    async def _warmup_one(info) -> dict:
        name = info.name
        cached = schema_cache.get(name)
        if cached is not None:
            return {"name": name, "status": "cached", "table_count": len(cached)}
        conn_str = await store.get_connection_string(name)
        if not conn_str:
            return {"name": name, "status": "skipped", "error": "no credentials"}
        try:
            extras = await store.get_credential_extras(name)
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                schema = await connector.get_schema()
                schema_cache.put(name, schema)

                _categorical_patterns = {
                    "status", "state", "type", "category", "region", "country",
                    "city", "gender", "role", "department", "dept", "tier",
                    "priority", "severity", "channel", "source", "currency",
                    "payment_method", "payment_type", "order_status", "plan",
                    "segment", "class", "grade", "level", "phase",
                }
                _string_types = {"varchar", "nvarchar", "text", "char", "nchar",
                                 "character varying", "enum", "string", "String"}
                sample_count = 0
                for table_key, table_data in list(schema.items())[:30]:
                    if schema_cache.get_sample_values(name, table_key) is not None:
                        continue
                    low_card_cols = []
                    for col in table_data.get("columns", []):
                        col_name = col.get("name", "")
                        col_type = col.get("type", "").lower().split("(")[0]
                        stats = col.get("stats", {})
                        dc = stats.get("distinct_count", 0) if stats else 0
                        df = abs(stats.get("distinct_fraction", 0)) if stats else 0
                        if dc and dc <= 50:
                            low_card_cols.append(col_name)
                        elif df and df < 0.05:
                            low_card_cols.append(col_name)
                        elif not stats and col_type in _string_types:
                            col_lower = col_name.lower()
                            if col_lower in _categorical_patterns or col_lower.endswith("_type") or col_lower.endswith("_status"):
                                low_card_cols.append(col_name)
                    if low_card_cols:
                        try:
                            samples = await connector.get_sample_values(
                                table_key, low_card_cols[:10], limit=5
                            )
                            if samples:
                                schema_cache.put_sample_values(name, table_key, samples)
                                sample_count += len(samples)
                        except Exception:
                            pass

            now = time.time()
            await store.update_connection(name, ConnectionUpdate(last_schema_refresh=now))
            return {"name": name, "status": "ok", "table_count": len(schema),
                    "sample_columns": sample_count}
        except Exception as e:
            return {"name": name, "status": "error", "error": sanitize_db_error(str(e))[:200]}

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


@router.post("/connections/parse-url", dependencies=[RequireScope("read")])
async def parse_url_endpoint(_: UserID, request: Request):
    """Parse a database connection URL into individual credential fields."""
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    if len(url) > 4096:
        raise HTTPException(status_code=422, detail="URL must be at most 4096 characters")

    from ..url_parser import parse_connection_url
    result = parse_connection_url(url, db_type=body.get("db_type", ""))
    if not result:
        raise HTTPException(status_code=400, detail="Could not parse URL")
    return result


@router.post("/connections/test-credentials", dependencies=[RequireScope("write")])
async def test_credentials(_: UserID, request: Request):
    """Test connection credentials without saving."""
    body = await request.json()
    t0 = time.monotonic()
    phases: list[dict] = []

    # Name is required by ConnectionCreate but irrelevant for testing —
    # inject a placeholder so users can test before choosing a name.
    if not body.get("name"):
        body["name"] = "_test"

    try:
        conn = ConnectionCreate(**body)
    except Exception as e:
        logger.warning("ConnectionCreate validation failed: %s | keys=%s", e, list(body.keys()))
        return {"status": "error", "message": "Invalid connection parameters", "phases": []}

    try:
        conn_str = conn.connection_string or _build_connection_string(conn)
    except Exception:
        return {"status": "error", "message": "Could not build connection string", "phases": []}

    # SSRF validation: check host before opening any TCP connection.
    # test_credentials accepts raw user-supplied host/port and never goes through
    # _validate_connection_params, making it the primary SSRF vector.
    try:
        validate_connection_params(conn.host, conn.port, conn.db_type, conn.connection_string)
    except ValueError as e:
        return {
            "status": "error",
            "message": str(e),
            "phases": [{"phase": "ssrf_check", "status": "error", "message": str(e)}],
        }

    extras = _extract_credential_extras(conn)
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
    if body.get("auth_method") == "iam":
        extras["auth_method"] = "iam"
    if body.get("auth_method") == "azure_ad":
        extras["auth_method"] = "azure_ad"
        extras["azure_ad_auth"] = True

    db_type = conn.db_type

    # Phase 1: Network connectivity (skip for embedded/local DBs)
    t1 = time.monotonic()
    is_embedded = db_type in ("duckdb", "sqlite", "bigquery")
    if is_embedded:
        phases.append({
            "phase": "network", "status": "skipped",
            "message": f"{db_type} does not require network connectivity check",
            "duration_ms": 0,
        })
    else:
        try:
            parsed = urlparse(conn_str if "://" in conn_str else f"dummy://{conn_str}")
            host = parsed.hostname or conn.host or "localhost"
            port = parsed.port or conn.port or 5432

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            try:
                sock.connect((host, int(port)))
                sock.close()
                phases.append({
                    "phase": "network", "status": "ok",
                    "message": f"TCP connection to {host}:{port} succeeded",
                    "duration_ms": round((time.monotonic() - t1) * 1000, 1),
                })
            except (socket.timeout, socket.error, OSError) as e:
                phases.append({
                    "phase": "network", "status": "error",
                    "message": f"Cannot reach {host}:{port} — {str(e)[:100]}",
                    "hint": _connection_error_hint(db_type, str(e)),
                    "duration_ms": round((time.monotonic() - t1) * 1000, 1),
                })
                return {
                    "status": "error", "message": f"Network unreachable: {host}:{port}",
                    "phases": phases, "total_duration_ms": round((time.monotonic() - t0) * 1000, 1),
                }
        except Exception:
            phases.append({
                "phase": "network", "status": "warning",
                "message": "Could not verify network connectivity",
                "duration_ms": round((time.monotonic() - t1) * 1000, 1),
            })

    # Phase 2: Database connection / file access
    t2 = time.monotonic()
    phase2_label = "file_access" if is_embedded else "authentication"
    try:
        async with pool_manager.connection(db_type, conn_str, credential_extras=extras) as connector:
            ok = await connector.health_check()
            if ok:
                msg = "File found and readable" if is_embedded else "Authenticated and connected successfully"
                phases.append({
                    "phase": phase2_label, "status": "ok",
                    "message": msg,
                    "duration_ms": round((time.monotonic() - t2) * 1000, 1),
                })

                # Phase 3: Schema access
                t3 = time.monotonic()
                try:
                    schema = await connector.get_schema()
                    table_count = len(schema) if schema else 0
                    phases.append({
                        "phase": "schema_access", "status": "ok",
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
                        "phase": "schema_access", "status": "warning",
                        "message": f"Connected but schema access limited: {sanitize_db_error(str(e))}",
                        "hint": schema_hints.get(db_type, "Check SELECT permissions on information_schema or system tables"),
                        "duration_ms": round((time.monotonic() - t3) * 1000, 1),
                    })
            else:
                fail_msg = "File not found or not readable" if is_embedded else "Connection established but health check failed"
                phases.append({
                    "phase": phase2_label, "status": "error",
                    "message": fail_msg,
                    "duration_ms": round((time.monotonic() - t2) * 1000, 1),
                })
    except Exception as e:
        err_msg = sanitize_db_error(str(e))
        fail_prefix = "File access failed" if is_embedded else "Authentication failed"
        phases.append({
            "phase": phase2_label, "status": "error",
            "message": f"{fail_prefix}: {err_msg}",
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


@router.post("/connections/validate-url", dependencies=[RequireScope("read")])
async def validate_connection_url(_: UserID, body: dict):
    """Validate and parse a connection string without saving or connecting."""
    url = body.get("connection_string", "")
    db_type = body.get("db_type", "")

    if not url:
        return {"valid": False, "error": "Connection string is empty"}
    if len(url) > 4096:
        raise HTTPException(status_code=422, detail="connection_string must be at most 4096 characters")
    if not db_type:
        return {"valid": False, "error": "db_type is required"}

    try:
        parsed_info: dict[str, Any] = {"db_type": db_type}
        warnings: list[str] = []

        if db_type in ("postgres", "mysql", "redshift", "clickhouse", "mssql"):
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

        return {"valid": True, "parsed": parsed_info, "warnings": warnings}
    except Exception:
        return {"valid": False, "error": "Invalid URL format"}


_BUILD_URL_FIELD_LIMITS: dict[str, int] = {
    "host": 255,
    "database": 128,
    "username": 128,
    "password": 1024,
}


@router.post("/connections/build-url", dependencies=[RequireScope("read")])
async def build_connection_url(_: UserID, body: dict):
    """Build a connection string from individual fields."""
    db_type = body.get("db_type", "")
    host = body.get("host", "")
    port = body.get("port")
    database = body.get("database", "")
    username = body.get("username", "")
    password = body.get("password", "")

    if not db_type:
        return {"url": "", "error": "db_type is required"}

    for field_name, max_len in _BUILD_URL_FIELD_LIMITS.items():
        value = body.get(field_name, "")
        if isinstance(value, str) and len(value) > max_len:
            raise HTTPException(
                status_code=422,
                detail=f"{field_name} must be at most {max_len} characters",
            )

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

        masked = url
        if password:
            masked = masked.replace(quote_plus(password), "****")

        return {"url": url, "masked_url": masked, "db_type": db_type}
    except Exception:
        return {"url": "", "error": "Failed to build URL"}


@router.post("/connections/{name}/test", dependencies=[RequireScope("read")])
async def test_connection(name: str, store: StoreD):
    """Three-phase connection test."""
    info = await store.get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        return {"status": "error", "phase": "credentials", "message": "No credentials stored (restart gateway to reload)"}

    extras = await store.get_credential_extras(name)
    phases: list[dict] = []
    t0 = time.monotonic()

    has_tunnel = (
        extras.get("ssh_tunnel")
        and extras["ssh_tunnel"].get("enabled")
        and info.db_type in ("postgres", "mysql", "redshift", "clickhouse", "mssql", "trino")
    )
    if has_tunnel:
        try:
            from ..connectors.ssh_tunnel import SSHTunnel
            from ..connectors.pool_manager import _extract_host_port
            ssh_config = extras["ssh_tunnel"]
            remote_host, remote_port = _extract_host_port(conn_str, info.db_type)
            phases.append({
                "phase": "ssh_tunnel", "status": "ok",
                "message": f"SSH tunnel config valid: {ssh_config.get('username')}@{ssh_config.get('host')}:{ssh_config.get('port', 22)}",
                "duration_ms": round((time.monotonic() - t0) * 1000, 1),
            })
        except Exception as e:
            phases.append({
                "phase": "ssh_tunnel", "status": "error",
                "message": sanitize_db_error(str(e)),
                "duration_ms": round((time.monotonic() - t0) * 1000, 1),
            })
            return {"status": "error", "phases": phases, "message": f"SSH tunnel failed: {sanitize_db_error(str(e))}"}

    t1 = time.monotonic()
    try:
        connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)
        try:
            ok = await connector.health_check()

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
                        import re as _re_ver
                        raw = str(list(vrows[0].values())[0]).split("\n")[0]
                        ver_match = _re_ver.match(r"([\w\s]+?\d+[\d.]+)", raw)
                        db_version = ver_match.group(1).strip() if ver_match else raw[:60]
            except Exception:
                pass

            phase2_duration = round((time.monotonic() - t1) * 1000, 1)
            if ok:
                msg = "Authentication and query test passed"
                if db_version:
                    msg += f" ({db_version})"
                phases.append({"phase": "database", "status": "ok", "message": msg, "duration_ms": phase2_duration})
            else:
                phases.append({"phase": "database", "status": "error", "message": "Health check failed after connection", "duration_ms": phase2_duration})
                return {"status": "error", "phases": phases, "message": "Health check failed"}

            t2 = time.monotonic()
            try:
                schema = await connector.get_schema()
                table_count = len(schema) if schema else 0
                phase3_duration = round((time.monotonic() - t2) * 1000, 1)
                if table_count > 0:
                    sample_tables = list(schema.keys())[:5]
                    phases.append({
                        "phase": "schema_access", "status": "ok",
                        "message": f"Schema readable: {table_count} tables found",
                        "sample_tables": sample_tables,
                        "duration_ms": phase3_duration,
                    })
                    schema_cache.put(name, schema)
                else:
                    phases.append({
                        "phase": "schema_access", "status": "warning",
                        "message": "Connected but no tables found — check permissions or database contents",
                        "duration_ms": phase3_duration,
                    })
            except Exception as e:
                phases.append({
                    "phase": "schema_access", "status": "warning",
                    "message": f"Schema access limited: {sanitize_db_error(str(e))}",
                    "duration_ms": round((time.monotonic() - t2) * 1000, 1),
                })
        finally:
            await pool_manager.release(info.db_type, conn_str)
    except Exception as e:
        phases.append({
            "phase": "database", "status": "error",
            "message": sanitize_db_error(str(e), db_type=info.db_type),
            "duration_ms": round((time.monotonic() - t1) * 1000, 1),
        })
        return {"status": "error", "phases": phases, "message": sanitize_db_error(str(e), db_type=info.db_type)}

    total_ms = round((time.monotonic() - t0) * 1000, 1)
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


@router.get("/connections/{name}/health", dependencies=[RequireScope("read")])
async def get_connection_health(_: UserID, name: str, window: int = Query(default=300, ge=60, le=3600)):
    """Get health stats for a specific connection."""
    stats = health_monitor.connection_stats(name, window)
    if stats is None:
        raise HTTPException(status_code=404, detail=f"No health data for connection '{name}'")
    return stats


@router.get("/connections/{name}/health/history", dependencies=[RequireScope("read")])
async def get_connection_health_history(
    _: UserID,
    name: str,
    window: int = Query(default=3600, ge=300, le=86400, description="History window in seconds"),
    bucket: int = Query(default=60, ge=10, le=3600, description="Bucket size in seconds"),
):
    """Get time-bucketed health history for sparkline/chart rendering."""
    history = health_monitor.connection_history(name, window, bucket)
    if history is None:
        raise HTTPException(status_code=404, detail=f"No health data for connection '{name}'")
    return {
        "connection_name": name,
        "window_seconds": window,
        "bucket_seconds": bucket,
        "buckets": history,
    }


@router.get("/network/info", dependencies=[RequireScope("admin")])
async def network_info(_: UserID):
    """Return this server's public IP and network info for firewall/whitelist setup."""
    result: dict = {
        "hostname": socket.gethostname(),
        "local_ips": [],
        "public_ip": None,
        "whitelist_instructions": {},
    }

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in result["local_ips"] and ip != "127.0.0.1":
                result["local_ips"].append(ip)
    except Exception:
        pass

    try:
        import urllib.request
        public_ip = urllib.request.urlopen("https://api.ipify.org", timeout=5).read().decode().strip()
        result["public_ip"] = public_ip
    except Exception:
        result["public_ip"] = None

    ip_to_whitelist = result["public_ip"] or (result["local_ips"][0] if result["local_ips"] else "YOUR_SERVER_IP")

    result["whitelist_instructions"] = {
        "aws_rds": f"RDS Console -> Security Group -> Inbound Rules -> Add: Type=Custom TCP, Port=5432, Source={ip_to_whitelist}/32",
        "aws_redshift": f"Redshift Console -> Cluster -> Properties -> VPC Security Group -> Inbound Rules -> Add: {ip_to_whitelist}/32",
        "azure_sql": f"Azure Portal -> SQL Server -> Networking -> Add firewall rule: Start={ip_to_whitelist}, End={ip_to_whitelist}",
        "gcp_cloud_sql": f"Cloud SQL Console -> Instance -> Connections -> Authorized Networks -> Add: {ip_to_whitelist}/32",
        "snowflake": f"ALTER NETWORK POLICY sp_policy SET ALLOWED_IP_LIST=('{ip_to_whitelist}'); -- Snowflake Admin -> Security -> Network Policies",
        "databricks": f"Workspace Settings -> Security -> IP Access Lists -> Add: {ip_to_whitelist}",
        "clickhouse_cloud": f"ClickHouse Cloud Console -> Service -> Security -> IP Access List -> Add: {ip_to_whitelist}/32",
    }

    return result


@router.post("/connections/{name}/diagnose", dependencies=[RequireScope("read")])
async def diagnose_connection(name: str, store: StoreD):
    """Run network-level diagnostics for a connection (DNS, TCP, TLS)."""
    import re as _re

    info = await store.get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    diagnostics: list[dict] = []

    if info.db_type in ("duckdb", "sqlite"):
        extras = await store.get_credential_extras(name)
        t0 = time.monotonic()
        try:
            connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)
            try:
                ok = await connector.health_check()
                diagnostics.append({
                    "check": "local_access",
                    "status": "ok" if ok else "error",
                    "message": "Local database accessible" if ok else "Health check failed",
                    "duration_ms": round((time.monotonic() - t0) * 1000, 1),
                })
            finally:
                await pool_manager.release(info.db_type, conn_str)
        except Exception as e:
            diagnostics.append({
                "check": "local_access", "status": "error",
                "message": f"Cannot access database: {sanitize_db_error(str(e), db_type=info.db_type)}",
                "hint": "Check the file path exists and is readable",
                "duration_ms": round((time.monotonic() - t0) * 1000, 1),
            })
        return {"host": "localhost", "port": 0, "diagnostics": diagnostics}

    host, port = "", 0
    try:
        normalized = _re.sub(r'^[a-zA-Z][a-zA-Z0-9+.\-]*://', 'http://', conn_str)
        parsed = urlparse(normalized)
        host = parsed.hostname or ""
        _default_ports = {
            "postgres": 5432, "mysql": 3306, "mssql": 1433, "redshift": 5439,
            "snowflake": 443, "bigquery": 443, "clickhouse": 9000,
            "databricks": 443, "trino": 8080, "duckdb": 0, "sqlite": 0,
        }
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
        resolved_ips = list(set(i[4][0] for i in ips))
        diagnostics.append({
            "check": "dns", "status": "ok",
            "message": f"Resolved {host} -> {', '.join(resolved_ips)}",
            "duration_ms": round((time.monotonic() - t0) * 1000, 1),
        })
    except socket.gaierror as e:
        diagnostics.append({
            "check": "dns", "status": "error",
            "message": f"DNS resolution failed for {host}: {str(e)[:100]}",
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
            "check": "tcp", "status": "ok",
            "message": f"TCP connection to {host}:{port} succeeded",
            "duration_ms": round((time.monotonic() - t1) * 1000, 1),
        })
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        diagnostics.append({
            "check": "tcp", "status": "error",
            "message": f"TCP connection to {host}:{port} failed: {str(e)[:100]}",
            "hint": "Check firewall rules, security groups, and ensure the database is running and accepting connections on this port",
            "duration_ms": round((time.monotonic() - t1) * 1000, 1),
        })
        return {"host": host, "port": port, "diagnostics": diagnostics}

    # 3. TLS handshake
    ssl_db_types = {"postgres", "mysql", "redshift", "snowflake", "bigquery", "databricks", "clickhouse", "mssql"}
    extras = await store.get_credential_extras(name)
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
                "check": "tls", "status": "ok",
                "message": f"TLS handshake succeeded ({tls_version})",
                "duration_ms": round((time.monotonic() - t2) * 1000, 1),
            })
        except Exception as e:
            diagnostics.append({
                "check": "tls", "status": "warning",
                "message": f"TLS handshake issue: {str(e)[:100]}",
                "hint": "The database may not support TLS on this port, or certificates may be misconfigured",
                "duration_ms": round((time.monotonic() - t2) * 1000, 1),
            })

    # 4. Database-level auth test
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
            "check": "auth", "status": "error",
            "message": f"Authentication failed: {sanitize_db_error(str(e), db_type=info.db_type)}",
            "hint": "Verify username, password, and that the user has permission to connect",
            "duration_ms": round((time.monotonic() - t3) * 1000, 1),
        })

    return {"host": host, "port": port, "diagnostics": diagnostics}


@router.get("/connectors/capabilities", dependencies=[RequireScope("read")])
async def get_connector_capabilities(_: UserID, db_type: str | None = None):
    """Return connector tier classification and feature matrix."""
    if db_type:
        info = _CONNECTOR_TIERS.get(db_type)
        if not info:
            raise HTTPException(status_code=404, detail=f"Unknown db_type: {db_type}")
        feature_count = sum(1 for v in info["features"].values() if v)
        total_features = len(info["features"])
        return {
            "db_type": db_type, **info,
            "feature_score": round(feature_count / total_features * 100),
            "feature_count": feature_count, "total_features": total_features,
        }

    tiers: dict[int, list] = {1: [], 2: [], 3: []}
    for dt, info in _CONNECTOR_TIERS.items():
        feature_count = sum(1 for v in info["features"].values() if v)
        total_features = len(info["features"])
        tiers[info["tier"]].append({
            "db_type": dt, **info,
            "feature_score": round(feature_count / total_features * 100),
            "feature_count": feature_count, "total_features": total_features,
        })

    return {
        "tier_1": tiers[1], "tier_2": tiers[2], "tier_3": tiers[3],
        "total_connectors": len(_CONNECTOR_TIERS),
    }


@router.get("/connections/{name}/capabilities", dependencies=[RequireScope("read")])
async def get_connection_capabilities(name: str, store: StoreD):
    """Return capabilities for a specific connection based on its db_type."""
    info = await store.get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    tier_info = _CONNECTOR_TIERS.get(info.db_type, {})
    features = tier_info.get("features", {})
    feature_count = sum(1 for v in features.values() if v)
    total_features = max(len(features), 1)

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
