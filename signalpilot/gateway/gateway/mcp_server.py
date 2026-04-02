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
from .errors import query_error_hint
from .models import AuditEntry
from .store import (
    append_audit,
    get_connection,
    get_connection_string,
    list_connections,
    list_sandboxes,
    load_settings,
)

def _gateway_url() -> str:
    """Get the gateway API URL for internal MCP→REST calls."""
    import os
    return os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")


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
            async with pool_manager.connection(conn_info.db_type, conn_str) as connector:
                rows = await connector.execute(safe_sql)
        except Exception as e:
            elapsed_err = (time.monotonic() - start) * 1000
            health_monitor.record(connection_name, elapsed_err, False, str(e)[:200], conn_info.db_type)
            # Structured error feedback for agent self-correction (Spider2.0 SOTA pattern)
            err_str = str(e)
            hint = query_error_hint(err_str, conn_info.db_type)
            return f"Query error: {err_str}" + (f"\n\nHint: {hint}" if hint else "")

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
            async with pool_manager.connection(conn_info.db_type, conn_str) as connector:
                schema = await connector.get_schema()
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
            async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
                schema = await connector.get_schema()
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
async def find_join_path(connection_name: str, from_table: str, to_table: str, max_hops: int = 4) -> str:
    """
    Find FK join paths between two tables for accurate multi-table SQL generation.

    Returns the exact join columns at each hop, enabling correct JOIN construction
    without hallucinating join conditions. Essential for Spider2.0-style queries.

    Args:
        connection_name: Name of the database connection
        from_table: Source table (e.g., 'public.orders')
        to_table: Target table (e.g., 'public.products')
        max_hops: Maximum FK hops to search (1-6, default 4)
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=30) as client:
        resp = await client.get(
            f"/api/connections/{connection_name}/schema/join-paths",
            params={"from_table": from_table, "to_table": to_table, "max_hops": max_hops},
        )
        if resp.status_code != 200:
            return f"Error: {resp.text}"
        data = resp.json()

    paths = data.get("paths", [])
    if not paths:
        return f"No join path found between {from_table} and {to_table} within {max_hops} hops"

    lines = [f"Join paths: {from_table} → {to_table} ({len(paths)} found)\n"]
    for i, p in enumerate(paths):
        lines.append(f"Path {i+1} ({p['hops']} hop{'s' if p['hops'] != 1 else ''}):")
        lines.append(f"  Tables: {' → '.join(p['tables'])}")
        for j in p.get("joins", []):
            lines.append(f"  JOIN ON {j['from']} = {j['to']}")
        if p.get("sql_hint"):
            lines.append(f"  SQL: {p['sql_hint']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def get_relationships(connection_name: str, format: str = "compact") -> str:
    """
    Get all foreign key relationships for a connection — ERD overview.

    Useful for understanding the data model before writing queries.
    Returns FK arrows showing which tables reference which.

    Args:
        connection_name: Name of the database connection
        format: Output format — 'compact' (arrows), 'graph' (adjacency list)
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=30) as client:
        resp = await client.get(
            f"/api/connections/{connection_name}/schema/relationships",
            params={"format": format},
        )
        if resp.status_code != 200:
            return f"Error: {resp.text}"
        data = resp.json()

    if format == "compact":
        rels = data.get("relationships", [])
        if not rels:
            return "No foreign key relationships found"
        header = f"Foreign Key Relationships ({len(rels)}):\n"
        return header + "\n".join(f"  {r}" for r in rels)
    elif format == "graph":
        adj = data.get("adjacency", {})
        if not adj:
            return "No relationships found"
        lines = [f"Table Graph ({len(adj)} tables):\n"]
        for table, neighbors in adj.items():
            lines.append(f"  {table} ↔ {', '.join(neighbors)}")
        return "\n".join(lines)
    else:
        return json.dumps(data, indent=2)


