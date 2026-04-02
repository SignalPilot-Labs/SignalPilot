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
import re
import time
import uuid

import httpx
from mcp.server.fastmcp import FastMCP

# Input validation patterns
_CONN_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_MAX_SQL_LENGTH = 100_000
_MAX_CODE_LENGTH = 1_000_000


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
    # Input validation
    if not code or not code.strip():
        return "Error: Code cannot be empty."
    if len(code) > _MAX_CODE_LENGTH:
        return f"Error: Code exceeds maximum length ({_MAX_CODE_LENGTH} characters)."
    if timeout < 1 or timeout > 300:
        return "Error: Timeout must be between 1 and 300 seconds."

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
    # Input validation
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if err := _validate_sql(sql):
        return f"Error: {err}"

    from .connectors.registry import get_connector
    from .governance.annotations import load_annotations

    conn_info = get_connection(connection_name)
    if not conn_info:
        available = [c.name for c in list_connections()]
        return f"Error: Connection '{connection_name}' not found. Available: {available}"

    # Load annotations for blocked tables (Feature #19)
    annotations = load_annotations(connection_name)
    blocked_tables = annotations.blocked_tables

    # Validate SQL (with blocked tables from annotations)
    validation = validate_sql(sql, blocked_tables=blocked_tables or None)
    if not validation.ok:
        await append_audit(AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type="block",
            connection_name=connection_name,
            sql=sql,
            blocked=True,
            block_reason=validation.blocked_reason,
        ))
        return f"Query blocked: {validation.blocked_reason}"

    # Inject LIMIT
    row_limit = min(row_limit, 10_000)
    safe_sql = inject_limit(sql, row_limit)

    # Check query cache (Feature #30)
    from .governance.cache import query_cache

    cached = query_cache.get(connection_name, sql, row_limit)
    if cached:
        await append_audit(AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type="query",
            connection_name=connection_name,
            sql=sql,
            tables=cached.tables,
            rows_returned=len(cached.rows),
            duration_ms=0.0,
            metadata={"cache_hit": True},
        ))
        rows = cached.rows
        elapsed_ms = cached.execution_ms
    else:
        conn_str = get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection (restart gateway to reload)"

        # Use pool manager for connection reuse (MED-06 fix)
        from .connectors.pool_manager import pool_manager
        from .connectors.health_monitor import health_monitor

        start = time.monotonic()
        try:
            connector = await pool_manager.acquire(conn_info.db_type, conn_str)
            rows = await connector.execute(safe_sql)
            await pool_manager.release(conn_info.db_type, conn_str)
        except Exception as e:
            elapsed_err = (time.monotonic() - start) * 1000
            health_monitor.record(connection_name, elapsed_err, False, str(e)[:200], conn_info.db_type)
            return f"Query error: {e}"

        elapsed_ms = (time.monotonic() - start) * 1000
        health_monitor.record(connection_name, elapsed_ms, True, db_type=conn_info.db_type)

        # Apply PII redaction from annotations (Feature #15)
        from .governance.pii import PIIRedactor
        pii_redactor = PIIRedactor()
        for col_name, rule in annotations.pii_columns.items():
            pii_redactor.add_rule(col_name, rule)
        if pii_redactor.has_rules():
            rows = pii_redactor.redact_rows(rows)

        # Store in cache after PII redaction
        query_cache.put(
            connection_name=connection_name,
            sql=sql,
            row_limit=row_limit,
            rows=rows,
            tables=validation.tables,
            execution_ms=elapsed_ms,
            sql_executed=safe_sql,
        )

        # Charge query cost to budget (Feature #11 + #12)
        from .governance.budget import budget_ledger
        # Cost formula: duration_sec × $0.000014 per vCPU (simplified for DB queries)
        query_cost_usd = (elapsed_ms / 1000) * 0.000014
        # Budget check uses "default" session if no specific session
        budget_ok = budget_ledger.charge("default", query_cost_usd)
        if not budget_ok:
            meta_parts_budget = [f"${query_cost_usd:.6f} cost"]
            return f"Query budget exhausted. This query would cost ~${query_cost_usd:.6f}. Remaining budget: $0.00"

        await append_audit(AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type="query",
            connection_name=connection_name,
            sql=sql,
            tables=validation.tables,
            rows_returned=len(rows),
            duration_ms=elapsed_ms,
            cost_usd=query_cost_usd,
        ))

    # Build status footer
    meta_parts = [f"{len(rows)} rows", f"{elapsed_ms:.0f}ms"]
    if cached:
        meta_parts.append("cache hit")

    if not rows:
        return f"Query returned 0 rows ({', '.join(meta_parts)})"

    # Format as readable table
    columns = list(rows[0].keys())
    lines = [" | ".join(str(c) for c in columns)]
    lines.append("-" * len(lines[0]))
    for row in rows[:50]:  # Cap display at 50 rows
        lines.append(" | ".join(str(row.get(c, "")) for c in columns))
    if len(rows) > 50:
        lines.append(f"... ({len(rows)} rows total, showing first 50)")

    return "\n".join(lines) + f"\n\n[{', '.join(meta_parts)}]"


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


