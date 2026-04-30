from __future__ import annotations

import asyncio
import socket
import time
from urllib.parse import urlparse

from fastapi import HTTPException

from gateway.api.connections._router import router
from gateway.api.deps import StoreD, sanitize_db_error
from gateway.auth import UserID
from gateway.connectors.pool_manager import pool_manager
from gateway.scope_guard import RequireScope


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
                diagnostics.append(
                    {
                        "check": "local_access",
                        "status": "ok" if ok else "error",
                        "message": "Local database accessible" if ok else "Health check failed",
                        "duration_ms": round((time.monotonic() - t0) * 1000, 1),
                    }
                )
            finally:
                await pool_manager.release(info.db_type, conn_str)
        except Exception as e:
            diagnostics.append(
                {
                    "check": "local_access",
                    "status": "error",
                    "message": f"Cannot access database: {sanitize_db_error(str(e), db_type=info.db_type)}",
                    "hint": "Check the file path exists and is readable",
                    "duration_ms": round((time.monotonic() - t0) * 1000, 1),
                }
            )
        return {"host": "localhost", "port": 0, "diagnostics": diagnostics}

    host, port = "", 0
    try:
        normalized = _re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", "http://", conn_str)
        parsed = urlparse(normalized)
        host = parsed.hostname or ""
        _default_ports = {
            "postgres": 5432,
            "mysql": 3306,
            "mssql": 1433,
            "redshift": 5439,
            "snowflake": 443,
            "bigquery": 443,
            "clickhouse": 9000,
            "databricks": 443,
            "trino": 8080,
            "duckdb": 0,
            "sqlite": 0,
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
        diagnostics.append(
            {
                "check": "dns",
                "status": "ok",
                "message": f"Resolved {host} -> {', '.join(resolved_ips)}",
                "duration_ms": round((time.monotonic() - t0) * 1000, 1),
            }
        )
    except socket.gaierror as e:
        diagnostics.append(
            {
                "check": "dns",
                "status": "error",
                "message": f"DNS resolution failed for {host}: {str(e)[:100]}",
                "hint": "Check the hostname spelling and ensure DNS is configured correctly",
                "duration_ms": round((time.monotonic() - t0) * 1000, 1),
            }
        )
        return {"host": host, "port": port, "diagnostics": diagnostics}

    # 2. TCP connectivity
    t1 = time.monotonic()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        await asyncio.to_thread(sock.connect, (host, port))
        sock.close()
        diagnostics.append(
            {
                "check": "tcp",
                "status": "ok",
                "message": f"TCP connection to {host}:{port} succeeded",
                "duration_ms": round((time.monotonic() - t1) * 1000, 1),
            }
        )
    except (TimeoutError, ConnectionRefusedError, OSError) as e:
        diagnostics.append(
            {
                "check": "tcp",
                "status": "error",
                "message": f"TCP connection to {host}:{port} failed: {str(e)[:100]}",
                "hint": "Check firewall rules, security groups, and ensure the database is running and accepting connections on this port",
                "duration_ms": round((time.monotonic() - t1) * 1000, 1),
            }
        )
        return {"host": host, "port": port, "diagnostics": diagnostics}

    # 3. TLS handshake
    ssl_db_types = {"postgres", "mysql", "redshift", "snowflake", "bigquery", "databricks", "clickhouse", "mssql"}
    extras = await store.get_credential_extras(name)
    ssl_enabled = extras.get("ssl_config", {}).get("enabled", False) or info.db_type in (
        "snowflake",
        "bigquery",
        "databricks",
    )

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
            # Force peer-cert resolution to surface chain errors.
            tls_sock.getpeercert(binary_form=False)
            tls_version = tls_sock.version()
            tls_sock.close()
            diagnostics.append(
                {
                    "check": "tls",
                    "status": "ok",
                    "message": f"TLS handshake succeeded ({tls_version})",
                    "duration_ms": round((time.monotonic() - t2) * 1000, 1),
                }
            )
        except Exception as e:
            diagnostics.append(
                {
                    "check": "tls",
                    "status": "warning",
                    "message": f"TLS handshake issue: {str(e)[:100]}",
                    "hint": "The database may not support TLS on this port, or certificates may be misconfigured",
                    "duration_ms": round((time.monotonic() - t2) * 1000, 1),
                }
            )

    # 4. Database-level auth test
    t3 = time.monotonic()
    try:
        connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)
        try:
            ok = await connector.health_check()
            diagnostics.append(
                {
                    "check": "auth",
                    "status": "ok" if ok else "error",
                    "message": "Authentication and basic query succeeded"
                    if ok
                    else "Auth succeeded but health check failed",
                    "duration_ms": round((time.monotonic() - t3) * 1000, 1),
                }
            )
        finally:
            await pool_manager.release(info.db_type, conn_str)
    except Exception as e:
        diagnostics.append(
            {
                "check": "auth",
                "status": "error",
                "message": f"Authentication failed: {sanitize_db_error(str(e), db_type=info.db_type)}",
                "hint": "Verify username, password, and that the user has permission to connect",
                "duration_ms": round((time.monotonic() - t3) * 1000, 1),
            }
        )

    return {"host": host, "port": port, "diagnostics": diagnostics}
