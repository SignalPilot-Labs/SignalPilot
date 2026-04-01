"""
SignalPilot MCP Server — exposes governed sandbox + database tools.

Run with stdio transport (for Claude Code):
    python -m gateway.mcp_server

Tools exposed:
    execute_code     — Run Python code in an isolated Firecracker microVM
    query_database   — Run governed read-only SQL against a connected database
    list_connections — List configured database connections
    list_sandboxes   — List active sandbox sessions
    sandbox_health   — Check sandbox manager status
"""

from __future__ import annotations

import json
import time
import uuid

import httpx
from mcp.server.fastmcp import FastMCP

from .engine import inject_limit, validate_sql
from .models import AuditEntry
from .store import (
    append_audit,
    get_connection,
    get_connection_string,
    list_connections,
    list_sandboxes,
    load_settings,
)

mcp = FastMCP(
    "SignalPilot",
    instructions=(
        "You have access to SignalPilot, a governed sandbox for AI database access. "
        "Use execute_code to run Python in an isolated Firecracker microVM (~300ms). "
        "Use query_database for read-only SQL with automatic governance (LIMIT injection, "
        "DDL/DML blocking, audit logging). Use list_connections to see available databases."
    ),
)


def _get_sandbox_url() -> str:
    settings = load_settings()
    return settings.sandbox_manager_url


# ─── Tools ───────────────────────────────────────────────────────────────────


@mcp.tool()
async def execute_code(code: str, timeout: int = 30) -> str:
    """
    Execute Python code in an isolated Firecracker microVM sandbox.

    The code runs in a secure, ephemeral microVM with Python 3.10 and common
    stdlib modules pre-loaded (math, re, collections, datetime, etc.).
    Each execution gets a fresh VM that is destroyed after returning.
    Typical latency: ~300ms (snapshot-accelerated).

    Args:
        code: Python code to execute
        timeout: Max execution time in seconds (default 30)

    Returns:
        The stdout output from the code, or an error message.
    """
    # Input length validation (MED-07)
    if len(code) > 1_000_000:
        return "Error: Code exceeds maximum length (1MB)"

    sandbox_url = _get_sandbox_url()

    async with httpx.AsyncClient(timeout=timeout + 10) as client:
        try:
            resp = await client.post(
                f"{sandbox_url}/execute",
                json={
                    "code": code,
                    "session_token": str(uuid.uuid4()),
                    "timeout": timeout,
                },
            )
            data = resp.json()
        except httpx.ConnectError:
            return f"Error: Cannot connect to sandbox manager at {sandbox_url}. Is Firecracker running?"
        except Exception as e:
            return f"Error: {e}"

    # Log to audit
    await append_audit(AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        event_type="execute",
        metadata={
            "code_preview": code[:200],
            "success": data.get("success", False),
            "execution_ms": data.get("execution_ms"),
            "restore_ms": data.get("restore_ms"),
        },
    ))

    if data.get("success"):
        output = data.get("output", "").strip()
        meta = []
        if data.get("restore_ms"):
            meta.append(f"restore={data['restore_ms']:.0f}ms")
        if data.get("execution_ms"):
            meta.append(f"total={data['execution_ms']:.0f}ms")
        suffix = f"\n[{', '.join(meta)}]" if meta else ""
        return output + suffix if output else f"(no output){suffix}"
    else:
        error = data.get("error", "Unknown error")
        return f"Error:\n{error}"