@mcp.tool()
async def explore_table(connection_name: str, table_name: str) -> str:
    """
    Deep-dive a specific table — get full column details, types, FK refs, and sample values.

    Use this after list_tables to investigate tables relevant to the user's question.
    This follows the ReFoRCE iterative column exploration pattern (Spider2.0 SOTA).

    Args:
        connection_name: Name of the database connection
        table_name: Full table name (e.g., 'public.customers')
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=30) as client:
        resp = await client.get(
            f"/api/connections/{connection_name}/schema/explore-table",
            params={"table": table_name, "include_samples": True},
        )
        if resp.status_code != 200:
            return f"Error: {resp.text}"
        data = resp.json()

    lines = [f"Table: {data.get('table', table_name)}"]
    row_count = data.get("row_count", 0)
    if row_count:
        lines.append(f"Rows: {row_count:,}")
    if data.get("engine"):
        lines.append(f"Engine: {data['engine']}")
    lines.append("")

    # Columns
    lines.append("Columns:")
    for col in data.get("columns", []):
        parts = [f"  {col['name']}"]
        parts.append(col.get("type", "?"))
        flags = []
        if col.get("primary_key"):
            flags.append("PK")
        if not col.get("nullable", True):
            flags.append("NOT NULL")
        if col.get("foreign_key"):
            fk = col["foreign_key"]
            flags.append(f"FK→{fk['references_table']}.{fk['references_column']}")
        if flags:
            parts.append(f"[{', '.join(flags)}]")
        if col.get("comment"):
            parts.append(f"-- {col['comment']}")
        lines.append(" ".join(parts))

    # Foreign keys
    fks = data.get("foreign_keys", [])
    if fks:
        lines.append(f"\nOutgoing FKs ({len(fks)}):")
        for fk in fks:
            lines.append(f"  {fk['column']} → {fk.get('references_table', '?')}.{fk.get('references_column', '?')}")

    # Referenced by
    refs = data.get("referenced_by", [])
    if refs:
        lines.append(f"\nReferenced by ({len(refs)}):")
        for ref in refs:
            lines.append(f"  {ref['table']}.{ref['column']} → {ref['references_column']}")

    # Sample values
    samples = data.get("sample_values", {})
    if samples:
        lines.append(f"\nSample values:")
        for col_name, vals in samples.items():
            lines.append(f"  {col_name}: {', '.join(str(v) for v in vals[:5])}")

    return "\n".join(lines)


@mcp.tool()
async def schema_overview(connection_name: str) -> str:
    """
    Quick database overview — table count, columns, rows, FK density.

    Use this first to understand the database before loading schema.
    Returns a recommendation for which schema format to use.

    Args:
        connection_name: Name of the database connection
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=30) as client:
        resp = await client.get(f"/api/connections/{connection_name}/schema/overview")
        if resp.status_code != 200:
            return f"Error: {resp.text}"
        data = resp.json()

    lines = [
        f"Database: {connection_name} ({data.get('db_type', 'unknown')})",
        f"Schemas: {', '.join(data.get('schemas', []))}",
        f"Tables: {data.get('table_count', 0)}",
        f"Columns: {data.get('total_columns', 0)} (avg {data.get('avg_columns_per_table', 0)} per table)",
        f"Total rows: {data.get('total_rows', 0):,}",
        f"Foreign keys: {data.get('total_foreign_keys', 0)} across {data.get('tables_with_fks', 0)} tables",
        f"Recommended schema format: {data.get('recommendation', 'enriched')}",
    ]

    largest = data.get("largest_tables", [])
    if largest:
        lines.append(f"\nLargest tables:")
        for t in largest[:5]:
            lines.append(f"  {t['table']}: {t['rows']:,} rows, {t['columns']} cols, {t['fks']} FKs")

    return "\n".join(lines)


