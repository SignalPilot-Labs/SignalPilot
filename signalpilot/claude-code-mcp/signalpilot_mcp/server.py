"""
SignalPilot Remote MCP Server — manage your SignalPilot instance from Claude Code.

Connects to a remote SignalPilot gateway over HTTP and exposes all
management and query tools via MCP stdio transport.

Usage:
    SIGNALPILOT_URL=https://your-gateway:3300 signalpilot-mcp-remote
    SIGNALPILOT_URL=https://your-gateway:3300 SIGNALPILOT_API_KEY=sk-... signalpilot-mcp-remote
"""

from __future__ import annotations

import json
import os
import sys
import textwrap

from mcp.server.fastmcp import FastMCP

from .client import SignalPilotClient

# ── Configuration ────────────────────────────────────────────────────────────

GATEWAY_URL = os.environ.get("SIGNALPILOT_URL", "http://localhost:3300")
API_KEY = os.environ.get("SIGNALPILOT_API_KEY", "")

_client: SignalPilotClient | None = None


def _get_client() -> SignalPilotClient:
    global _client
    if _client is None:
        _client = SignalPilotClient(GATEWAY_URL, API_KEY or None)
    return _client


mcp = FastMCP(
    "SignalPilot Remote",
    instructions=textwrap.dedent("""\
        You have access to a remote SignalPilot instance — a governed platform for
        AI database access with sandbox code execution.

        Key capabilities:
        - Query databases with automatic governance (SQL validation, LIMIT injection,
          PII redaction, audit logging, cost budgets)
        - Execute Python code in isolated Firecracker microVMs (~300ms cold start)
        - Manage database connections, sandboxes, and gateway settings
        - View audit logs, connection health, cache stats, and budgets

        The gateway is at: {url}
    """).format(url=GATEWAY_URL),
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _fmt_table(rows: list[dict], max_rows: int = 50) -> str:
    """Format a list of dicts as an aligned text table."""
    if not rows:
        return "(no rows)"
    cols = list(rows[0].keys())
    lines = [" | ".join(str(c) for c in cols)]
    lines.append("-" * len(lines[0]))
    for row in rows[:max_rows]:
        lines.append(" | ".join(str(row.get(c, "")) for c in cols))
    if len(rows) > max_rows:
        lines.append(f"... ({len(rows)} total, showing first {max_rows})")
    return "\n".join(lines)


def _err(e: Exception) -> str:
    """Format an exception for tool output."""
    if isinstance(e, Exception) and hasattr(e, "response"):
        try:
            body = e.response.json()  # type: ignore[union-attr]
            detail = body.get("detail", body)
            return f"Error: {detail}"
        except Exception:
            return f"Error: HTTP {e.response.status_code}"  # type: ignore[union-attr]
    return f"Error: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS
# ═══════════════════════════════════════════════════════════════════════════════


# ── Gateway Health ───────────────────────────────────────────────────────────


@mcp.tool()
async def signalpilot_health() -> str:
    """
    Check if the SignalPilot gateway is reachable and healthy.

    Returns gateway status, version, sandbox availability, and connection count.
    """
    try:
        data = await _get_client().health()
    except Exception as e:
        return f"Gateway at {GATEWAY_URL} is unreachable: {e}"

    lines = [
        f"Gateway: {GATEWAY_URL}",
        f"Status: {data.get('status', 'unknown')}",
    ]
    if "sandbox" in data:
        sb = data["sandbox"]
        lines.append(f"Sandbox: {sb.get('status', 'unknown')}")
    if "connections" in data:
        lines.append(f"Connections: {data['connections']}")
    return "\n".join(lines)


# ── Database Queries ─────────────────────────────────────────────────────────


@mcp.tool()
async def query_database(connection_name: str, sql: str, row_limit: int = 1000) -> str:
    """
    Execute a governed read-only SQL query on a connected database.

    All queries pass through SignalPilot's governance pipeline:
    - SQL is parsed and validated (DDL/DML blocked)
    - LIMIT is auto-injected/clamped
    - PII columns are redacted per schema annotations
    - Query cost is tracked against session budget
    - Everything is logged to the audit trail

    Args:
        connection_name: Name of a configured database connection
        sql: SQL SELECT query to execute
        row_limit: Maximum rows to return (default 1000, max 10000)

    Returns:
        Query results as a formatted text table with metadata.
    """
    try:
        data = await _get_client().query(connection_name, sql, row_limit)
    except Exception as e:
        return _err(e)

    rows = data.get("rows", [])
    meta = []
    row_count = data.get("row_count", len(rows))
    meta.append(f"{row_count} rows")
    if data.get("execution_ms") is not None:
        meta.append(f"{data['execution_ms']:.0f}ms")
    if data.get("cache_hit"):
        meta.append("cache hit")
    if data.get("cost_usd") is not None:
        meta.append(f"${data['cost_usd']:.6f}")

    result = _fmt_table(rows)
    if meta:
        result += f"\n\n[{', '.join(meta)}]"
    return result


# ── Connections ──────────────────────────────────────────────────────────────


@mcp.tool()
async def list_connections() -> str:
    """
    List all configured database connections on the SignalPilot gateway.

    Returns connection names, types, hosts, and descriptions.
    Use the connection name with query_database to run SQL.
    """
    try:
        conns = await _get_client().list_connections()
    except Exception as e:
        return _err(e)

    if not conns:
        return "No database connections configured."

    lines = []
    for c in conns:
        line = f"- {c['name']} ({c.get('db_type', '?')}) — {c.get('host', '?')}:{c.get('port', '?')}/{c.get('database', '?')}"
        if c.get("description"):
            line += f"\n  {c['description']}"
        lines.append(line)
    return "\n".join(lines)


@mcp.tool()
async def add_connection(
    name: str,
    db_type: str,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    description: str = "",
    ssl: bool = False,
) -> str:
    """
    Register a new database connection on the SignalPilot gateway.

    Args:
        name: Unique connection name (letters, numbers, hyphens, underscores)
        db_type: Database type — postgres, duckdb, mysql, or snowflake
        host: Database server hostname or IP
        port: Database server port (e.g. 5432 for postgres)
        database: Database name
        username: Database username
        password: Database password
        description: Optional human-readable description
        ssl: Whether to use SSL/TLS connection

    Returns:
        Confirmation with connection details.
    """
    try:
        result = await _get_client().create_connection({
            "name": name,
            "db_type": db_type,
            "host": host,
            "port": port,
            "database": database,
            "username": username,
            "password": password,
            "description": description,
            "ssl": ssl,
        })
    except Exception as e:
        return _err(e)
    return f"Connection '{result.get('name', name)}' created ({result.get('db_type', db_type)})"


@mcp.tool()
async def add_connection_uri(
    name: str,
    connection_string: str,
    db_type: str = "postgres",
    description: str = "",
) -> str:
    """
    Register a new database connection using a URI string.

    This is a shortcut for add_connection when you have a full connection URI.

    Args:
        name: Unique connection name
        connection_string: Full database URI (e.g. postgresql://user:pass@host:5432/db)
        db_type: Database type (default: postgres)
        description: Optional description

    Returns:
        Confirmation with connection details.
    """
    try:
        result = await _get_client().create_connection({
            "name": name,
            "db_type": db_type,
            "connection_string": connection_string,
            "description": description,
        })
    except Exception as e:
        return _err(e)
    return f"Connection '{result.get('name', name)}' created ({result.get('db_type', db_type)})"


@mcp.tool()
async def remove_connection(name: str) -> str:
    """
    Remove a database connection from the SignalPilot gateway.

    Args:
        name: Name of the connection to remove

    Returns:
        Confirmation message.
    """
    try:
        await _get_client().delete_connection(name)
    except Exception as e:
        return _err(e)
    return f"Connection '{name}' removed."


@mcp.tool()
async def test_connection(name: str) -> str:
    """
    Test connectivity to a database connection.

    Args:
        name: Name of the connection to test

    Returns:
        Success/failure message with latency.
    """
    try:
        result = await _get_client().test_connection(name)
    except Exception as e:
        return _err(e)
    status = result.get("status", "unknown")
    latency = result.get("latency_ms")
    msg = f"Connection '{name}': {status}"
    if latency is not None:
        msg += f" ({latency:.0f}ms)"
    if result.get("error"):
        msg += f"\nError: {result['error']}"
    return msg


@mcp.tool()
async def describe_schema(connection_name: str) -> str:
    """
    Get the full schema for a database connection.

    Returns all tables with their columns, types, and annotations.

    Args:
        connection_name: Name of the connection to introspect

    Returns:
        Schema information as formatted text.
    """
    try:
        schema = await _get_client().get_schema(connection_name)
    except Exception as e:
        return _err(e)

    if not schema:
        return f"No schema data for '{connection_name}'."

    lines = [f"Schema for '{connection_name}':", ""]
    tables = schema if isinstance(schema, list) else list(schema.values()) if isinstance(schema, dict) else []
    for table in tables:
        if isinstance(table, dict):
            tname = table.get("name", "?")
            tschema = table.get("schema", "public")
            cols = table.get("columns", [])
            lines.append(f"  {tschema}.{tname} ({len(cols)} columns)")
            for col in cols[:20]:
                nullable = "nullable" if col.get("nullable") else "NOT NULL"
                pk = " [PK]" if col.get("primary_key") else ""
                lines.append(f"    {col.get('name', '?')} — {col.get('type', '?')} ({nullable}){pk}")
            if len(cols) > 20:
                lines.append(f"    ... and {len(cols) - 20} more columns")
            lines.append("")
    return "\n".join(lines)


# ── Connection Health ────────────────────────────────────────────────────────


@mcp.tool()
async def connection_health(connection_name: str = "") -> str:
    """
    Check health and performance metrics for database connections.

    Returns latency percentiles (p50/p95/p99), error rates, and status.

    Args:
        connection_name: Specific connection to check (empty = all)

    Returns:
        Health stats as formatted text.
    """
    try:
        if connection_name:
            stats = await _get_client().get_connection_health(connection_name)
            return _fmt_health(stats)
        else:
            all_stats = await _get_client().get_all_health()
            if not all_stats:
                return "No health data yet. Run some queries first."
            return "\n\n".join(_fmt_health(s) for s in (all_stats if isinstance(all_stats, list) else [all_stats]))
    except Exception as e:
        return _err(e)


def _fmt_health(stats: dict) -> str:
    lines = [f"Connection: {stats.get('connection_name', '?')} ({stats.get('db_type', '?')})"]
    if stats.get("status"):
        lines.append(f"Status: {stats['status'].upper()}")
    if stats.get("latency_p50_ms") is not None:
        lines.append(f"Latency: p50={stats['latency_p50_ms']:.0f}ms  p95={stats.get('latency_p95_ms', 0):.0f}ms  p99={stats.get('latency_p99_ms', 0):.0f}ms")
    if stats.get("error_rate") is not None:
        lines.append(f"Error Rate: {stats['error_rate'] * 100:.1f}%")
    if stats.get("last_error"):
        lines.append(f"Last Error: {stats['last_error']}")
    return "\n".join(lines)


# ── Sandboxes ────────────────────────────────────────────────────────────────


@mcp.tool()
async def list_sandboxes() -> str:
    """
    List all active Firecracker microVM sandboxes.

    Returns sandbox IDs, labels, status, and uptime.
    """
    try:
        sandboxes = await _get_client().list_sandboxes()
    except Exception as e:
        return _err(e)

    if not sandboxes:
        return "No active sandboxes."

    lines = []
    for s in sandboxes:
        label = s.get("label") or s.get("id", "?")[:8]
        lines.append(f"- {label} ({s.get('status', '?')}) — id: {s.get('id', '?')[:12]}")
    return "\n".join(lines)


@mcp.tool()
async def create_sandbox(
    label: str = "",
    connection_name: str | None = None,
    budget_usd: float = 10.0,
    timeout_seconds: int = 300,
) -> str:
    """
    Create a new isolated Firecracker microVM sandbox for code execution.

    Args:
        label: Optional human-readable label
        connection_name: Optional database connection to expose inside the sandbox
        budget_usd: Cost budget for this sandbox session (default $10)
        timeout_seconds: Max lifetime in seconds (default 300)

    Returns:
        Sandbox ID and status.
    """
    try:
        result = await _get_client().create_sandbox({
            "label": label,
            "connection_name": connection_name,
            "budget_usd": budget_usd,
            "timeout_seconds": timeout_seconds,
        })
    except Exception as e:
        return _err(e)
    return f"Sandbox created: {result.get('id', '?')[:12]} ({result.get('status', '?')})"


@mcp.tool()
async def destroy_sandbox(sandbox_id: str) -> str:
    """
    Destroy an active sandbox, terminating the microVM.

    Args:
        sandbox_id: ID of the sandbox to destroy

    Returns:
        Confirmation message.
    """
    try:
        await _get_client().delete_sandbox(sandbox_id)
    except Exception as e:
        return _err(e)
    return f"Sandbox '{sandbox_id[:12]}' destroyed."


@mcp.tool()
async def execute_code(sandbox_id: str, code: str, timeout: int = 30) -> str:
    """
    Execute Python code inside an existing sandbox microVM.

    Args:
        sandbox_id: ID of the sandbox to execute in
        code: Python code to run
        timeout: Max execution time in seconds (default 30)

    Returns:
        stdout output or error message.
    """
    try:
        result = await _get_client().execute_in_sandbox(sandbox_id, code, timeout)
    except Exception as e:
        return _err(e)

    if result.get("success"):
        output = result.get("output", "").strip()
        meta = []
        if result.get("execution_ms"):
            meta.append(f"{result['execution_ms']:.0f}ms")
        suffix = f"\n[{', '.join(meta)}]" if meta else ""
        return (output or "(no output)") + suffix
    return f"Error:\n{result.get('error', 'Unknown error')}"


# ── Audit ────────────────────────────────────────────────────────────────────


@mcp.tool()
async def audit_log(limit: int = 20, connection_name: str = "") -> str:
    """
    View the SignalPilot audit trail — all queries, blocks, and executions.

    Args:
        limit: Number of entries to return (default 20)
        connection_name: Filter to a specific connection (optional)

    Returns:
        Recent audit entries as formatted text.
    """
    try:
        entries = await _get_client().audit_log(limit, 0, connection_name or None)
    except Exception as e:
        return _err(e)

    if not entries:
        return "No audit entries."

    lines = [f"Audit Log (last {len(entries)} entries):", ""]
    for entry in entries:
        ts = entry.get("timestamp", 0)
        evt = entry.get("event_type", "?")
        conn = entry.get("connection_name", "")
        blocked = " [BLOCKED]" if entry.get("blocked") else ""
        sql_preview = ""
        if entry.get("sql"):
            sql_preview = f' — {entry["sql"][:80]}...' if len(entry.get("sql", "")) > 80 else f' — {entry["sql"]}'
        lines.append(f"  [{evt}{blocked}] {conn}{sql_preview}")
    return "\n".join(lines)


# ── Budget ───────────────────────────────────────────────────────────────────


@mcp.tool()
async def check_budget(session_id: str = "default") -> str:
    """
    Check the query cost budget for a session.

    Args:
        session_id: Session to check (default: "default")

    Returns:
        Budget limit, spent, remaining, and query count.
    """
    try:
        data = await _get_client().get_budget(session_id)
    except Exception as e:
        return _err(e)

    return (
        f"Session: {data.get('session_id', session_id)}\n"
        f"Budget: ${data.get('budget_usd', 0):.2f}\n"
        f"Spent: ${data.get('spent_usd', 0):.4f}\n"
        f"Remaining: ${data.get('remaining_usd', 0):.4f}\n"
        f"Queries: {data.get('query_count', 0)}"
    )


# ── Cache ────────────────────────────────────────────────────────────────────


@mcp.tool()
async def cache_stats() -> str:
    """
    View SignalPilot query cache statistics.

    Returns cache entry count, TTL, hit/miss counts, and hit rate.
    """
    try:
        data = await _get_client().cache_stats()
    except Exception as e:
        return _err(e)

    return (
        f"Query Cache:\n"
        f"Entries: {data.get('entries', 0)} / {data.get('max_entries', 0)}\n"
        f"TTL: {data.get('ttl_seconds', 0)}s\n"
        f"Hits: {data.get('hits', 0)}\n"
        f"Misses: {data.get('misses', 0)}\n"
        f"Hit Rate: {data.get('hit_rate', 0) * 100:.1f}%"
    )


# ── Settings ─────────────────────────────────────────────────────────────────


@mcp.tool()
async def get_settings() -> str:
    """
    View the current SignalPilot gateway settings.

    Returns sandbox configuration, governance defaults, and gateway settings.
    """
    try:
        data = await _get_client().get_settings()
    except Exception as e:
        return _err(e)

    lines = ["Gateway Settings:", ""]
    for key, val in data.items():
        lines.append(f"  {key}: {val}")
    return "\n".join(lines)


@mcp.tool()
async def update_settings(settings_json: str) -> str:
    """
    Update SignalPilot gateway settings.

    Pass a JSON object with the settings to change. Only included fields
    are updated; others keep their current values.

    Example: {"default_row_limit": 5000, "default_budget_usd": 20.0}

    Args:
        settings_json: JSON string of settings to update

    Returns:
        Confirmation with updated settings.
    """
    try:
        payload = json.loads(settings_json)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"

    try:
        result = await _get_client().update_settings(payload)
    except Exception as e:
        return _err(e)

    return f"Settings updated:\n{json.dumps(result, indent=2)}"


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    """Run the SignalPilot remote MCP server over stdio."""
    if not GATEWAY_URL or GATEWAY_URL == "http://localhost:3300":
        print(
            "Tip: Set SIGNALPILOT_URL to your gateway address. "
            "Using default: http://localhost:3300",
            file=sys.stderr,
        )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