@mcp.tool()
async def query_database(connection_name: str, sql: str, row_limit: int = 1000) -> str:
    """
    Execute a governed, read-only SQL query against a connected database.

    All queries are validated through the SignalPilot governance pipeline:
    - SQL is parsed to AST and checked for DDL/DML (blocked)
    - Statement stacking is detected and blocked
    - LIMIT is automatically injected/clamped
    - Results are logged to the audit trail

    Args:
        connection_name: Name of a configured database connection
        sql: SQL query (SELECT only)
        row_limit: Max rows to return (default 1000, max 10000)

    Returns:
        Query results as formatted text, or an error message.
    """
    from .connectors.registry import get_connector
    from .connectors.base import BaseConnector

    # Input length validation (MED-07)
    if len(sql) > 100_000:
        return "Error: SQL query exceeds maximum length (100KB)"

    conn_info = get_connection(connection_name)
    if not conn_info:
        available = [c.name for c in list_connections()]
        return f"Error: Connection '{connection_name}' not found. Available: {available}"

    # Validate SQL
    validation = validate_sql(sql)
    if not validation.ok:
        await append_audit(AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type="block",
            connection_name=connection_name,
            sql=sql[:1000],  # Truncate in audit to prevent log bloat
            blocked=True,
            block_reason=validation.blocked_reason,
        ))
        return f"Query blocked: {validation.blocked_reason}"

    # Inject LIMIT
    row_limit = min(row_limit, 10_000)
    safe_sql = inject_limit(sql, row_limit)

    conn_str = get_connection_string(connection_name)
    if not conn_str:
        return "Error: No credentials stored for this connection (restart gateway to reload)"

    # Use persistent pool (reuse across queries)
    if not hasattr(query_database, "_pool_cache"):
        query_database._pool_cache = {}

    pool_cache = query_database._pool_cache
    connector = pool_cache.get(connection_name)
    if connector and not await connector.health_check():
        await connector.close()
        connector = None

    if connector is None:
        connector = get_connector(conn_info.db_type)
        await connector.connect(conn_str, ssl=conn_info.ssl)
        pool_cache[connection_name] = connector

    start = time.monotonic()
    try:
        rows = await connector.execute(safe_sql)
    except Exception as e:
        pool_cache.pop(connection_name, None)
        return f"Query error: {e}"

    elapsed_ms = (time.monotonic() - start) * 1000

    await append_audit(AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        event_type="query",
        connection_name=connection_name,
        sql=sql,
        tables=validation.tables,
        rows_returned=len(rows),
        duration_ms=elapsed_ms,
    ))

    if not rows:
        return f"Query returned 0 rows ({elapsed_ms:.0f}ms)"

    # Format as readable table
    columns = list(rows[0].keys())
    lines = [" | ".join(str(c) for c in columns)]
    lines.append("-" * len(lines[0]))
    for row in rows[:50]:  # Cap display at 50 rows
        lines.append(" | ".join(str(row.get(c, "")) for c in columns))
    if len(rows) > 50:
        lines.append(f"... ({len(rows)} rows total, showing first 50)")

    return "\n".join(lines) + f"\n\n[{len(rows)} rows, {elapsed_ms:.0f}ms]"


@mcp.tool()
async def list_database_connections() -> str:
    """
    List all configured database connections.

    Returns connection names, types, hosts, and status.
    Use the connection name with query_database to run SQL.
    """
    connections = list_connections()
    if not connections:
        return "No database connections configured. Add one via the SignalPilot UI at http://localhost:3200/connections"

    lines = []
    for c in connections:
        lines.append(f"- {c.name} ({c.db_type}) — {c.host}:{c.port}/{c.database}")
        if c.description:
            lines.append(f"  {c.description}")
    return "\n".join(lines)


@mcp.tool()
async def sandbox_status() -> str:
    """
    Check the health of the sandbox manager and list active sandboxes.

    Returns sandbox manager health, KVM status, snapshot readiness,
    and any active sandbox sessions.
    """
    settings = load_settings()
    sandbox_url = settings.sandbox_manager_url

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{sandbox_url}/health")
            health = resp.json()
    except Exception as e:
        return f"Sandbox manager at {sandbox_url}: OFFLINE ({e})"

    lines = [
        f"Sandbox Manager: {sandbox_url}",
        f"Status: {health.get('status', 'unknown')}",
        f"KVM: {'available' if health.get('kvm_available') else 'NOT available'}",
        f"Snapshot: {'ready (fast mode ~300ms)' if health.get('snapshot_ready') else 'not ready (cold boot ~1600ms)'}",
        f"Active VMs: {health.get('active_vms', 0)} / {health.get('max_vms', 10)}",
    ]

    sandboxes = list_sandboxes()
    if sandboxes:
        lines.append(f"\nActive sandboxes: {len(sandboxes)}")
        for s in sandboxes:
            lines.append(f"  - {s.label or s.id[:8]} ({s.status})")

    return "\n".join(lines)


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    """Run the MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