@mcp.tool()
async def connector_capabilities(connection_name: str = "") -> str:
    """
    Get connector tier classification and available features.

    If connection_name is provided, returns capabilities for that specific connection.
    Otherwise returns the full connector tier matrix.

    Use this to understand what schema metadata is available before querying.
    For example, if a connector doesn't support foreign_keys, you shouldn't
    rely on FK-based join path discovery.
    """
    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=15) as client:
        if connection_name:
            if not _CONN_NAME_RE.match(connection_name):
                return "Error: Invalid connection name"
            r = await client.get(f"{gw}/api/connections/{connection_name}/capabilities")
        else:
            r = await client.get(f"{gw}/api/connectors/capabilities")
    if r.status_code != 200:
        return f"Error ({r.status_code}): {r.text[:200]}"

    data = r.json()
    lines = ["Connector Capabilities:"]

    if connection_name:
        lines.append(f"  Connection: {data.get('connection_name', connection_name)}")
        lines.append(f"  DB Type: {data.get('db_type', 'unknown')}")
        lines.append(f"  Tier: {data.get('tier_label', 'unknown')}")
        lines.append(f"  Feature Score: {data.get('feature_score', 0)}%")
        features = data.get("features", {})
        enabled = [k for k, v in features.items() if v]
        disabled = [k for k, v in features.items() if not v]
        if enabled:
            lines.append(f"  Enabled: {', '.join(enabled)}")
        if disabled:
            lines.append(f"  Not Available: {', '.join(disabled)}")
        configured = data.get("configured", {})
        active = [k for k, v in configured.items() if v]
        if active:
            lines.append(f"  Active Config: {', '.join(active)}")
    else:
        for tier_key in ["tier_1", "tier_2", "tier_3"]:
            connectors = data.get(tier_key, [])
            if connectors:
                tier_num = tier_key.split("_")[1]
                lines.append(f"\n  Tier {tier_num}:")
                for c in connectors:
                    lines.append(f"    {c['db_type']}: {c.get('feature_score', 0)}% features")

    return "\n".join(lines)


@mcp.tool()
async def schema_diff(connection_name: str) -> str:
    """
    Compare current database schema against the last cached version.

    Returns added/removed/modified tables and columns. Use this after DDL changes
    or migrations to verify what changed and update your understanding of the schema.
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(f"{gw}/api/connections/{connection_name}/schema/diff")
    if r.status_code != 200:
        return f"Error ({r.status_code}): {r.text[:200]}"

    data = r.json()
    lines = [f"Schema Diff for {connection_name}:"]
    lines.append(f"  Tables: {data.get('table_count', 0)}")

    if not data.get("has_cached"):
        lines.append(f"  {data.get('message', 'No cached schema — baseline stored.')}")
        return "\n".join(lines)

    diff = data.get("diff", {})
    if not diff.get("has_changes"):
        lines.append("  No changes detected")
        return "\n".join(lines)

    added = diff.get("added_tables", [])
    removed = diff.get("removed_tables", [])
    modified = diff.get("modified_tables", [])

    if added:
        lines.append(f"  Added tables ({len(added)}): {', '.join(added[:10])}")
    if removed:
        lines.append(f"  Removed tables ({len(removed)}): {', '.join(removed[:10])}")
    if modified:
        lines.append(f"  Modified tables ({len(modified)}):")
        for m in modified[:5]:
            parts = [m['table']]
            if m.get('added_columns'):
                parts.append(f"+cols: {', '.join(m['added_columns'][:5])}")
            if m.get('removed_columns'):
                parts.append(f"-cols: {', '.join(m['removed_columns'][:5])}")
            if m.get('type_changes'):
                for tc in m['type_changes'][:3]:
                    parts.append(f"{tc['column']}: {tc['old_type']}→{tc['new_type']}")
            lines.append(f"    {' | '.join(parts)}")

    return "\n".join(lines)


@mcp.tool()
async def schema_ddl(connection_name: str, max_tables: int = 50, compress: bool = False) -> str:
    """
    Get the database schema as CREATE TABLE DDL statements.

    DDL format is preferred over JSON/text for text-to-SQL because:
    - LLMs have seen massive DDL in training, making it the natural schema format
    - DDL encodes constraints (PK, FK, NOT NULL) in standard SQL syntax
    - Spider2.0 SOTA systems (DAIL-SQL, CHESS) use DDL format

    Use this when you need to write SQL queries against the database.
    For initial exploration, use schema_overview first, then compact_schema,
    then this tool for the final DDL needed to write queries.

    Args:
        connection_name: Name of the database connection
        max_tables: Maximum number of tables to include (default 50)
        compress: Enable ReFoRCE-style table grouping for large schemas (groups similar-prefix
                  tables, shows one DDL per group with member list — saves 30-50% tokens)
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            f"{gw}/api/connections/{connection_name}/schema/ddl",
            params={"max_tables": max_tables, "compress": compress},
        )
    if r.status_code != 200:
        return f"Error ({r.status_code}): {r.text[:200]}"

    data = r.json()
    compressed = data.get("compressed_tables", 0)
    total_repr = data.get("total_tables_represented", data.get("table_count", 0))
    header = (
        f"-- Schema DDL for {connection_name}\n"
        f"-- Tables: {data.get('table_count', 0)} DDL"
    )
    if compressed:
        header += f" + {compressed} compressed ({total_repr} total)"
    header += f", Est. tokens: {data.get('token_estimate', 0)}\n\n"
    return header + data.get("ddl", "")