@mcp.tool()
async def describe_table(connection_name: str, table_name: str) -> str:
    """
    Get detailed column information for a specific database table.

    Returns column names, types, nullability, and any annotations
    (descriptions, PII flags) from the schema.yml file.

    Args:
        connection_name: Name of a configured database connection
        table_name: Name of the table to describe

    Returns:
        Column details as formatted text.
    """
    # Input validation
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"

    from .connectors.registry import get_connector
    from .governance.annotations import load_annotations

    conn_info = get_connection(connection_name)
    if not conn_info:
        available = [c.name for c in list_connections()]
        return f"Error: Connection '{connection_name}' not found. Available: {available}"

    conn_str = get_connection_string(connection_name)
    if not conn_str:
        return "Error: No credentials stored for this connection"

    # Check schema cache first (Feature #18)
    from .connectors.schema_cache import schema_cache

    schema = schema_cache.get(connection_name)
    if schema is None:
        from .connectors.pool_manager import pool_manager
        try:
            connector = await pool_manager.acquire(conn_info.db_type, conn_str)
            schema = await connector.get_schema()
            await pool_manager.release(conn_info.db_type, conn_str)
        except Exception as e:
            return f"Error: {e}"
        schema_cache.put(connection_name, schema)

    # Find the table (case-insensitive)
    table_data = None
    for key, val in schema.items():
        if val.get("name", "").lower() == table_name.lower():
            table_data = val
            break

    if not table_data:
        table_names = [v.get("name", k) for k, v in schema.items()]
        return f"Table '{table_name}' not found. Available tables:\n" + "\n".join(f"  - {t}" for t in sorted(table_names))

    # Load annotations for descriptions/PII info
    annotations = load_annotations(connection_name)
    table_ann = annotations.get_table(table_name)

    lines = [f"Table: {table_data['schema']}.{table_data['name']}"]
    if table_ann and table_ann.description:
        lines.append(f"Description: {table_ann.description}")
    if table_ann and table_ann.owner:
        lines.append(f"Owner: {table_ann.owner}")
    lines.append(f"Columns ({len(table_data['columns'])}):")
    lines.append("")

    for col in table_data["columns"]:
        nullable = "nullable" if col.get("nullable") else "NOT NULL"
        pk = " [PK]" if col.get("primary_key") else ""
        line = f"  {col['name']} — {col['type']} ({nullable}){pk}"

        # Add annotation info
        if table_ann and col["name"] in table_ann.columns:
            col_ann = table_ann.columns[col["name"]]
            if col_ann.description:
                line += f"\n    {col_ann.description}"
            if col_ann.pii:
                line += f"\n    [PII: {col_ann.pii}]"

        lines.append(line)

    return "\n".join(lines)


