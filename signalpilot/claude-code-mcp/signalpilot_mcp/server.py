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
from .agent_client import AgentClient

# ── Configuration ────────────────────────────────────────────────────────────

GATEWAY_URL = os.environ.get("SIGNALPILOT_URL", "http://localhost:3300")
API_KEY = os.environ.get("SIGNALPILOT_API_KEY", "")
MONITOR_URL = os.environ.get("SIGNALPILOT_MONITOR_URL", "http://localhost:3401")

_client: SignalPilotClient | None = None
_agent_client: AgentClient | None = None


def _get_client() -> SignalPilotClient:
    global _client
    if _client is None:
        _client = SignalPilotClient(GATEWAY_URL, API_KEY or None)
    return _client


def _get_agent_client() -> AgentClient:
    global _agent_client
    if _agent_client is None:
        _agent_client = AgentClient(MONITOR_URL)
    return _agent_client


mcp = FastMCP(
    "SignalPilot Remote",
    instructions=textwrap.dedent("""\
        You have access to a remote SignalPilot instance — a governed platform for
        AI database access with sandbox code execution, plus a self-improving
        AI agent that autonomously improves the SignalPilot codebase.

        Key capabilities:
        - Query databases with automatic governance (SQL validation, LIMIT injection,
          PII redaction, audit logging, cost budgets)
        - Execute Python code in isolated Firecracker microVMs (~300ms cold start)
        - Manage database connections, sandboxes, and gateway settings
        - View audit logs, connection health, cache stats, and budgets
        - Start, monitor, pause, resume, stop, and inject prompts into the
          self-improving agent — a Claude-powered autonomous coding agent
        - View agent run history, tool calls, diffs, and real-time output

        The gateway is at: {gateway}
        The self-improve monitor is at: {monitor}
    """).format(gateway=GATEWAY_URL, monitor=MONITOR_URL),
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
    """Format an exception into a clear, actionable error message."""
    import httpx

    # Connection-level failures (server unreachable)
    if isinstance(e, httpx.ConnectError):
        return f"Error: Cannot reach server — is it running? ({e})"
    if isinstance(e, httpx.ConnectTimeout):
        return "Error: Connection timed out — server may be down or unreachable."
    if isinstance(e, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return "Error: Request timed out — the operation took too long."
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out."

    # HTTP error responses (4xx, 5xx)
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        detail = ""
        try:
            body = e.response.json()
            detail = body.get("detail", "") if isinstance(body, dict) else str(body)
        except Exception:
            detail = e.response.text[:200] if e.response.text else ""

        if status == 401 or status == 403:
            return f"Error: Authentication failed — check SIGNALPILOT_API_KEY. ({detail})" if detail else "Error: Authentication failed — check SIGNALPILOT_API_KEY."
        if status == 404:
            return f"Error: Not found: {detail}" if detail else "Error: Not found."
        if status == 409:
            return f"Error: {detail}" if detail else "Error: Conflict — operation not allowed in current state."
        return f"Error: HTTP {status}: {detail}" if detail else f"Error: HTTP {status}"

    # Fallback
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


@mcp.tool()
async def invalidate_cache(connection_name: str = "") -> str:
    """
    Clear the query cache. Useful after schema changes or data updates.

    Args:
        connection_name: Clear cache only for this connection (empty = all)

    Returns:
        Confirmation message.
    """
    try:
        result = await _get_client().cache_invalidate(connection_name or None)
    except Exception as e:
        return _err(e)
    cleared = result.get("cleared", "?")
    scope = f" for '{connection_name}'" if connection_name else ""
    return f"Cache invalidated{scope}. {cleared} entries cleared."


# ── Annotations & PII ────────────────────────────────────────────────────────


@mcp.tool()
async def get_annotations(connection_name: str) -> str:
    """
    View schema annotations for a database connection.

    Annotations include table descriptions, column metadata, PII flags,
    sensitivity levels, and owners. These are defined in schema.yml files
    and control governance behavior (PII redaction, blocked tables, etc.).

    Args:
        connection_name: Name of the connection

    Returns:
        Annotation details as formatted text.
    """
    try:
        data = await _get_client().get_annotations(connection_name)
    except Exception as e:
        return _err(e)

    if not data or (isinstance(data, dict) and not data.get("tables")):
        return f"No annotations configured for '{connection_name}'."

    lines = [f"Annotations for '{connection_name}':", ""]
    tables = data.get("tables", data) if isinstance(data, dict) else data
    if isinstance(tables, dict):
        for tname, info in tables.items():
            desc = info.get("description", "")
            owner = info.get("owner", "")
            lines.append(f"  {tname}")
            if desc:
                lines.append(f"    Description: {desc}")
            if owner:
                lines.append(f"    Owner: {owner}")
            if info.get("sensitivity"):
                lines.append(f"    Sensitivity: {info['sensitivity']}")
            cols = info.get("columns", {})
            for col_name, col_info in cols.items():
                if col_info.get("pii"):
                    lines.append(f"    [{col_name}] PII: {col_info['pii']}")
            lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def detect_pii(connection_name: str) -> str:
    """
    Auto-detect PII (personally identifiable information) in a database.

    Scans column names and sample data to find columns that may contain
    emails, phone numbers, SSNs, credit card numbers, or IP addresses.
    Results can be used to set up automatic PII redaction rules.

    Args:
        connection_name: Name of the connection to scan

    Returns:
        Detected PII columns and their types.
    """
    try:
        data = await _get_client().detect_pii(connection_name)
    except Exception as e:
        return _err(e)

    detections = data.get("detections", data) if isinstance(data, dict) else data
    if not detections:
        return f"No PII detected in '{connection_name}'."

    lines = [f"PII Detection for '{connection_name}':", ""]
    if isinstance(detections, list):
        for d in detections:
            table = d.get("table", "?")
            column = d.get("column", "?")
            pii_type = d.get("pii_type", "?")
            confidence = d.get("confidence", "?")
            lines.append(f"  {table}.{column} — {pii_type} (confidence: {confidence})")
    elif isinstance(detections, dict):
        for table, cols in detections.items():
            for col, info in (cols.items() if isinstance(cols, dict) else []):
                lines.append(f"  {table}.{col} — {info}")
    return "\n".join(lines)


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
# SELF-IMPROVE AGENT TOOLS
# ═══════════════════════════════════════════════════════════════════════════════


def _fmt_run(run: dict) -> str:
    """Format a single run dict into readable text."""
    lines = [f"Run: {run.get('id', '?')[:12]}"]
    if run.get("status"):
        lines[0] += f"  [{run['status'].upper()}]"
    if run.get("branch_name"):
        lines.append(f"  Branch: {run['branch_name']}")
    if run.get("custom_prompt"):
        lines.append(f"  Prompt: {run['custom_prompt'][:120]}")
    if run.get("base_branch"):
        lines.append(f"  Base: {run['base_branch']}")
    if run.get("total_cost_usd") is not None:
        lines.append(f"  Cost: ${run['total_cost_usd']:.2f}")
    tokens_in = run.get("total_input_tokens", 0) or 0
    tokens_out = run.get("total_output_tokens", 0) or 0
    if tokens_in or tokens_out:
        lines.append(f"  Tokens: {tokens_in:,} in / {tokens_out:,} out")
    if run.get("started_at"):
        lines.append(f"  Started: {run['started_at']}")
    if run.get("finished_at"):
        lines.append(f"  Finished: {run['finished_at']}")
    if run.get("duration_minutes"):
        lines.append(f"  Duration: {run['duration_minutes']}m")
    if run.get("pr_url"):
        lines.append(f"  PR: {run['pr_url']}")
    return "\n".join(lines)


# ── Agent Health ─────────────────────────────────────────────────────────────


@mcp.tool()
async def agent_health() -> str:
    """
    Check the status of the self-improving agent.

    Returns whether the agent is idle or running, the current run ID,
    elapsed time, and time remaining if a run is active.
    """
    try:
        data = await _get_agent_client().agent_health()
    except Exception as e:
        return f"Agent at {MONITOR_URL} is unreachable: {e}"

    status = data.get("status", "unknown")
    lines = [f"Agent Status: {status.upper()}"]
    if data.get("current_run_id"):
        lines.append(f"Current Run: {data['current_run_id'][:12]}")
    if data.get("elapsed_minutes") is not None:
        lines.append(f"Elapsed: {data['elapsed_minutes']:.0f}m")
    if data.get("time_remaining"):
        lines.append(f"Remaining: {data['time_remaining']}")
    if data.get("session_unlocked") is not None:
        lines.append(f"Session Unlocked: {data['session_unlocked']}")
    return "\n".join(lines)


# ── Start / Resume / Stop ────────────────────────────────────────────────────


@mcp.tool()
async def start_improvement_run(
    prompt: str = "",
    duration_minutes: float = 30,
    max_budget_usd: float = 0,
    base_branch: str = "main",
) -> str:
    """
    Start a new self-improvement run on the SignalPilot codebase.

    The agent will autonomously analyze the codebase, identify improvements,
    implement changes, run tests, commit, and create a PR. A CEO/PM layer
    reviews work between rounds and assigns the next task.

    Args:
        prompt: Custom focus/task for the agent (e.g. "improve test coverage for the gateway").
                If empty, the agent does a general improvement pass.
        duration_minutes: How long the agent should work (default 30). Set to 0 for unlimited.
        max_budget_usd: Maximum API spend in USD (0 = use server default).
        base_branch: Git branch to base work from (default: main).

    Returns:
        Run ID and configuration details.
    """
    try:
        data = await _get_agent_client().start_run(
            prompt=prompt or None,
            max_budget_usd=max_budget_usd,
            duration_minutes=duration_minutes,
            base_branch=base_branch,
        )
    except Exception as e:
        return _err(e)

    run_id = data.get("run_id", "?")
    lines = [f"Improvement run started!"]
    if run_id and run_id != "?":
        lines.append(f"Run ID: {run_id[:12]}")
    if data.get("prompt"):
        lines.append(f"Prompt: {data['prompt']}")
    lines.append(f"Duration: {duration_minutes}m")
    lines.append(f"Base Branch: {base_branch}")
    if data.get("max_budget_usd"):
        lines.append(f"Budget: ${data['max_budget_usd']:.2f}")
    return "\n".join(lines)


@mcp.tool()
async def resume_improvement_run(run_id: str, max_budget_usd: float = 0) -> str:
    """
    Resume a previously stopped or rate-limited improvement run.

    The agent picks up where it left off, using the same branch and
    session context. Useful after rate limiting or manual stops.

    Args:
        run_id: ID of the run to resume (from list_improvement_runs)
        max_budget_usd: Additional budget for the resumed run (0 = server default)

    Returns:
        Confirmation that the run has been resumed.
    """
    try:
        data = await _get_agent_client().resume_run(run_id, max_budget_usd)
    except Exception as e:
        return _err(e)
    return f"Run {run_id[:12]} resumed."


@mcp.tool()
async def stop_improvement_run(run_id: str = "", reason: str = "") -> str:
    """
    Gracefully stop the current improvement run.

    The agent will commit its work, push the branch, and create a PR
    before shutting down. Use this for a clean stop.

    If run_id is provided, sends the stop signal through the control
    channel (allows the agent to wrap up). If omitted, sends an instant
    stop to whatever is currently running.

    Args:
        run_id: Specific run to stop (optional — defaults to current run)
        reason: Why you're stopping (logged in audit trail)

    Returns:
        Confirmation message.
    """
    try:
        if run_id:
            data = await _get_agent_client().stop_run(run_id, reason or "Operator stop from Claude Code")
        else:
            data = await _get_agent_client().stop_agent()
    except Exception as e:
        return _err(e)
    return f"Stop signal sent. The agent will commit progress and create a PR."


@mcp.tool()
async def kill_improvement_run() -> str:
    """
    Immediately kill the current improvement run. NO cleanup.

    Unlike stop_improvement_run, this cancels the agent task instantly
    without waiting for commits or PR creation. Use only as a last resort.

    Returns:
        Confirmation message.
    """
    try:
        data = await _get_agent_client().kill_agent()
    except Exception as e:
        return _err(e)
    run_id = data.get("run_id", "?")
    return f"Run {run_id[:12]} killed immediately. No PR was created."


# ── Run Management ───────────────────────────────────────────────────────────


@mcp.tool()
async def list_improvement_runs(limit: int = 10) -> str:
    """
    List recent self-improvement runs with status, cost, and PR links.

    Args:
        limit: Number of runs to show (default 10, max 50)

    Returns:
        Formatted list of recent runs.
    """
    try:
        runs = await _get_agent_client().list_runs()
    except Exception as e:
        return _err(e)

    if not runs:
        return "No improvement runs found."

    runs = runs[:min(limit, 50)]
    lines = [f"Improvement Runs ({len(runs)} most recent):", ""]
    for run in runs:
        lines.append(_fmt_run(run))
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def get_improvement_run(run_id: str) -> str:
    """
    Get detailed information about a specific improvement run.

    Returns full status, cost, tokens, branch, PR URL, prompt, and timing.

    Args:
        run_id: Run ID to look up

    Returns:
        Detailed run information.
    """
    try:
        run = await _get_agent_client().get_run(run_id)
    except Exception as e:
        return _err(e)
    return _fmt_run(run)


@mcp.tool()
async def get_run_tool_calls(run_id: str, limit: int = 50) -> str:
    """
    View the tool calls made by the agent during an improvement run.

    Shows what files were read, edited, what commands were run, etc.

    Args:
        run_id: Run ID to look up
        limit: Number of tool calls to show (default 50)

    Returns:
        Recent tool calls with tool name, timing, and status.
    """
    try:
        calls = await _get_agent_client().get_tool_calls(run_id, limit)
    except Exception as e:
        return _err(e)

    if not calls:
        return f"No tool calls recorded for run {run_id[:12]}."

    lines = [f"Tool Calls for run {run_id[:12]} ({len(calls)} shown):", ""]
    for tc in calls:
        tool = tc.get("tool_name", "?")
        status = tc.get("status", "?")
        ts = tc.get("ts", "")
        duration = tc.get("duration_ms")
        line = f"  [{status}] {tool}"
        if duration is not None:
            line += f" ({duration:.0f}ms)"
        if tc.get("input_preview"):
            line += f" — {tc['input_preview'][:80]}"
        lines.append(line)
    return "\n".join(lines)


@mcp.tool()
async def get_run_output(run_id: str, limit: int = 30) -> str:
    """
    View the latest LLM output and audit events from an improvement run.

    This shows the agent's thinking, text output, and key events
    (start, stop, errors, prompt injections, etc.) in reverse chronological order.

    Args:
        run_id: Run ID to look up
        limit: Number of events to show (default 30)

    Returns:
        Recent agent output and events.
    """
    try:
        entries = await _get_agent_client().get_run_audit(run_id, limit)
    except Exception as e:
        return _err(e)

    if not entries:
        return f"No audit entries for run {run_id[:12]}."

    lines = [f"Output for run {run_id[:12]} ({len(entries)} events):", ""]
    for entry in entries:
        event = entry.get("event_type", "?")
        data = entry.get("data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                data = {}

        if event == "llm_text":
            text = data.get("text", "")[:200]
            role = data.get("agent_role", "worker")
            lines.append(f"  [{role}] {text}")
        elif event == "llm_thinking":
            text = data.get("text", "")[:100]
            lines.append(f"  [thinking] {text}...")
        elif event in ("run_started", "round_complete", "ceo_continuation", "worker_assignment"):
            lines.append(f"  [{event}] {json.dumps(data, default=str)[:150]}")
        elif event in ("stop_requested", "killed", "fatal_error", "prompt_injected", "session_unlocked"):
            lines.append(f"  [{event}] {json.dumps(data, default=str)[:150]}")
        elif event == "usage":
            inp = data.get("total_input_tokens", 0)
            out = data.get("total_output_tokens", 0)
            lines.append(f"  [usage] {inp:,} in / {out:,} out")
        elif event == "pr_created":
            lines.append(f"  [PR] {data.get('url', '?')}")
        else:
            # Show other events briefly
            lines.append(f"  [{event}] {json.dumps(data, default=str)[:120]}")
    return "\n".join(lines)


@mcp.tool()
async def get_run_diff(run_id: str) -> str:
    """
    View the git diff (files changed) for an improvement run.

    Shows which files were added, modified, or removed, with line counts.

    Args:
        run_id: Run ID to look up

    Returns:
        File-level diff summary.
    """
    try:
        data = await _get_agent_client().get_run_diff(run_id)
    except Exception as e:
        return _err(e)

    files = data.get("files", [])
    if not files:
        return f"No changes in run {run_id[:12]}."

    total_add = data.get("total_added", 0)
    total_rm = data.get("total_removed", 0)
    lines = [f"Diff for run {run_id[:12]} ({len(files)} files, +{total_add}/-{total_rm}):", ""]
    for f in files:
        fname = f.get("file", f.get("path", "?"))
        added = f.get("added", 0)
        removed = f.get("removed", 0)
        lines.append(f"  {fname}  +{added}/-{removed}")
    return "\n".join(lines)


# ── Agent Control Signals ────────────────────────────────────────────────────


@mcp.tool()
async def pause_improvement_run(run_id: str) -> str:
    """
    Pause a running improvement run.

    The agent will stop processing after the current tool call completes.
    Use resume_improvement_signal to continue, or inject_agent_prompt to
    redirect the agent before resuming.

    Args:
        run_id: Run ID to pause

    Returns:
        Confirmation message.
    """
    try:
        data = await _get_agent_client().pause_run(run_id)
    except Exception as e:
        return _err(e)
    return f"Run {run_id[:12]} paused."


@mcp.tool()
async def resume_improvement_signal(run_id: str) -> str:
    """
    Resume a paused improvement run.

    Args:
        run_id: Run ID to resume

    Returns:
        Confirmation message.
    """
    try:
        data = await _get_agent_client().resume_run_signal(run_id)
    except Exception as e:
        return _err(e)
    return f"Run {run_id[:12]} resumed."


@mcp.tool()
async def inject_agent_prompt(run_id: str, message: str) -> str:
    """
    Inject a message into a running or paused improvement agent.

    This lets you redirect the agent mid-session. The message will be
    delivered to the agent as an operator instruction. If the agent is
    paused, it will resume with your message as the next task.

    Args:
        run_id: Run ID to inject into
        message: The instruction to send to the agent

    Returns:
        Confirmation message.
    """
    if not message or not message.strip():
        return "Error: Message cannot be empty."
    try:
        data = await _get_agent_client().inject_prompt(run_id, message)
    except Exception as e:
        return _err(e)
    length = data.get("prompt_length", len(message))
    return f"Message injected into run {run_id[:12]} ({length} chars)."


@mcp.tool()
async def unlock_improvement_run(run_id: str) -> str:
    """
    Unlock the session time gate for a running improvement run.

    Normally the agent is locked for a minimum duration. Unlocking lets
    the agent's end_session tool succeed immediately, allowing a clean
    early exit.

    Args:
        run_id: Run ID to unlock

    Returns:
        Confirmation message.
    """
    try:
        data = await _get_agent_client().unlock_run(run_id)
    except Exception as e:
        return _err(e)
    return f"Run {run_id[:12]} session gate unlocked. Agent can now end early."


@mcp.tool()
async def list_agent_branches() -> str:
    """
    List available git branches in the agent's repository clone.

    Useful for choosing a base_branch when starting a new improvement run.

    Returns:
        List of branch names.
    """
    try:
        branches = await _get_agent_client().list_branches()
    except Exception as e:
        return _err(e)
    if not branches:
        return "No branches found."
    return "Branches:\n" + "\n".join(f"  - {b}" for b in branches)


# ═══════════════════════════════════════════════════════════════════════════════
# Connectivity check
# ═══════════════════════════════════════════════════════════════════════════════


async def _run_check() -> bool:
    """Validate connectivity to gateway and monitor. Returns True if all pass."""
    import asyncio

    tool_count = len(mcp._tool_manager._tools)
    passed = 0
    failed = 0

    print("SignalPilot MCP — Connectivity Check")
    print("=" * 40)
    print(f"Gateway URL:  {GATEWAY_URL}")
    print(f"Monitor URL:  {MONITOR_URL}")
    print(f"API Key:      {'(set)' if API_KEY else '(none)'}")
    print(f"Tools:        {tool_count}")
    print()

    # 1. Gateway health
    try:
        data = await _get_client().health()
        status = data.get("status", "unknown")
        print(f"  [PASS] Gateway health: {status}")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] Gateway health: {e}")
        failed += 1

    # 2. List connections (also verifies auth)
    try:
        conns = await _get_client().list_connections()
        print(f"  [PASS] Gateway connections: {len(conns)} configured")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] Gateway connections: {e}")
        failed += 1

    # 3. Monitor / agent health
    try:
        data = await _get_agent_client().agent_health()
        status = data.get("status", "unknown")
        run_id = data.get("current_run_id")
        extra = f" (run {run_id[:12]})" if run_id else ""
        print(f"  [PASS] Agent health: {status}{extra}")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] Agent health: {e}")
        failed += 1

    # 4. List runs (verifies monitor DB)
    try:
        runs = await _get_agent_client().list_runs()
        print(f"  [PASS] Monitor runs: {len(runs)} in history")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] Monitor runs: {e}")
        failed += 1

    print()
    if failed == 0:
        print(f"All {passed} checks passed — ready for Claude Code!")
    else:
        print(f"{passed} passed, {failed} failed — fix the failures above.")
    return failed == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    """Run the SignalPilot remote MCP server over stdio."""
    import asyncio
    from . import __version__

    if "--version" in sys.argv:
        print(f"signalpilot-mcp {__version__}")
        return

    if "--check" in sys.argv:
        import logging
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        ok = asyncio.run(_run_check())
        sys.exit(0 if ok else 1)

    if not GATEWAY_URL or GATEWAY_URL == "http://localhost:3300":
        print(
            "Tip: Set SIGNALPILOT_URL to your gateway address. "
            "Using default: http://localhost:3300",
            file=sys.stderr,
        )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