@mcp.tool()
async def schema_link(connection_name: str, question: str, format: str = "ddl", max_tables: int = 20) -> str:
    """
    Smart schema linking — find tables relevant to a natural language question.

    This is the recommended tool for writing SQL queries. Instead of loading the
    full schema, describe what you want to query and this tool returns only the
    relevant tables with their DDL, scored by relevance.

    Uses high-recall linking (EDBT 2026): matches question terms against table
    names, column names, and comments, then expands via foreign keys to ensure
    join paths are available.

    Args:
        connection_name: Name of the database connection
        question: Natural language question (e.g., "total revenue by customer last month")
        format: Output format — "ddl" (default, best for SQL gen), "compact", or "json"
        max_tables: Maximum tables to include (default 20)
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            f"{gw}/api/connections/{connection_name}/schema/link",
            params={"question": question, "format": format, "max_tables": max_tables},
        )
    if r.status_code != 200:
        return f"Error ({r.status_code}): {r.text[:200]}"

    data = r.json()
    linked = data.get("linked_tables", 0)
    total = data.get("total_tables", 0)
    header = (
        f"-- Schema linked for: {question}\n"
        f"-- Linked {linked}/{total} tables\n"
    )

    if format == "compact":
        return header + "\n" + data.get("schema", "")
    elif format == "json":
        import json as _json
        return header + "\n" + _json.dumps(data.get("tables", {}), indent=2, default=str)
    else:
        tokens = data.get("token_estimate", 0)
        header += f"-- Est. tokens: {tokens}\n\n"
        return header + data.get("ddl", "")


@mcp.tool()
async def explain_query(connection_name: str, sql: str) -> str:
    """
    Get the execution plan for a SQL query without running it.

    Returns the query plan, estimated rows, and cost estimate.
    Use this to validate a query before execution — catches errors,
    shows estimated cost, and reveals potential performance issues.

    This enables the "generate → explain → fix → execute" workflow
    used by Spider2.0 SOTA systems for higher accuracy.

    Args:
        connection_name: Name of the database connection
        sql: SQL query to explain
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"
    if err := _validate_sql(sql):
        return f"Error: {err}"

    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{gw}/api/query/explain",
            json={"connection_name": connection_name, "sql": sql},
        )
    if r.status_code != 200:
        return f"Error ({r.status_code}): {r.text[:300]}"

    data = r.json()
    parts = [f"-- EXPLAIN for: {connection_name}"]

    if data.get("estimated_rows"):
        parts.append(f"-- Estimated rows: {data['estimated_rows']:,}")
    if data.get("estimated_usd") and data["estimated_usd"] > 0:
        parts.append(f"-- Estimated cost: ${data['estimated_usd']:.6f}")
    if data.get("is_expensive"):
        parts.append("-- ⚠ WARNING: This query is estimated to be expensive")
    if data.get("warning"):
        parts.append(f"-- Note: {data['warning']}")

    plan = data.get("plan", "")
    if plan:
        parts.append(f"\n{plan}")

    return "\n".join(parts)


