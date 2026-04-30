from __future__ import annotations

import logging
import socket
import time
from urllib.parse import urlparse

from fastapi import HTTPException, Request

from gateway.api.connections._hints import _connection_error_hint
from gateway.api.connections._router import router
from gateway.api.deps import StoreD, sanitize_db_error
from gateway.auth import UserID
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache
from gateway.models import ConnectionCreate
from gateway.network_validation import resolve_and_validate, validate_connection_params
from gateway.scope_guard import RequireScope
from gateway.store import _build_connection_string, _extract_credential_extras

logger = logging.getLogger(__name__)


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
    for field_name in (
        "auth_method",
        "oauth_access_token",
        "impersonate_service_account",
        "private_key",
        "private_key_passphrase",
        "oauth_client_id",
        "oauth_client_secret",
        "jwt_token",
        "client_cert",
        "client_key",
        "kerberos_config",
        "aws_region",
        "aws_access_key_id",
        "aws_secret_access_key",
        "cluster_id",
        "workgroup",
        "azure_tenant_id",
        "azure_client_id",
        "azure_client_secret",
    ):
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
        phases.append(
            {
                "phase": "network",
                "status": "skipped",
                "message": f"{db_type} does not require network connectivity check",
                "duration_ms": 0,
            }
        )
    else:
        try:
            parsed = urlparse(conn_str if "://" in conn_str else f"dummy://{conn_str}")
            host = parsed.hostname or conn.host or "localhost"
            port = parsed.port or conn.port or 5432

            # Resolve DNS and validate IPs in one step, then connect to the
            # validated IP directly. This prevents DNS rebinding TOCTOU attacks
            # where the hostname could resolve to a different (internal) IP
            # between the SSRF check and the actual socket connect.
            try:
                validated_ips = resolve_and_validate(host, int(port), db_type)
            except ValueError:
                # If resolve_and_validate fails (e.g. non-TCP type or
                # cloud mode disabled), fall back to the hostname.
                validated_ips = [host]

            connect_ip = validated_ips[0]

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            try:
                sock.connect((connect_ip, int(port)))
                sock.close()
                phases.append(
                    {
                        "phase": "network",
                        "status": "ok",
                        "message": f"TCP connection to {host}:{port} succeeded",
                        "duration_ms": round((time.monotonic() - t1) * 1000, 1),
                    }
                )
            except (TimeoutError, OSError) as e:
                phases.append(
                    {
                        "phase": "network",
                        "status": "error",
                        "message": f"Cannot reach {host}:{port} — {str(e)[:100]}",
                        "hint": _connection_error_hint(db_type, str(e)),
                        "duration_ms": round((time.monotonic() - t1) * 1000, 1),
                    }
                )
                return {
                    "status": "error",
                    "message": f"Network unreachable: {host}:{port}",
                    "phases": phases,
                    "total_duration_ms": round((time.monotonic() - t0) * 1000, 1),
                }
        except Exception:
            phases.append(
                {
                    "phase": "network",
                    "status": "warning",
                    "message": "Could not verify network connectivity",
                    "duration_ms": round((time.monotonic() - t1) * 1000, 1),
                }
            )

    # Phase 2: Database connection / file access
    t2 = time.monotonic()
    phase2_label = "file_access" if is_embedded else "authentication"
    try:
        async with pool_manager.connection(
            db_type, conn_str, credential_extras=extras, connection_name=conn.name
        ) as connector:
            ok = await connector.health_check()
            if ok:
                msg = "File found and readable" if is_embedded else "Authenticated and connected successfully"
                phases.append(
                    {
                        "phase": phase2_label,
                        "status": "ok",
                        "message": msg,
                        "duration_ms": round((time.monotonic() - t2) * 1000, 1),
                    }
                )

                # Phase 3: Schema access
                t3 = time.monotonic()
                try:
                    schema = await connector.get_schema()
                    table_count = len(schema) if schema else 0
                    phases.append(
                        {
                            "phase": "schema_access",
                            "status": "ok",
                            "message": f"Schema access verified — {table_count} tables found",
                            "duration_ms": round((time.monotonic() - t3) * 1000, 1),
                        }
                    )
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
                    phases.append(
                        {
                            "phase": "schema_access",
                            "status": "warning",
                            "message": f"Connected but schema access limited: {sanitize_db_error(str(e))}",
                            "hint": schema_hints.get(
                                db_type, "Check SELECT permissions on information_schema or system tables"
                            ),
                            "duration_ms": round((time.monotonic() - t3) * 1000, 1),
                        }
                    )
            else:
                fail_msg = (
                    "File not found or not readable"
                    if is_embedded
                    else "Connection established but health check failed"
                )
                phases.append(
                    {
                        "phase": phase2_label,
                        "status": "error",
                        "message": fail_msg,
                        "duration_ms": round((time.monotonic() - t2) * 1000, 1),
                    }
                )
    except Exception as e:
        err_msg = sanitize_db_error(str(e))
        fail_prefix = "File access failed" if is_embedded else "Authentication failed"
        phases.append(
            {
                "phase": phase2_label,
                "status": "error",
                "message": f"{fail_prefix}: {err_msg}",
                "hint": _connection_error_hint(db_type, str(e)),
                "duration_ms": round((time.monotonic() - t2) * 1000, 1),
            }
        )

    all_ok = all(p["status"] in ("ok", "skipped") for p in phases)
    return {
        "status": "healthy" if all_ok else "error",
        "message": "All connection tests passed" if all_ok else "Connection test failed",
        "phases": phases,
        "total_duration_ms": round((time.monotonic() - t0) * 1000, 1),
    }