@mcp.tool()
async def list_tables(connection_name: str) -> str:
    """
    List all tables in a database with compact schema overview.

    Returns a one-line-per-table summary with column names, primary keys,
    foreign keys, and row counts. This is designed for schema linking —
    read this first, then use describe_table for details on relevant tables.

    Args:
        connection_name: Name of a configured database connection

    Returns:
        Compact table listing optimized for LLM context efficiency.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"

    conn_info = get_connection(connection_name)
    if not conn_info:
        available = [c.name for c in list_connections()]
        return f"Error: Connection '{connection_name}' not found. Available: {available}"

    conn_str = get_connection_string(connection_name)
    if not conn_str:
        return "Error: No credentials stored for this connection"

    from .connectors.schema_cache import schema_cache
    schema = schema_cache.get(connection_name)
    if schema is None:
        from .connectors.pool_manager import pool_manager
        try:
            extras = get_credential_extras(connection_name)
            connector = await pool_manager.acquire(conn_info.db_type, conn_str, credential_extras=extras)
            schema = await connector.get_schema()
            await pool_manager.release(conn_info.db_type, conn_str)
        except Exception as e:
            return f"Error: {e}"
        schema_cache.put(connection_name, schema)

    # Build FK lookup
    fk_map: dict[str, str] = {}
    for key, table in schema.items():
        for fk in table.get("foreign_keys", []):
            fk_map[f"{key}.{fk['column']}"] = f"{fk.get('references_table', '')}.{fk.get('references_column', '')}"

    lines = [f"Database: {connection_name} ({conn_info.db_type})", f"Tables: {len(schema)}", ""]
    for key in sorted(schema.keys()):
        table = schema[key]
        row_count = table.get("row_count", 0)
        if row_count >= 1_000_000:
            row_str = f" ({row_count / 1_000_000:.1f}M rows)"
        elif row_count >= 1_000:
            row_str = f" ({row_count / 1_000:.0f}K rows)"
        elif row_count > 0:
            row_str = f" ({row_count} rows)"
        else:
            row_str = ""

        col_parts = []
        for col in table.get("columns", []):
            name = col["name"]
            if col.get("primary_key"):
                name += "*"
            fk_ref = fk_map.get(f"{key}.{col['name']}")
            if fk_ref:
                name += f"→{fk_ref}"
            col_parts.append(name)

        lines.append(f"{key}{row_str}: {', '.join(col_parts)}")

    return "\n".join(lines)


@mcp.tool()
async def check_budget(session_id: str = "default") -> str:
    """
    Check the remaining query budget for a session.

    Returns the budget limit, amount spent, amount remaining,
    and query count for the specified session.

    Args:
        session_id: Session ID to check (default: "default")

    Returns:
        Budget status as formatted text.
    """
    from .governance.budget import budget_ledger

    budget = budget_ledger.get_session(session_id)
    if not budget:
        return f"No budget tracking for session '{session_id}'. Create a budget via the gateway API to enable spending limits."

    return (
        f"Session: {budget.session_id}\n"
        f"Budget: ${budget.budget_usd:.2f}\n"
        f"Spent: ${budget.spent_usd:.4f}\n"
        f"Remaining: ${budget.remaining_usd:.4f}\n"
        f"Queries: {budget.query_count}\n"
        f"Status: {'EXHAUSTED' if budget.is_exhausted else 'Active'}"
    )


@mcp.tool()
async def connection_health(connection_name: str = "") -> str:
    """
    Check the health and performance of database connections.

    Returns latency percentiles (p50/p95/p99), error rates, and status
    for monitored connections. Call without arguments to see all connections.

    Args:
        connection_name: Specific connection to check (empty = all connections)

    Returns:
        Health stats as formatted text.
    """
    from .connectors.health_monitor import health_monitor

    if connection_name:
        stats = health_monitor.connection_stats(connection_name)
        if not stats:
            return f"No health data for '{connection_name}'. Run some queries first."
        return _format_health_stats(stats)

    all_stats = health_monitor.all_stats()
    if not all_stats:
        return "No health data yet. Run some queries to start collecting metrics."

    lines = [f"Connection Health ({len(all_stats)} connections):"]
    for stats in all_stats:
        lines.append("")
        lines.append(_format_health_stats(stats))
    return "\n".join(lines)


def _format_health_stats(stats: dict) -> str:
    """Format health stats dict into readable text."""
    lines = [
        f"Connection: {stats['connection_name']} ({stats['db_type']})",
        f"Status: {stats['status'].upper()}",
        f"Samples: {stats['sample_count']} (last {stats['window_seconds']}s)",
    ]
    if stats.get("successes") is not None:
        lines.append(f"Success/Fail: {stats['successes']}/{stats['failures']}")
    if stats.get("error_rate") is not None:
        lines.append(f"Error Rate: {stats['error_rate'] * 100:.1f}%")
    if stats.get("latency_p50_ms") is not None:
        lines.append(f"Latency: p50={stats['latency_p50_ms']:.0f}ms  p95={stats['latency_p95_ms']:.0f}ms  p99={stats['latency_p99_ms']:.0f}ms")
    if stats.get("last_error"):
        lines.append(f"Last Error: {stats['last_error']}")
    return "\n".join(lines)


@mcp.tool()
async def cache_status() -> str:
    """
    Check the query cache status and performance.

    Returns cache hit rate, entry count, and usage statistics.
    """
    from .governance.cache import query_cache

    stats = query_cache.stats()
    return (
        f"Query Cache Status:\n"
        f"Entries: {stats['entries']} / {stats['max_entries']}\n"
        f"TTL: {stats['ttl_seconds']}s\n"
        f"Hits: {stats['hits']}\n"
        f"Misses: {stats['misses']}\n"
        f"Hit Rate: {stats['hit_rate'] * 100:.1f}%"
    )


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    """Run the MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