@mcp.tool()
async def validate_sql(connection_name: str, sql: str) -> str:
    """
    Validate SQL syntax and semantics without executing the query.

    Uses EXPLAIN to check if the SQL is valid against the actual database schema.
    Returns validation result: OK with plan summary, or error with specific
    line/position information and a fix suggestion.

    This is the "format restriction" step in the ReFoRCE self-refinement loop:
    generate SQL → validate → fix errors → execute.

    Args:
        connection_name: Name of the database connection
        sql: SQL query to validate
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"
    if err := _validate_sql(sql):
        return f"Error: {err}"

    # First: basic local checks
    sql_stripped = sql.strip().rstrip(";")
    issues = []
    sql_upper = sql_stripped.upper()
    if not any(sql_upper.startswith(kw) for kw in ("SELECT", "WITH", "EXPLAIN", "SHOW", "DESCRIBE")):
        issues.append("Query should start with SELECT, WITH, SHOW, or DESCRIBE for read-only execution.")

    # Try EXPLAIN to validate against actual schema
    gw = _gateway_url()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{gw}/api/query/explain",
                json={"connection_name": connection_name, "sql": sql},
            )
        if r.status_code == 200:
            data = r.json()
            parts = ["VALID ✓"]
            if data.get("estimated_rows"):
                parts.append(f"Estimated rows: {data['estimated_rows']:,}")
            if data.get("is_expensive"):
                parts.append("Warning: query may be expensive")
            if issues:
                parts.append(f"Local checks: {'; '.join(issues)}")
            return "\n".join(parts)
        else:
            # Extract error details
            error_text = r.text[:500]
            # Get db_type for dialect-specific hints
            db_type = ""
            try:
                async with httpx.AsyncClient(timeout=5) as client2:
                    r2 = await client2.get(f"{gw}/api/connections/{connection_name}")
                    if r2.status_code == 200:
                        db_type = r2.json().get("db_type", "")
            except Exception:
                pass
            hint = query_error_hint(error_text, db_type)
            parts = [f"INVALID ✗\n{error_text}"]
            if hint:
                parts.append(f"\nSuggested fix: {hint}")
            return "\n".join(parts)
    except Exception as e:
        return f"Validation error: {e}"


@mcp.tool()
async def query_history(connection_name: str, limit: int = 10) -> str:
    """
    Get recent successful queries for a database connection.

    Useful for learning query patterns, understanding the data model
    through real usage, and avoiding repeating previously failed queries.

    Spider2.0 SOTA insight: agents that reference prior successful queries
    have higher accuracy on follow-up questions in the same session.

    Args:
        connection_name: Name of the database connection
        limit: Max queries to return (default 10, max 50)
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    limit = min(limit, 50)
    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{gw}/api/audit",
            params={
                "connection_name": connection_name,
                "event_type": "query",
                "limit": limit,
            },
        )
    if r.status_code != 200:
        return f"Error ({r.status_code}): {r.text[:200]}"

    data = r.json()
    entries = data.get("entries", [])
    if not entries:
        return f"No recent queries for {connection_name}"

    lines = [f"-- Recent queries for {connection_name} ({len(entries)} shown)\n"]
    for e in entries:
        ts = e.get("timestamp", 0)
        sql = e.get("sql", "")
        rows = e.get("rows_returned", 0)
        ms = e.get("duration_ms", 0)
        blocked = e.get("blocked", False)

        if blocked:
            continue  # Skip blocked queries

        # Format timestamp
        import time as _time
        try:
            ts_str = _time.strftime("%H:%M:%S", _time.localtime(ts))
        except Exception:
            ts_str = "?"

        lines.append(f"-- [{ts_str}] {rows} rows, {ms:.0f}ms")
        lines.append(sql.strip())
        lines.append("")

    return "\n".join(lines) if len(lines) > 1 else f"No successful queries for {connection_name}"


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