@router.post("/connections/{name}/test", dependencies=[RequireScope("read")])
async def test_connection(name: str, store: StoreD):
    """Three-phase connection test."""
    info = await store.get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        return {
            "status": "error",
            "phase": "credentials",
            "message": "No credentials stored (restart gateway to reload)",
        }

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
            from gateway.connectors.pool_manager import _extract_host_port

            ssh_config = extras["ssh_tunnel"]
            remote_host, remote_port = _extract_host_port(conn_str, info.db_type)
            phases.append(
                {
                    "phase": "ssh_tunnel",
                    "status": "ok",
                    "message": f"SSH tunnel config valid: {ssh_config.get('username')}@{ssh_config.get('host')}:{ssh_config.get('port', 22)}",
                    "duration_ms": round((time.monotonic() - t0) * 1000, 1),
                }
            )
        except Exception as e:
            phases.append(
                {
                    "phase": "ssh_tunnel",
                    "status": "error",
                    "message": sanitize_db_error(str(e)),
                    "duration_ms": round((time.monotonic() - t0) * 1000, 1),
                }
            )
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
                phases.append(
                    {
                        "phase": "database",
                        "status": "error",
                        "message": "Health check failed after connection",
                        "duration_ms": phase2_duration,
                    }
                )
                return {"status": "error", "phases": phases, "message": "Health check failed"}

            t2 = time.monotonic()
            try:
                schema = await connector.get_schema()
                table_count = len(schema) if schema else 0
                phase3_duration = round((time.monotonic() - t2) * 1000, 1)
                if table_count > 0:
                    sample_tables = list(schema.keys())[:5]
                    phases.append(
                        {
                            "phase": "schema_access",
                            "status": "ok",
                            "message": f"Schema readable: {table_count} tables found",
                            "sample_tables": sample_tables,
                            "duration_ms": phase3_duration,
                        }
                    )
                    schema_cache.put(name, schema)
                else:
                    phases.append(
                        {
                            "phase": "schema_access",
                            "status": "warning",
                            "message": "Connected but no tables found — check permissions or database contents",
                            "duration_ms": phase3_duration,
                        }
                    )
            except Exception as e:
                phases.append(
                    {
                        "phase": "schema_access",
                        "status": "warning",
                        "message": f"Schema access limited: {sanitize_db_error(str(e))}",
                        "duration_ms": round((time.monotonic() - t2) * 1000, 1),
                    }
                )
        finally:
            await pool_manager.release(info.db_type, conn_str)
    except Exception as e:
        phases.append(
            {
                "phase": "database",
                "status": "error",
                "message": sanitize_db_error(str(e), db_type=info.db_type),
                "duration_ms": round((time.monotonic() - t1) * 1000, 1),
            }
        )
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
        "message": "All connection tests passed"
        if overall_status == "healthy"
        else "Connection works but with warnings",
        "total_duration_ms": total_ms,
    }