@mcp.tool()
async def explore_columns(
    connection_name: str,
    table: str,
    columns: list[str] | None = None,
    include_samples: bool = True,
    include_stats: bool = True,
) -> str:
    """
    Explore specific columns in a table — their types, statistics, and sample values.

    Use this for iterative column exploration (ReFoRCE pattern): first use
    schema_link to find relevant tables, then explore_columns to understand
    specific columns before writing SQL.

    Args:
        connection_name: Name of the database connection
        table: Full table name (e.g., "public.customers")
        columns: Optional list of column names to explore. If None, explores all.
        include_samples: Whether to include sample distinct values
        include_stats: Whether to include column statistics

    Returns column details: type, nullable, primary_key, comment, stats, sample values
    """
    err = _validate_connection_name(connection_name)
    if err:
        return err

    try:
        # Use the deep column exploration endpoint (single API call)
        gw = _gateway_url()
        body: dict = {
            "table": table,
            "include_stats": include_stats,
            "include_values": include_samples,
            "value_limit": 10,
        }
        if columns:
            body["columns"] = columns

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{gw}/api/connections/{connection_name}/schema/explore-columns",
                json=body,
            )
        if resp.status_code == 404:
            return f"Table '{table}' not found. Check the table name with schema_link first."
        if resp.status_code != 200:
            return f"Error: {resp.text}"

        data = resp.json()
        explored_cols = data.get("columns", [])

        # Build response
        table_type = data.get("table_type", "table")
        rc = data.get("row_count", "?")
        lines = [f"{'View' if table_type == 'view' else 'Table'}: {table} ({rc:,} rows)" if isinstance(rc, int) else f"Table: {table} ({rc} rows)"]
        lines.append("")

        for col in explored_cols:
            parts = [f"  {col['name']}: {col.get('type', 'unknown')}"]
            flags = []
            if col.get("primary_key"):
                flags.append("PK")
            if not col.get("nullable", True):
                flags.append("NOT NULL")
            if flags:
                parts.append(f"[{', '.join(flags)}]")
            if col.get("comment"):
                parts.append(f"-- {col['comment']}")
            lines.append(" ".join(parts))

            # Schema statistics (distinct count, cardinality)
            if include_stats and col.get("schema_stats"):
                stats = col["schema_stats"]
                stat_parts = []
                if stats.get("distinct_count"):
                    stat_parts.append(f"distinct={stats['distinct_count']}")
                if stats.get("distinct_fraction"):
                    frac = abs(stats["distinct_fraction"])
                    stat_parts.append(f"uniqueness={frac:.2f}")
                if stat_parts:
                    lines.append(f"    stats: {', '.join(stat_parts)}")

            # Numeric value stats (min/max/avg)
            if include_stats and col.get("value_stats"):
                vs = col["value_stats"]
                vs_parts = []
                if vs.get("min") is not None:
                    vs_parts.append(f"min={vs['min']}")
                if vs.get("max") is not None:
                    vs_parts.append(f"max={vs['max']}")
                if vs.get("avg") is not None:
                    vs_parts.append(f"avg={vs['avg']}")
                if vs_parts:
                    lines.append(f"    range: {', '.join(vs_parts)}")

            # Sample values
            if include_samples and col.get("sample_values"):
                vals = col["sample_values"][:10]
                lines.append(f"    values: {', '.join(repr(v) for v in vals)}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error exploring columns: {e}"


@mcp.tool()
async def schema_statistics(connection_name: str) -> str:
    """
    Get a high-level summary of the database schema — table counts, total rows,
    column counts, FK density. Useful for understanding the overall data landscape
    before diving into specific tables.

    Returns: overview with tables sorted by size and FK connectivity.
    """
    err = _validate_connection_name(connection_name)
    if err:
        return err

    try:
        gw = _gateway_url()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{gw}/api/connections/{connection_name}/schema/overview")
        if resp.status_code != 200:
            return f"Error: {resp.text}"

        data = resp.json()
        lines = [
            f"Database: {connection_name} ({data.get('db_type', '?')})",
            f"Tables: {data.get('table_count', 0)}",
            f"Total columns: {data.get('total_columns', 0)}",
            f"Total rows: {data.get('total_rows', 0):,}",
            f"Foreign key relationships: {data.get('total_foreign_keys', 0)}",
            "",
        ]

        # Show top tables by row count
        top = data.get("largest_tables", [])
        if top:
            lines.append("Largest tables:")
            for t in top[:10]:
                name = t.get("table", "?")
                meta_parts = [f"{t.get('rows', 0):,} rows", f"{t.get('columns', 0)} cols"]
                if t.get("engine"):
                    meta_parts.append(f"engine={t['engine']}")
                if t.get("sorting_key"):
                    meta_parts.append(f"order_by={t['sorting_key']}")
                if t.get("diststyle"):
                    meta_parts.append(f"dist={t['diststyle']}")
                if t.get("sortkey"):
                    meta_parts.append(f"sort={t['sortkey']}")
                if t.get("clustering_key"):
                    meta_parts.append(f"cluster={t['clustering_key']}")
                if t.get("size_bytes") and t["size_bytes"] > 0:
                    mb = t["size_bytes"] / (1024 * 1024)
                    meta_parts.append(f"size={mb:.1f}MB")
                elif t.get("size_mb") and t["size_mb"] > 0:
                    meta_parts.append(f"size={t['size_mb']}MB")
                lines.append(f"  {name}: {', '.join(meta_parts)}")

        # Hub tables (most FK connections — derived from largest_tables)
        hub = sorted([t for t in top if t.get("fks", 0) > 0], key=lambda t: -t.get("fks", 0))
        if hub:
            lines.append("")
            lines.append("Hub tables (most relationships):")
            for t in hub[:5]:
                lines.append(f"  {t.get('table', '?')}: {t.get('fks', 0)} FKs")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def explore_column(
    connection_name: str,
    table: str,
    column: str,
    limit: int = 20,
    filter_pattern: str = "",
) -> str:
    """
    Explore distinct values in a specific column — critical for Spider2.0.

    ReFoRCE-style iterative column exploration: probe actual column values
    to resolve ambiguity when the question uses domain terminology not in
    column names. Returns top distinct values with counts and NULL stats.

    Args:
        connection_name: Database connection to query.
        table: Full table name (e.g., 'public.users' or 'schema.table').
        column: Column name to explore.
        limit: Max distinct values to return (default 20).
        filter_pattern: Optional LIKE pattern to filter values (e.g., '%active%').
    """
    err = _validate_connection_name(connection_name)
    if err:
        return err

    try:
        gw = _gateway_url()
        params = {"table": table, "column": column, "limit": limit}
        if filter_pattern:
            params["filter_pattern"] = filter_pattern

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{gw}/api/connections/{connection_name}/schema/explore",
                params=params,
            )
        if resp.status_code != 200:
            return f"Error: {resp.text}"

        data = resp.json()
        lines = [f"Column: {table}.{column}"]

        stats = data.get("statistics", {})
        lines.append(f"Total rows: {stats.get('total_rows', 0):,}")
        lines.append(f"Distinct values: {stats.get('distinct_count', 0):,}")
        lines.append(f"NULL: {stats.get('null_count', 0):,} ({stats.get('null_pct', 0)}%)")

        if data.get("filter"):
            lines.append(f"Filter: LIKE '{data['filter']}'")

        lines.append("")
        values = data.get("values", [])
        if values:
            lines.append("Top values:")
            for v in values:
                val_str = str(v.get("value")) if v.get("value") is not None else "NULL"
                lines.append(f"  {val_str}: {v.get('count', 0):,}")
        else:
            lines.append("No values found.")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {e}"


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    """Run the MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
