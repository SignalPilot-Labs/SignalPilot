"""
SignalPilot MCP Server — exposes governed sandbox + database tools.

Run with stdio transport (for Claude Code):
    python -m gateway.mcp_server

Tools exposed:
    execute_code     — Run Python code in an isolated gVisor sandbox
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
from dataclasses import dataclass

import httpx
from mcp.server.fastmcp import FastMCP

# Input validation patterns
_CONN_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9_.]{1,256}$")
_MAX_SQL_LENGTH = 100_000
_MAX_CODE_LENGTH = 1_000_000


def _quote_table(name: str) -> str:
    """Quote a table name for SQL, handling schema-qualified names like main.track."""
    parts = name.split(".")
    return ".".join('"' + p.replace('"', '""') + '"' for p in parts)


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

from contextlib import asynccontextmanager

from .engine import inject_limit, validate_sql as engine_validate_sql
from .errors import query_error_hint
from .mcp_errors import sanitize_mcp_error, sanitize_proxy_response
from .models import AuditEntry
import contextvars
from .store import list_sandboxes, Store
from .db.engine import get_session_factory

# Context variable set by MCPAuthMiddleware with the authenticated user_id
mcp_user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_user_id", default=None)
from .dbt import (
    build_project_map as _build_project_map,
    format_validation_result as _format_validation_result,
    validate_project as _validate_project,
)
from .dbt.date_spine_fixer import generate_date_spine_fixes
from .dbt.inventory import scan_project as _scan_project
from .dbt.nondeterminism_fixer import (
    build_table_columns_from_schema,
    generate_nondeterminism_fixes,
)

@asynccontextmanager
async def _store_session(user_id: str | None = None):
    """Create a Store with a managed DB session for MCP tool calls.

    If user_id is not provided, reads from the context variable set by
    MCPAuthMiddleware during key validation.
    """
    if user_id is None:
        user_id = mcp_user_id_var.get(None)
    factory = get_session_factory()
    async with factory() as session:
        yield Store(session, user_id)


def _gateway_url() -> str:
    """Get the gateway API URL for internal MCP→REST calls."""
    import os
    return os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")


import os as _os

# Allowed hosts for MCP streamable-http transport (DNS rebinding protection)
_allowed_hosts = ["localhost", "127.0.0.1", "host.docker.internal", "0.0.0.0"]
_extra_hosts = _os.environ.get("SP_MCP_ALLOWED_HOSTS", "")
if _extra_hosts:
    _allowed_hosts.extend(h.strip() for h in _extra_hosts.split(",") if h.strip())
# Include hosts with port numbers
_allowed_hosts_with_ports = list(_allowed_hosts)
for h in _allowed_hosts:
    _allowed_hosts_with_ports.append(f"{h}:3300")

mcp = FastMCP(
    "SignalPilot",
    instructions=(
        "You have access to SignalPilot, a governed sandbox for AI database access. "
        "Use execute_code to run Python in an isolated gVisor sandbox (~300ms). "
        "Use query_database for read-only SQL with automatic governance (LIMIT injection, "
        "DDL/DML blocking, audit logging). Use list_connections to see available databases."
    ),
    transport_security={
        "allowed_hosts": _allowed_hosts_with_ports,
    },
)



async def _get_sandbox_url() -> str:
    async with _store_session() as store:
        settings = await store.load_settings()
    return settings.sandbox_manager_url


# ─── Tools ───────────────────────────────────────────────────────────────────


@mcp.tool()
async def execute_code(code: str, timeout: int = 30) -> str:
    """
    Execute Python code in an isolated gVisor sandbox.

    The code runs in a secure, ephemeral gVisor sandbox with Python 3.12 and common
    stdlib modules pre-loaded (math, re, collections, datetime, etc.).
    Each execution gets a fresh sandbox that is destroyed after returning.
    Typical latency: ~300ms.

    Args:
        code: Python code to execute
        timeout: Max execution time in seconds (default 30)

    Returns:
        The stdout output from the code, or an error message.
    """
    # Cloud mode gate
    from .deployment import is_cloud_mode
    if is_cloud_mode():
        return "Error: Code execution is not available in cloud mode"

    # Input validation
    if not code or not code.strip():
        return "Error: Code cannot be empty."
    if len(code) > _MAX_CODE_LENGTH:
        return f"Error: Code exceeds maximum length ({_MAX_CODE_LENGTH} characters)."
    if timeout < 1 or timeout > 300:
        return "Error: Timeout must be between 1 and 300 seconds."

    sandbox_url = await _get_sandbox_url()

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
            return "Error: Cannot connect to sandbox manager. Is the sandbox manager running?"
        except Exception as e:
            return f"Error: Sandbox execution failed: {sanitize_mcp_error(str(e))}"

    # Log to audit
    async with _store_session() as store:
        await store.append_audit(AuditEntry(
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
        return f"Error:\n{sanitize_mcp_error(str(error))}"


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

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        # Load annotations for blocked tables (Feature #19)
        annotations = load_annotations(connection_name)
        blocked_tables = annotations.blocked_tables

        # Validate SQL (with blocked tables from annotations)
        validation = engine_validate_sql(sql, blocked_tables=blocked_tables or None)
        if not validation.ok:
            await store.append_audit(AuditEntry(
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
            await store.append_audit(AuditEntry(
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
            conn_str = await store.get_connection_string(connection_name)
            if not conn_str:
                return "Error: No credentials stored for this connection (restart gateway to reload)"

            # Use pool manager for connection reuse (MED-06 fix)
            from .connectors.pool_manager import pool_manager
            from .connectors.health_monitor import health_monitor

            extras = await store.get_credential_extras(connection_name)
            start = time.monotonic()
            try:
                async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
                    rows = await connector.execute(safe_sql)
            except Exception as e:
                elapsed_err = (time.monotonic() - start) * 1000
                health_monitor.record(connection_name, elapsed_err, False, str(e)[:200], conn_info.db_type)
                # Structured error feedback for agent self-correction (Spider2.0 SOTA pattern)
                err_str = str(e)
                hint = query_error_hint(err_str, conn_info.db_type)
                sanitized = sanitize_mcp_error(err_str, cap=300)
                return f"Query error: {sanitized}" + (f"\n\nHint: {hint}" if hint else "")

            elapsed_ms = (time.monotonic() - start) * 1000
            health_monitor.record(connection_name, elapsed_ms, True, db_type=conn_info.db_type)

            # Apply PII redaction if enabled on this connection (Feature #15)
            from .governance.pii import PIIRedactor
            pii_redactor = PIIRedactor()
            # Load rules from DB-stored PII config (toggled per-connection)
            if conn_info.pii_enabled and conn_info.pii_rules:
                for col_name, rule in conn_info.pii_rules.items():
                    pii_redactor.add_rule(col_name, rule)
            # Also load from YAML annotations (legacy/manual overrides)
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

            await store.append_audit(AuditEntry(
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

    # PII redaction notice for the LLM
    redaction_notice = ""
    if pii_redactor.last_redacted_columns:
        redacted_cols = ", ".join(pii_redactor.last_redacted_columns)
        redaction_notice = (
            f"\n\n[PII REDACTED] The following columns were redacted by policy: {redacted_cols}. "
            f"Values shown as ***** (hide), sha256:... (hash), or partially masked. "
            f"Do not attempt to reverse or infer the original values."
        )

    if not rows:
        return f"Query returned 0 rows ({', '.join(meta_parts)})" + redaction_notice

    # Format as readable table
    columns = list(rows[0].keys())
    lines = [" | ".join(str(c) for c in columns)]
    lines.append("-" * len(lines[0]))
    for row in rows[:50]:  # Cap display at 50 rows
        lines.append(" | ".join(str(row.get(c, "")) for c in columns))
    if len(rows) > 50:
        lines.append(f"... ({len(rows)} rows total, showing first 50)")

    return "\n".join(lines) + f"\n\n[{', '.join(meta_parts)}]" + redaction_notice


@mcp.tool()
async def list_database_connections() -> str:
    """
    List all configured database connections.

    Returns connection names, types, hosts, and status.
    Use the connection name with query_database to run SQL.
    """
    async with _store_session() as store:
        connections = await store.list_connections()
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

    Returns sandbox manager health and active sandbox count.
    """
    async with _store_session() as store:
        settings = await store.load_settings()
    sandbox_url = settings.sandbox_manager_url

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{sandbox_url}/health")
            health = resp.json()
    except Exception:
        return "Sandbox manager: OFFLINE (connection failed)"

    lines = [
        "Sandbox Manager: connected",
        f"Status: {health.get('status', 'unknown')}",
        f"Active Sandboxes: {health.get('active_vms', 0)} / {health.get('max_vms', 10)}",
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

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection"

        extras = await store.get_credential_extras(connection_name)

    # Check schema cache first (Feature #18)
    from .connectors.schema_cache import schema_cache

    schema = schema_cache.get(connection_name)
    if schema is None:
        from .connectors.pool_manager import pool_manager
        try:
            async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
                schema = await connector.get_schema()
        except Exception as e:
            return f"Error: Could not fetch schema: {sanitize_mcp_error(str(e))}"
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

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection"

        extras = await store.get_credential_extras(connection_name)

    from .connectors.schema_cache import schema_cache
    schema = schema_cache.get(connection_name)
    if schema is None:
        from .connectors.pool_manager import pool_manager
        try:
            async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
                schema = await connector.get_schema()
        except Exception as e:
            return f"Error: Could not fetch schema: {sanitize_mcp_error(str(e))}"
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


@dataclass
class _DateBoundaryResult:
    """Structured result from the internal date-boundary query."""

    global_max: str | None
    largest_table: str | None
    largest_table_row_count: int
    largest_table_max: str | None
    table_max: dict[str, str]
    table_row_count: dict[str, int]
    found_any: bool
    error: str | None
    # Per-table detail: {full_name: {col_name: (min, max)}}
    table_col_results: dict[str, dict[str, tuple[str | None, str | None]]]
    db_type: str


async def _fetch_date_boundaries(connection_name: str) -> _DateBoundaryResult:
    """Shared internal function that queries date column boundaries for a connection.

    Returns a structured _DateBoundaryResult. Both get_date_boundaries and
    fix_date_spine_hazards call this to avoid duplicating the query logic.

    Raises ValueError if the connection name or credentials are invalid.
    """
    from .connectors.schema_cache import schema_cache
    from .connectors.pool_manager import pool_manager

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            raise ValueError(f"Connection '{connection_name}' not found. Available: {available}")

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            raise ValueError("No credentials stored for this connection")

        extras = await store.get_credential_extras(connection_name)

    schema = schema_cache.get(connection_name)
    if schema is None:
        async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
            schema = await connector.get_schema()
        schema_cache.put(connection_name, schema)

    DATE_TYPE_KEYWORDS = ("date", "timestamp", "datetime")

    global_max: str | None = None
    table_max: dict[str, str] = {}
    table_row_count: dict[str, int] = {}
    table_col_results: dict[str, dict[str, tuple[str | None, str | None]]] = {}
    found_any = False

    for key in sorted(schema.keys()):
        table = schema[key]
        table_schema = table.get("schema", "")
        table_name = table.get("name", key)
        full_name = f"{table_schema}.{table_name}" if table_schema else table_name

        date_cols = [
            col for col in table.get("columns", [])
            if any(kw in col.get("type", "").lower() for kw in DATE_TYPE_KEYWORDS)
        ]

        if not date_cols:
            continue

        found_any = True
        col_results: dict[str, tuple[str | None, str | None]] = {}

        select_parts = []
        for col in date_cols:
            col_name = col["name"]
            safe_col_name = col_name.replace('"', '""')
            quoted = f'"{safe_col_name}"'
            select_parts.append(f'MIN({quoted}) AS "min_{safe_col_name}", MAX({quoted}) AS "max_{safe_col_name}"')

        quoted_table = _quote_table(full_name)
        sql = f'SELECT {", ".join(select_parts)} FROM {quoted_table}'

        try:
            async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
                rows = await connector.execute(sql)
                if rows:
                    row = rows[0]
                    for col in date_cols:
                        col_name = col["name"]
                        min_val = row.get(f"min_{col_name}")
                        max_val = row.get(f"max_{col_name}")
                        col_results[col_name] = (
                            str(min_val).split(" ")[0] if min_val is not None else None,
                            str(max_val).split(" ")[0] if max_val is not None else None,
                        )
                        if max_val is not None:
                            max_str = str(max_val).split(" ")[0]
                            if global_max is None or max_str > global_max:
                                global_max = max_str
                            if max_str > table_max.get(full_name, ""):
                                table_max[full_name] = max_str
                count_sql = f'SELECT COUNT(*) AS "cnt" FROM {quoted_table}'
                count_rows = await connector.execute(count_sql)
                if count_rows:
                    raw = count_rows[0].get("cnt")
                    if raw is not None:
                        table_row_count[full_name] = int(raw)
        except Exception:
            for col in date_cols:
                col_results[col["name"]] = (None, None)

        table_col_results[full_name] = col_results

    largest_table: str | None = (
        max(table_row_count, key=table_row_count.__getitem__) if table_row_count else None
    )
    largest_table_max = table_max.get(largest_table) if largest_table else None
    largest_table_row_count = table_row_count.get(largest_table, 0) if largest_table else 0

    return _DateBoundaryResult(
        global_max=global_max,
        largest_table=largest_table,
        largest_table_row_count=largest_table_row_count,
        largest_table_max=largest_table_max,
        table_max=table_max,
        table_row_count=table_row_count,
        found_any=found_any,
        error=None,
        table_col_results=table_col_results,
        db_type=conn_info.db_type,
    )


@mcp.tool()
async def get_date_boundaries(connection_name: str) -> str:
    """
    Get the MIN and MAX dates across all DATE and TIMESTAMP columns in a connection.

    Queries every table to find date column boundaries. Use the returned
    GLOBAL MAX DATE as your date spine endpoint — never use current_date,
    now(), or current_timestamp as a spine endpoint.

    Args:
        connection_name: Name of a configured database connection

    Returns:
        Formatted string with per-table MIN/MAX dates and the global MAX date.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"

    try:
        result = await _fetch_date_boundaries(connection_name)
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"

    if not result.found_any:
        return f"Date boundaries for: {connection_name} ({result.db_type})\nNo DATE or TIMESTAMP columns found in this connection."

    lines = [f"Date boundaries for: {connection_name} ({result.db_type})", ""]

    # Reconstruct per-table detail lines from structured result.
    # We need the schema object to iterate in the same order, so we re-use
    # the table_col_results that _fetch_date_boundaries already collected.
    from .connectors.schema_cache import schema_cache
    schema = schema_cache.get(connection_name) or {}

    DATE_TYPE_KEYWORDS = ("date", "timestamp", "datetime")
    for key in sorted(schema.keys()):
        table = schema[key]
        table_schema = table.get("schema", "")
        table_name = table.get("name", key)
        full_name = f"{table_schema}.{table_name}" if table_schema else table_name
        date_cols = [
            col for col in table.get("columns", [])
            if any(kw in col.get("type", "").lower() for kw in DATE_TYPE_KEYWORDS)
        ]
        if not date_cols:
            continue
        col_results = result.table_col_results.get(full_name, {})
        lines.append(f"Table: {full_name}")
        for col in date_cols:
            col_name = col["name"]
            col_type = col.get("type", "")
            if col_name not in col_results:
                lines.append(f"  {col_name} ({col_type}): (query failed)")
            else:
                min_val, max_val = col_results[col_name]
                if min_val is None and max_val is None:
                    lines.append(f"  {col_name} ({col_type}): (no data)")
                else:
                    lines.append(f"  {col_name} ({col_type}): {min_val} → {max_val}")
        lines.append("")

    if result.global_max:
        lines.append(f"GLOBAL MAX DATE: {result.global_max}")
        lines.append("")

    if result.table_max:
        lines.append("TABLE MAX DATES (use these for date spine endpoints):")
        for tbl, tbl_max in sorted(result.table_max.items()):
            count_str = (
                f"{result.table_row_count[tbl]:,} rows"
                if tbl in result.table_row_count
                else "row count unavailable"
            )
            size_marker = " (largest table)" if tbl == result.largest_table else ""
            spine_marker = (
                " ← USE THIS for spine if this is your fact/event table"
                if tbl_max != result.global_max
                else ""
            )
            lines.append(f"  {tbl} → {tbl_max} ({count_str}){size_marker}{spine_marker}")
        lines.append("")
        lines.append("RULE: Use the max date of your PRIMARY FACT TABLE (orders, events, transactions)")
        lines.append("      as the date spine endpoint. Do NOT use the global max if it comes from a")
        lines.append("      dimension or reference table with a later date.")
    else:
        lines.append("GLOBAL MAX DATE: (no non-null date values found)")

    return "\n".join(lines)


async def _find_hazard_table_date(
    connection_name: str,
    project_path: "Path",
    boundaries: _DateBoundaryResult,
) -> tuple[str, str] | None:
    """Look for pre-existing hazard model tables in the DB and return their max date.

    When the source DB contains gold-generated tables (e.g. a pre-existing
    ``shopify__calendar`` or ``int_quickbooks__general_ledger_date_spine``),
    their max date reflects the original gold generation date — the correct
    replacement for ``current_date`` in the model SQL.

    Returns (date_string, source_description) or None.
    """
    from .connectors.pool_manager import pool_manager

    project = _scan_project(project_path)
    if not project.date_hazards:
        return None

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            return None
        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return None

    # Collect model names from hazards (the tables we want to check).
    model_names = [h.get("model_name", "") for h in project.date_hazards if h.get("model_name")]
    if not model_names:
        return None

    # Also check tables whose name contains '__' (dbt derived pattern) from boundaries.
    derived_max: dict[str, tuple[str, int]] = {}  # table -> (max_date, row_count)
    if boundaries.table_col_results:
        for tbl_name, col_results in boundaries.table_col_results.items():
            short_name = tbl_name.split(".")[-1] if "." in tbl_name else tbl_name
            for _, (_, max_val) in col_results.items():
                if max_val and "__" in short_name:
                    row_count = boundaries.table_row_count.get(tbl_name, 0)
                    if max_val > derived_max.get(short_name, ("", 0))[0]:
                        derived_max[short_name] = (max_val, row_count)

    # Priority 1: check if any hazard model name exists as a table with date data.
    # Take the MAX across all date columns (e.g. date_year=2024-01-01 vs
    # period_first_day=2024-09-01 — we want the latter).
    for model_name in model_names:
        for tbl_name, col_results in (boundaries.table_col_results or {}).items():
            short_name = tbl_name.split(".")[-1] if "." in tbl_name else tbl_name
            if short_name == model_name:
                best = max(
                    (mv for _, (_, mv) in col_results.items() if mv),
                    default=None,
                )
                if best:
                    return best, f"{best} (from pre-existing table {short_name})"

    # Priority 2: use the max date from the largest derived table (name contains '__').
    if derived_max:
        best_table = max(derived_max, key=lambda k: derived_max[k][1])
        max_date, row_count = derived_max[best_table]
        return max_date, f"{max_date} (from largest derived table {best_table}, {row_count:,} rows)"

    return None


@mcp.tool()
async def fix_date_spine_hazards(
    project_dir: str,
    connection_name: str,
    replacement_date: str = "",
) -> str:
    """
    Auto-fix all date spine hazards in a dbt project in one call.

    Reads the project scan to find all current_date/current_timestamp/now() hazards,
    then creates local override files for package models and edits project models
    in-place. Uses the largest-table max date from the connection as the replacement
    literal date, or an explicit replacement_date if provided.

    Args:
        project_dir: Absolute path to the dbt project root.
        connection_name: Name of a configured database connection (used to auto-detect
                         the replacement date from the largest fact table).
        replacement_date: Optional override date string like "2022-01-31". If omitted,
                          the date is auto-detected from the connection's largest table.

    Returns:
        Markdown report listing every file created/modified and a dbt run command.
    """
    from pathlib import Path as _Path

    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"

    project_path = _Path(project_dir)
    if not project_path.exists():
        return f"Error: project directory does not exist: {project_dir}"

    # Determine the replacement date and whether to add a +1 day offset.
    # add_day_offset=True only when the date comes from raw source data (global_max),
    # where max_data_date + 1 = current_date. When the date comes from a pre-existing
    # hazard table or is provided explicitly by the caller, it already reflects the
    # correct current_date value, so no offset is needed.
    resolved_date: str
    date_source: str
    add_day_offset: bool
    if replacement_date.strip():
        resolved_date = replacement_date.strip()
        date_source = f"{resolved_date} (provided explicitly)"
        add_day_offset = False
    else:
        try:
            boundaries = await _fetch_date_boundaries(connection_name)
        except Exception as e:
            return f"Error fetching date boundaries: {sanitize_mcp_error(str(e))}"

        if not boundaries.found_any:
            return (
                f"Error: No DATE/TIMESTAMP columns found in connection '{connection_name}'. "
                "Pass replacement_date explicitly."
            )

        # Strategy: look for the hazard model(s) as pre-existing tables in the
        # DB — their max date reflects the gold generation date. This is more
        # reliable than global_max (which picks up outlier dates from raw data,
        # e.g. purchase orders dated 2050) or largest_table_max (which misses
        # derived tables that aren't the largest).
        hazard_date = await _find_hazard_table_date(
            connection_name, project_path, boundaries
        )
        if hazard_date:
            resolved_date, date_source = hazard_date
            add_day_offset = False
        elif boundaries.global_max:
            resolved_date = boundaries.global_max
            date_source = f"{resolved_date} (global max date — no hazard table found)"
            add_day_offset = True
        else:
            return (
                f"Error: Could not determine a replacement date from connection '{connection_name}'. "
                "Pass replacement_date explicitly."
            )

    # Scan the project to get hazards.
    project = _scan_project(project_path)
    hazards = project.date_hazards

    if not hazards:
        return "No date spine hazards found — nothing to fix."

    # Generate fixes (pure, no I/O).
    try:
        fixes = generate_date_spine_fixes(project_path, hazards, resolved_date, add_day_offset)
    except OSError as e:
        return f"Error reading source files: {sanitize_mcp_error(str(e))}"

    # Write files.
    written: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for fix in fixes:
        if fix.already_overridden:
            skipped.append(fix.original_path)
            continue
        try:
            fix.output_path.parent.mkdir(parents=True, exist_ok=True)
            fix.output_path.write_text(fix.content, encoding="utf-8")
            written.append(fix.output_path.name.removesuffix(".sql"))
        except OSError as e:
            errors.append(f"{fix.output_path.name}: {sanitize_mcp_error(str(e), cap=100)}")

    # Build markdown report.
    report_lines = [f"## Date spine hazards fixed ({len([f for f in fixes if not f.already_overridden])} files)", ""]

    item_num = 0
    for fix in fixes:
        if fix.already_overridden:
            report_lines.append(
                f"  SKIPPED {fix.original_path} — override already exists"
            )
            continue

        item_num += 1
        action = "CREATED" if fix.is_package else "MODIFIED"
        out_rel = str(fix.output_path.relative_to(project_path))

        # Include a short snippet: first replacement found in context.
        snippet = _extract_replacement_snippet(fix.content, resolved_date)
        snippet_str = f"\n     snippet: {snippet}" if snippet else ""

        patterns_str = ", ".join(fix.patterns_replaced) if fix.patterns_replaced else "unknown"
        if fix.is_package:
            report_lines.append(
                f"{item_num}. {action} {out_rel} (override of {fix.original_path})\n"
                f"   Replaced: {patterns_str} -> ('{resolved_date}'::date + INTERVAL '1 day'){snippet_str}"
            )
        else:
            report_lines.append(
                f"{item_num}. {action} {out_rel} (project model, edited in-place)\n"
                f"   Replaced: {patterns_str} -> ('{resolved_date}'::date + INTERVAL '1 day'){snippet_str}"
            )

    if errors:
        report_lines.append("")
        report_lines.append("## Errors")
        for err in errors:
            report_lines.append(f"  - {err}")

    if written:
        model_list = " ".join(written)
        report_lines.append("")
        report_lines.append(f"Verify: dbt run --select {model_list}")

    report_lines.append("")
    report_lines.append(f"Date used: {date_source}")

    return "\n".join(report_lines)


@mcp.tool()
async def fix_nondeterminism_hazards(
    project_dir: str,
    connection_name: str,
) -> str:
    """
    Auto-fix all non-deterministic window function hazards in a dbt project.

    Finds ROW_NUMBER/RANK/DENSE_RANK OVER(...) clauses whose ORDER BY may not be
    unique, then appends a tiebreaker column (first *_id column found in referenced
    tables) to each ambiguous ORDER BY.

    Creates local override files for package models; edits project models in-place.
    If the DB connection is unavailable, skips all fixes and returns a warning
    listing the affected models for manual review.

    Args:
        project_dir: Absolute path to the dbt project root.
        connection_name: Name of a configured database connection (used to discover
                         column names for tiebreaker selection).

    Returns:
        Markdown report listing every file fixed and a dbt run --select command.
    """
    from pathlib import Path as _Path

    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"

    project_path = _Path(project_dir)
    if not project_path.exists():
        return f"Error: project directory does not exist: {project_dir}"

    # Scan the project to get nd_warnings.
    project = _scan_project(project_path)
    nd_warnings = project.nondeterminism_warnings

    if not nd_warnings:
        return "No non-determinism hazards found — nothing to fix."

    # Fetch schema to build table->columns map (graceful degradation if unavailable).
    table_columns: dict[str, list[str]] = {}
    schema_error: str = ""

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            conn_str = None
            extras = None
        else:
            conn_str = await store.get_connection_string(connection_name)
            extras = await store.get_credential_extras(connection_name) if conn_str else None

    if not conn_info:
        schema_error = (
            f"Connection '{connection_name}' not found (available: {available}). "
            "Tiebreaker selection skipped — all patterns will need manual fixes."
        )
    else:
        if not conn_str:
            schema_error = "No credentials stored for this connection. Tiebreaker selection skipped."
        else:
            from .connectors.pool_manager import pool_manager
            from .connectors.schema_cache import schema_cache

            schema = schema_cache.get(connection_name)
            if schema is None:
                try:
                    async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
                        schema = await connector.get_schema()
                    schema_cache.put(connection_name, schema)
                except Exception as e:
                    schema_error = f"Could not fetch schema: {sanitize_mcp_error(str(e))}. Tiebreaker selection skipped."
                    schema = {}
            table_columns = build_table_columns_from_schema(schema)

    # Generate fixes (pure, no I/O).
    try:
        fixes = generate_nondeterminism_fixes(project_path, nd_warnings, table_columns)
    except OSError as e:
        return f"Error reading source files: {sanitize_mcp_error(str(e))}"

    # Write files.
    written: list[str] = []
    skipped_files: list[str] = []
    errors: list[str] = []

    for fix in fixes:
        if fix.already_overridden:
            skipped_files.append(fix.original_path)
            continue
        if not fix.content:
            # No content means nothing could be fixed (no tiebreaker, read error, etc.)
            skipped_files.append(fix.original_path)
            continue
        if not fix.fixes_applied:
            # Parsed OK but nothing needed changing.
            skipped_files.append(fix.original_path)
            continue
        try:
            fix.output_path.parent.mkdir(parents=True, exist_ok=True)
            fix.output_path.write_text(fix.content, encoding="utf-8")
            written.append(fix.output_path.name.removesuffix(".sql"))
        except OSError as e:
            errors.append(f"{fix.output_path.name}: {sanitize_mcp_error(str(e), cap=100)}")

    # Build markdown report.
    total_fixed = len([f for f in fixes if f.fixes_applied and not f.already_overridden])
    report_lines = [f"## Non-determinism hazards fixed ({total_fixed} files)", ""]

    if schema_error:
        report_lines.append(f"Warning: {schema_error}")
        report_lines.append("")

    item_num = 0
    for fix in fixes:
        if fix.already_overridden:
            report_lines.append(f"  SKIPPED {fix.original_path} — override already exists")
            continue

        if not fix.fixes_applied and not fix.skipped_patterns:
            continue

        item_num += 1
        if fix.fixes_applied:
            action = "CREATED" if fix.is_package else "MODIFIED"
            try:
                out_rel = str(fix.output_path.relative_to(project_path))
            except ValueError:
                out_rel = str(fix.output_path)
            source_note = f" (override of {fix.original_path})" if fix.is_package else " (edited in-place)"
            report_lines.append(f"{item_num}. {action} {out_rel}{source_note}")
            for applied in fix.fixes_applied:
                report_lines.append(f"   Fixed: {applied}")

        for skipped in fix.skipped_patterns:
            report_lines.append(f"   SKIPPED: {skipped}")

    if errors:
        report_lines.append("")
        report_lines.append("## Errors")
        for err in errors:
            report_lines.append(f"  - {err}")

    if written:
        model_list = " ".join(written)
        report_lines.append("")
        report_lines.append(f"Verify: dbt run --select {model_list}")

    return "\n".join(report_lines)


def _extract_replacement_snippet(content: str, replacement_date: str) -> str:
    """Return a short context snippet showing where the replacement appears."""
    needle = f"'{replacement_date}'::date"
    idx = content.find(needle)
    if idx == -1:
        return ""
    start = max(0, idx - 30)
    end = min(len(content), idx + len(needle) + 30)
    snippet = content[start:end].replace("\n", " ").strip()
    return f"...{snippet}..."


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
    Find join paths between two tables for accurate multi-table SQL generation.

    Returns the exact join columns at each hop, enabling correct JOIN construction
    without hallucinating join conditions. Essential for Spider2.0-style queries.

    Includes both explicit FK relationships AND inferred joins from column naming
    conventions (e.g., customer_id → customers.id), making this work even on
    databases without FK declarations (data lakes, Databricks, ClickHouse, etc.).

    Args:
        connection_name: Name of the database connection
        from_table: Source table (e.g., 'public.orders')
        to_table: Target table (e.g., 'public.products')
        max_hops: Maximum FK hops to search (1-6, default 4)
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    async with httpx.AsyncClient(base_url=_gateway_url(), timeout=30) as client:
        resp = await client.get(
            f"/api/connections/{connection_name}/schema/join-paths",
            params={"from_table": from_table, "to_table": to_table, "max_hops": max_hops, "include_implicit": "true"},
        )
        if resp.status_code != 200:
            return sanitize_proxy_response(resp.status_code, resp.text)
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

    async with httpx.AsyncClient(base_url=_gateway_url(), timeout=30) as client:
        resp = await client.get(
            f"/api/connections/{connection_name}/schema/relationships",
            params={"format": format},
        )
        if resp.status_code != 200:
            return sanitize_proxy_response(resp.status_code, resp.text)
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

    async with httpx.AsyncClient(base_url=_gateway_url(), timeout=30) as client:
        resp = await client.get(
            f"/api/connections/{connection_name}/schema/explore-table",
            params={"table": table_name, "include_samples": True},
        )
        if resp.status_code != 200:
            return sanitize_proxy_response(resp.status_code, resp.text)
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

    try:
        async with httpx.AsyncClient(base_url=_gateway_url(), timeout=30) as client:
            resp = await client.get(f"/api/connections/{connection_name}/schema/overview")
            if resp.status_code != 200:
                return sanitize_proxy_response(resp.status_code, resp.text)
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

    except (httpx.ConnectError, httpx.TimeoutException):
        pass

    # Fallback: use local connector when gateway is unavailable
    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection"

        extras = await store.get_credential_extras(connection_name)

    from .connectors.schema_cache import schema_cache
    from .connectors.pool_manager import pool_manager

    schema = schema_cache.get(connection_name)
    if schema is None:
        try:
            async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
                schema = await connector.get_schema()
        except Exception as e:
            return f"Error: Could not fetch schema: {sanitize_mcp_error(str(e))}"
        schema_cache.put(connection_name, schema)

    fk_map: dict[str, str] = {}
    for key, table in schema.items():
        for fk in table.get("foreign_keys", []):
            fk_map[f"{key}.{fk['column']}"] = f"{fk.get('references_table', '')}.{fk.get('references_column', '')}"

    total_rows = sum(t.get("row_count", 0) for t in schema.values())
    total_columns = sum(len(t.get("columns", [])) for t in schema.values())
    total_fks = sum(len(t.get("foreign_keys", [])) for t in schema.values())
    tables_with_fks = sum(1 for t in schema.values() if t.get("foreign_keys"))

    lines = [
        "Note: Using direct connector (gateway unavailable).",
        "",
        f"Database: {connection_name} ({conn_info.db_type})",
        f"Tables: {len(schema)}",
        f"Columns: {total_columns}",
        f"Total rows: {total_rows:,}",
        f"Foreign keys: {total_fks} across {tables_with_fks} tables",
    ]

    largest = sorted(schema.items(), key=lambda kv: kv[1].get("row_count", 0), reverse=True)[:5]
    if largest:
        lines.append("\nLargest tables:")
        for key, table in largest:
            row_count = table.get("row_count", 0)
            col_count = len(table.get("columns", []))
            fk_count = len(table.get("foreign_keys", []))
            lines.append(f"  {key}: {row_count:,} rows, {col_count} cols, {fk_count} FKs")

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
        return sanitize_proxy_response(r.status_code, r.text)

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
        return sanitize_proxy_response(r.status_code, r.text)

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
        return sanitize_proxy_response(r.status_code, r.text)

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
        return sanitize_proxy_response(r.status_code, r.text)

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
        return sanitize_proxy_response(r.status_code, r.text)

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
            parts = [f"INVALID ✗\n{sanitize_mcp_error(error_text, cap=500)}"]
            if hint:
                parts.append(f"\nSuggested fix: {hint}")
            return "\n".join(parts)
    except Exception as e:
        return f"Validation error: {sanitize_mcp_error(str(e))}"


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
        return sanitize_proxy_response(r.status_code, r.text)

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
            return sanitize_proxy_response(resp.status_code, resp.text)

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
        return f"Error exploring columns: {sanitize_mcp_error(str(e))}"


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
            return sanitize_proxy_response(resp.status_code, resp.text)

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
        return f"Error: {sanitize_mcp_error(str(e))}"


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
            return sanitize_proxy_response(resp.status_code, resp.text)

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
        return f"Error: {sanitize_mcp_error(str(e))}"


@mcp.tool()
async def estimate_query_cost(connection_name: str, sql: str) -> str:
    """
    Estimate the cost of a SQL query before executing it (dry run).

    Returns estimated rows, bytes to scan, cost in USD, and warnings.
    For BigQuery: uses native dry_run (zero cost, exact bytes estimate).
    For other databases: uses EXPLAIN to estimate row counts and cost.

    Use this BEFORE running expensive queries to avoid surprise costs.

    Args:
        connection_name: Database connection to estimate against.
        sql: SQL query to estimate cost for.
    """
    err = _validate_connection_name(connection_name)
    if err:
        return err

    if err := _validate_sql(sql):
        return f"Error: {err}"

    gw = _gateway_url()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{gw}/api/query/explain",
                json={
                    "connection_name": connection_name,
                    "sql": sql,
                    "row_limit": 1000,
                },
            )
            if resp.status_code != 200:
                return sanitize_proxy_response(resp.status_code, resp.text)
            data = resp.json()

        lines = [f"Cost Estimate for: {connection_name}", ""]
        lines.append(f"Estimated rows: {data.get('estimated_rows', 'unknown'):,}")
        lines.append(f"Estimated USD:  ${data.get('estimated_usd', 0):.6f}")
        lines.append(f"Is expensive:   {data.get('is_expensive', False)}")
        lines.append(f"Tables touched: {', '.join(data.get('tables', []))}")

        if data.get("warning"):
            lines.append(f"\n⚠️  WARNING: {data['warning']}")

        plan = data.get("plan")
        if plan:
            lines.append(f"\nQuery plan:\n{plan[:1500]}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error estimating cost: {sanitize_mcp_error(str(e))}"


@mcp.tool()
async def debug_cte_query(connection_name: str, sql: str) -> str:
    """
    ReFoRCE-style CTE debugger — break complex queries into CTEs and validate each step.

    Takes a SQL query with WITH clauses (CTEs) and executes each CTE independently
    to find where errors occur. Returns results or errors for each CTE step,
    enabling incremental debugging of complex queries.

    This implements the "CTE-Based Self-Refinement" pattern from ReFoRCE:
    parse SQL → extract CTEs → execute each → examine intermediate results.

    Args:
        connection_name: Database connection to use.
        sql: SQL query containing WITH/CTE clauses to debug.
    """
    err = _validate_connection_name(connection_name)
    if err:
        return err

    if err := _validate_sql(sql):
        return f"Error: {err}"

    # Parse CTEs from the SQL
    import re
    sql_stripped = sql.strip().rstrip(";")

    # Simple CTE extraction — handles WITH name AS (...), name2 AS (...)
    cte_pattern = re.compile(
        r'(?:WITH\s+|,\s*)(\w+)\s+AS\s*\(',
        re.IGNORECASE
    )
    cte_names = cte_pattern.findall(sql_stripped)

    if not cte_names:
        return "No CTEs found in the query. This tool works best with WITH/CTE queries.\nTip: Try rewriting your query using CTEs for easier debugging."

    lines = [f"Found {len(cte_names)} CTEs: {', '.join(cte_names)}", ""]

    gw = _gateway_url()

    # For each CTE, extract and execute it independently
    for i, cte_name in enumerate(cte_names):
        lines.append(f"--- CTE {i + 1}: {cte_name} ---")

        # Build a standalone query for this CTE:
        # Take all CTEs up to and including this one, then SELECT * FROM this_cte LIMIT 5
        try:
            # Find the CTE definition boundaries
            # Extract everything from WITH to the end of this CTE's definition
            # Use a simpler approach: just add SELECT * FROM cte_name LIMIT 5
            # after the WITH block containing all CTEs up to this one

            # Build prefix: WITH + all CTEs up to index i
            # Find each CTE boundary in the original SQL
            cte_sections = []
            remaining = sql_stripped
            # Remove leading WITH
            remaining_no_with = re.sub(r'^\s*WITH\s+', '', remaining, flags=re.IGNORECASE)

            # Simple approach: for each CTE up to i, extract by matching parentheses
            # This is a simplified parser; won't handle all edge cases
            test_sql = f"WITH {remaining_no_with.split('SELECT', 1)[0].rstrip().rstrip(',')} SELECT * FROM {cte_name} LIMIT 5"

            # Alternative: ask gateway to run it
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{gw}/api/query",
                    json={
                        "connection_name": connection_name,
                        "sql": test_sql,
                        "row_limit": 5,
                    },
                )
            if resp.status_code == 200:
                data = resp.json()
                rows = data.get("rows", [])
                cols = data.get("columns", [])
                lines.append(f"OK ✓ — {data.get('row_count', 0)} rows, {len(cols)} columns")
                if cols:
                    lines.append(f"Columns: {', '.join(cols)}")
                if rows and len(rows) > 0:
                    # Show first row as preview
                    preview = str(rows[0])[:200]
                    lines.append(f"Sample: {preview}")
            else:
                error_text = resp.text[:300]
                lines.append(f"ERROR ✗: {sanitize_mcp_error(error_text, cap=300)}")
                # Get hint
                try:
                    async with httpx.AsyncClient(timeout=5) as client2:
                        r2 = await client2.get(f"{gw}/api/connections/{connection_name}")
                        if r2.status_code == 200:
                            db_type = r2.json().get("db_type", "")
                            hint = query_error_hint(error_text, db_type)
                            if hint:
                                lines.append(f"Fix: {hint}")
                except Exception:
                    pass

        except Exception as e:
            lines.append(f"ERROR: {sanitize_mcp_error(str(e))}")

        lines.append("")

    # Also try the full query
    lines.append("--- Full Query ---")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{gw}/api/query",
                json={
                    "connection_name": connection_name,
                    "sql": sql,
                    "row_limit": 5,
                },
            )
        if resp.status_code == 200:
            data = resp.json()
            lines.append(f"OK ✓ — {data.get('row_count', 0)} rows returned")
        else:
            lines.append(f"ERROR ✗: {sanitize_mcp_error(resp.text[:300], cap=300)}")
    except Exception as e:
        lines.append(f"ERROR: {sanitize_mcp_error(str(e))}")

    return "\n".join(lines)


@mcp.tool()
async def check_model_schema(connection_name: str, model_name: str, yml_columns: str) -> str:
    """
    Compare actual DuckDB table columns against an expected YML column list.

    Identifies missing columns, extra columns, and case mismatches between
    the materialized table and the schema defined in your dbt YML file.

    Args:
        connection_name: Name of a configured database connection
        model_name: Name of the dbt model / table to inspect
        yml_columns: Comma-separated list of column names from the YML schema

    Returns:
        Formatted schema comparison report, or an error message.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if not model_name or not _MODEL_NAME_RE.match(model_name):
        return f"Error: Invalid model name '{model_name}'. Use only letters, numbers, underscores, dots (1-256 chars)."
    if not yml_columns or not yml_columns.strip():
        return "Error: yml_columns cannot be empty."

    expected: list[str] = [c.strip() for c in yml_columns.split(",") if c.strip()]
    if not expected:
        return "Error: No column names found in yml_columns."

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection"

        extras = await store.get_credential_extras(connection_name)

    from .connectors.pool_manager import pool_manager

    try:
        async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
            rows = await connector.execute(f"PRAGMA table_info('{model_name}')")
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"

    if not rows:
        return f"Error: Model '{model_name}' not found in database. Has it been materialized yet?"

    actual: list[str] = [row.get("name", "") for row in rows if row.get("name")]

    expected_lower = {c.lower(): c for c in expected}
    actual_lower = {c.lower(): c for c in actual}

    matching = [c for c in expected if c in actual]
    missing = [c for c in expected if c not in actual]
    extra = [c for c in actual if c not in expected]
    case_mismatches = [
        f"{expected_lower[k]} (expected) vs {actual_lower[k]} (actual)"
        for k in expected_lower
        if k in actual_lower and expected_lower[k] != actual_lower[k]
    ]

    def _fmt(items: list[str]) -> str:
        return ", ".join(items) if items else "(none)"

    lines = [
        f"Schema check for '{model_name}':",
        f"  Expected: {len(expected)} columns | Actual: {len(actual)} columns",
        f"  [OK] Matching: {_fmt(matching)}",
        f"  [X] Missing: {_fmt(missing)}",
        f"  [X] Extra: {_fmt(extra)}",
        f"  [!] Case mismatch: {_fmt(case_mismatches)}",
    ]
    return "\n".join(lines)


@mcp.tool()
async def dbt_error_parser(error_output: str) -> str:
    """
    Parse raw dbt stderr/stdout and extract structured, actionable error info.

    No LLM involved — pure regex and string pattern matching against common
    dbt error formats. Provides a suggested fix for known error categories.

    Args:
        error_output: Raw dbt command output (stderr or combined stdout/stderr)

    Returns:
        Structured error summary with model name, type, location, message, and suggested fix.
    """
    from .deployment import is_cloud_mode
    if is_cloud_mode():
        return "Error: dbt error parsing is not available in cloud mode"
    if not error_output or not error_output.strip():
        return "Error: error_output cannot be empty."

    model_match = (
        re.search(r'model\s+"[^.]+\.[^.]+\.([^"]+)"', error_output)
        or re.search(r'(?:Compilation|Database|Runtime|Test)\s+Error\s+in\s+model\s+(\S+)', error_output)
    )
    model_name = model_match.group(1) if model_match else "(not detected)"

    type_match = re.search(r'(Compilation Error|Database Error|Runtime Error|Test Error|dbt\.exceptions\.\w+)', error_output)
    error_type = type_match.group(1) if type_match else "(not detected)"

    location_match = (
        re.search(r'at \[(\d+):(\d+)\]', error_output)
        or re.search(r'[Ll]ine\s+(\d+)', error_output)
    )
    if location_match:
        location = f"line {location_match.group(1)}" if len(location_match.groups()) == 1 else f"line {location_match.group(1)}, col {location_match.group(2)}"
    else:
        location = "(not detected)"

    msg_match = re.search(r'(?:ERROR|error):\s+(.+)', error_output)
    core_message = msg_match.group(1).strip() if msg_match else "(not detected)"

    error_lower = error_output.lower()
    col_missing = re.search(r'column "?([^"\s]+)"? does not exist', error_output, re.IGNORECASE)
    table_missing = re.search(r'(?:table|relation)\s+"?([^"\s]+)"?\s+does not exist', error_output, re.IGNORECASE)

    if col_missing:
        col = col_missing.group(1)
        suggested_fix = f"Check column name {col} in your SELECT. Use check_model_schema to compare actual vs expected columns."
    elif table_missing:
        tbl = table_missing.group(1)
        suggested_fix = f"Model {tbl} has not been materialized. Run `dbt run --select {tbl}` first."
    elif "syntax error" in error_lower:
        suggested_fix = "Review the SQL at the indicated line number."
    elif "ambiguous column" in error_lower:
        suggested_fix = "Qualify the column with a table alias."
    elif "divide by zero" in error_lower or "division by zero" in error_lower:
        suggested_fix = "Wrap denominator in NULLIF(denominator, 0)."
    elif "unique constraint" in error_lower:
        suggested_fix = "Deduplicate source data or add a ROW_NUMBER() window to resolve duplicates."
    else:
        suggested_fix = "Review the error message above."

    lines = [
        "dbt Error Summary:",
        f"  Model: {model_name}",
        f"  Type: {error_type}",
        f"  Location: {location}",
        f"  Message: {core_message}",
        f"  Suggested fix: {suggested_fix}",
    ]
    return "\n".join(lines)


@mcp.tool()
async def generate_sql_skeleton(model_name: str, yml_columns: str, ref_tables: str = "") -> str:
    """
    Generate a dbt SQL template from a YML column spec.

    Produces a properly structured Jinja SQL file with config block, source
    CTEs using {{ ref() }}, and a final CTE listing all expected output columns
    as null placeholders. Helps agents start from the correct shape.

    Args:
        model_name: Name of the dbt model being scaffolded
        yml_columns: Comma-separated list of expected output column names
        ref_tables: Optional comma-separated list of upstream ref() table names

    Returns:
        A dbt-compatible SQL skeleton string.
    """
    if not model_name or not _MODEL_NAME_RE.match(model_name):
        return f"Error: Invalid model name '{model_name}'. Use only letters, numbers, underscores, dots (1-256 chars)."
    if not yml_columns or not yml_columns.strip():
        return "Error: yml_columns cannot be empty."

    columns: list[str] = [c.strip() for c in yml_columns.split(",") if c.strip()]
    if not columns:
        return "Error: No column names found in yml_columns."

    refs: list[str] = [t.strip() for t in ref_tables.split(",") if t.strip()] if ref_tables else []

    col_lines = "\n".join(f"        null as {col}," for col in columns)
    # Remove trailing comma from last column line
    col_lines = col_lines.rstrip(",")

    config_block = "{{\n    config(\n        materialized='table'\n    )\n}}"

    if refs:
        cte_blocks = []
        for ref_table in refs:
            cte_blocks.append(
                f"{ref_table} as (\n\n    select * from {{{{ ref('{ref_table}') }}}}\n\n)"
            )
        source_ctes = ",\n\n".join(cte_blocks)
        from_clause = refs[0]
    else:
        source_ctes = "source as (\n\n    -- TODO: replace SOURCE_TABLE\n    select * from {{{{ ref('SOURCE_TABLE') }}}}\n\n)"
        from_clause = "source"

    sql = (
        f"{config_block}\n\n"
        f"with\n\n"
        f"{source_ctes},\n\n"
        f"final as (\n\n"
        f"    select\n\n"
        f"        -- TODO: fill in transformations\n"
        f"{col_lines}\n\n"
        f"    from {from_clause}\n\n"
        f")\n\n"
        f"select * from final"
    )
    return sql


@mcp.tool()
async def analyze_grain(connection_name: str, table_name: str, candidate_keys: str = "") -> str:
    """
    Analyze the cardinality and grain of a table.

    Helps agents understand if a model is fan-outing or has duplicates by
    checking row counts and distinctness of candidate key columns.

    Args:
        connection_name: Name of a configured database connection
        table_name: Name of the table to analyze
        candidate_keys: Optional comma-separated column names to test as grain keys

    Returns:
        Formatted grain analysis report, or an error message.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if not table_name or not _MODEL_NAME_RE.match(table_name):
        return f"Error: Invalid table name '{table_name}'. Use only letters, numbers, underscores, dots (1-256 chars)."

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection"

        extras = await store.get_credential_extras(connection_name)

    from .connectors.pool_manager import pool_manager

    try:
        async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
            count_rows = await connector.execute(f'SELECT COUNT(*) as total_rows FROM {_quote_table(table_name)}')
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"

    total_rows: int = count_rows[0].get("total_rows", 0) if count_rows else 0

    _SAFE_COL_RE = re.compile(r"^[a-zA-Z0-9_]{1,128}$")
    if candidate_keys:
        keys: list[str] = [k.strip() for k in candidate_keys.split(",") if k.strip()]
        invalid_keys = [k for k in keys if not _SAFE_COL_RE.match(k)]
        if invalid_keys:
            return f"Error: Invalid candidate key name(s): {', '.join(invalid_keys)}"
    else:
        try:
            async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
                pragma_rows = await connector.execute(f"PRAGMA table_info('{table_name}')")
        except Exception as e:
            return f"Error fetching schema: {sanitize_mcp_error(str(e))}"
        id_cols = [
            r.get("name", "")
            for r in pragma_rows
            if r.get("name", "").lower() == "id" or r.get("name", "").lower().endswith("_id")
        ]
        keys = id_cols[:5]

    lines = [
        f"Grain analysis for '{table_name}':",
        f"  Total rows: {total_rows:,}",
        "  Candidate key check:",
    ]

    unique_keys: list[str] = []
    if keys:
        try:
            async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
                for key in keys:
                    try:
                        safe_key = key.replace('"', '""')
                        dist_rows = await connector.execute(f'SELECT COUNT(DISTINCT "{safe_key}") as distinct_count FROM {_quote_table(table_name)}')
                        distinct_count: int = dist_rows[0].get("distinct_count", 0) if dist_rows else 0
                        if distinct_count == total_rows:
                            lines.append(f"    {key}: {distinct_count:,} distinct (UNIQUE - this is likely the grain)")
                            unique_keys.append(key)
                        else:
                            fan_out = total_rows / distinct_count if distinct_count > 0 else 0
                            lines.append(f"    {key}: {distinct_count:,} distinct (NOT unique - fan-out factor ~{fan_out:.1f}x)")
                    except Exception as e:
                        lines.append(f"    {key}: error checking distinctness ({sanitize_mcp_error(str(e), cap=100)})")
        except Exception as e:
            lines.append(f"    error opening connection: {sanitize_mcp_error(str(e), cap=100)}")

    if not keys:
        lines.append("    (no candidate keys found or provided)")

    if unique_keys:
        lines.append(f"  Recommendation: {unique_keys[0]} appears to be the grain key.")
    else:
        lines.append("  Recommendation: No unique key found among candidates. Consider adding a surrogate key.")

    return "\n".join(lines)


@mcp.tool()
async def validate_model_output(
    connection_name: str,
    model_name: str,
    source_table: str = "",
    expected_row_count: int = 0,
) -> str:
    """
    Post-build row count validation for a dbt model.

    Detects fan-outs, empty models, and optional row count mismatches
    by comparing the model's row count against a source table or an
    expected value.

    Args:
        connection_name: Name of a configured database connection
        model_name: Name of the materialized dbt model to validate
        source_table: Optional upstream source table to compare row counts against
        expected_row_count: Optional expected row count (0 means skip check)

    Returns:
        Formatted validation report, or an error message.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if not model_name or not _MODEL_NAME_RE.match(model_name):
        return f"Error: Invalid model name '{model_name}'. Use only letters, numbers, underscores, dots (1-256 chars)."

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection"

        extras = await store.get_credential_extras(connection_name)

    from .connectors.pool_manager import pool_manager

    try:
        async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
            model_rows_result = await connector.execute(f'SELECT COUNT(*) as row_count FROM {_quote_table(model_name)}')
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"

    model_rows: int = model_rows_result[0].get("row_count", 0) if model_rows_result else 0

    source_rows: int | None = None
    source_error: str | None = None
    if source_table:
        if not _MODEL_NAME_RE.match(source_table):
            return f"Error: Invalid source_table name '{source_table}'."
        try:
            async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
                src_result = await connector.execute(f'SELECT COUNT(*) as row_count FROM {_quote_table(source_table)}')
            source_rows = src_result[0].get("row_count", 0) if src_result else 0
        except Exception as e:
            source_error = sanitize_mcp_error(str(e))

    lines = [
        f"Model output validation: '{model_name}'",
        f"  Row count: {model_rows:,}",
    ]

    if model_rows == 0:
        lines.append("  WARNING: Model returned 0 rows.")

    if source_table:
        if source_error:
            lines.append(f"  Source '{source_table}': error fetching row count ({source_error})")
        elif source_rows is not None:
            lines.append(f"  Source '{source_table}': {source_rows:,} rows")
            if source_rows > 0:
                ratio = model_rows / source_rows
                if ratio < 0.5:
                    warning = "WARNING: Model has significantly fewer rows than source -- possible data loss or over-filtering."
                elif ratio > 2.0:
                    warning = "WARNING: Fan-out detected -- model has more rows than source. Check for unintended cross-joins."
                else:
                    warning = "OK - no fan-out detected"
                lines.append(f"  Fan-out ratio: {ratio:.2f}x ({warning})")
            else:
                lines.append("  Fan-out ratio: N/A (source has 0 rows)")

    if expected_row_count > 0:
        match_label = "MATCH" if model_rows == expected_row_count else "MISMATCH"
        lines.append(f"  Expected row count: {expected_row_count:,} - {match_label}")

    return "\n".join(lines)


@mcp.tool()
async def audit_model_sources(
    connection_name: str,
    model_name: str,
    source_tables: str,
    sample_nulls: bool = True,
) -> str:
    """
    Single-call cardinality audit for a materialized dbt model and its sources.

    Queries all upstream source tables and the model itself, computes row count
    ratios (fan-out / over-filter detection), and optionally scans every output
    column for NULL fraction and constant-value patterns.

    Args:
        connection_name: Name of a configured database connection
        model_name: Name of the materialized dbt model to audit
        source_tables: Comma-separated list of upstream source/staging tables (1-10)
        sample_nulls: If True, run NULL-fraction and constant-value scan on output columns

    Returns:
        Formatted diagnostic report, or an error message.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if not model_name or not _MODEL_NAME_RE.match(model_name):
        return f"Error: Invalid model name '{model_name}'. Use only letters, numbers, underscores, dots (1-256 chars)."
    if not source_tables or not source_tables.strip():
        return "Error: source_tables cannot be empty. Provide at least one upstream table name."

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection"

        extras = await store.get_credential_extras(connection_name)

    from .connectors.pool_manager import pool_manager

    # Step 1: Get model row count.
    try:
        async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
            model_result = await connector.execute(f'SELECT COUNT(*) as row_count FROM {_quote_table(model_name)}')
    except Exception as e:
        return f"Error: could not query model '{model_name}': {sanitize_mcp_error(str(e))}"

    model_rows: int = model_result[0].get("row_count", 0) if model_result else 0

    # Step 2: Parse and validate source table names.
    raw_sources = [s.strip() for s in source_tables.split(",") if s.strip()]
    if len(raw_sources) > 10:
        raw_sources = raw_sources[:10]

    # Step 3: Query each source table, compute ratio, classify.
    source_lines: list[str] = []
    diagnosis_lines: list[str] = []

    for src in raw_sources:
        if not _MODEL_NAME_RE.match(src):
            source_lines.append(f"  {src}:  ERROR: invalid table name (skipped)")
            continue
        try:
            async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
                src_result = await connector.execute(f'SELECT COUNT(*) as row_count FROM {_quote_table(src)}')
            src_rows: int = src_result[0].get("row_count", 0) if src_result else 0
        except Exception as e:
            source_lines.append(f"  {src}:  ERROR: {sanitize_mcp_error(str(e), cap=100)}")
            continue

        if src_rows == 0:
            ratio_str = "N/A"
            classification = "WARNING: source has 0 rows"
            diagnosis_lines.append(f"  - {src} has 0 rows: source table may be empty or not yet built")
        else:
            ratio = model_rows / src_rows
            ratio_str = f"{ratio:.2f}x"
            if ratio < 0.5:
                classification = "WARNING: OVER-FILTER — fewer model rows than source (check LEFT vs INNER JOIN or WHERE clause)"
                diagnosis_lines.append(
                    f"  - {src} ratio {ratio_str}: check if INNER JOIN should be LEFT JOIN, or remove over-restrictive WHERE"
                )
            elif ratio > 2.0:
                classification = "WARNING: FAN-OUT — model has more rows than source (check for missing pre-aggregation or cross-join)"
                diagnosis_lines.append(
                    f"  - {src} ratio {ratio_str}: pre-aggregate or deduplicate {src} before joining; check join key uniqueness"
                )
            else:
                classification = "OK"

        label = src.ljust(20)
        source_lines.append(f"  {label} {src_rows:>10,} rows  → ratio {ratio_str:<8} {classification}")

    # Step 4: NULL-fraction and constant-value scan on output columns.
    col_scan_lines: list[str] = []
    col_scan_header = ""

    if sample_nulls and model_rows > 0:
        _SAFE_COL_RE = re.compile(r"^[a-zA-Z0-9_]{1,128}$")
        try:
            async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
                pragma_rows = await connector.execute(f"PRAGMA table_info('{model_name}')")
            all_cols = [r.get("name", "") for r in pragma_rows if r.get("name")]
            total_col_count = len(all_cols)
            cols = all_cols[:20]

            if total_col_count > 20:
                col_scan_header = f"Column scan (showing first 20 of {total_col_count} cols):"
            else:
                col_scan_header = f"Column scan ({len(cols)} cols):"

            for col in cols:
                if not _SAFE_COL_RE.match(col):
                    col_scan_lines.append(f"  [--] {col}: skipped (unsafe column name)")
                    continue
                try:
                    async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
                        col_result = await connector.execute(
                            f'SELECT COUNT(*) FILTER (WHERE "{col}" IS NULL) as nulls, '
                            f'COUNT(DISTINCT "{col}") as dist '
                            f'FROM {_quote_table(model_name)}'
                        )
                    null_count: int = col_result[0].get("nulls", 0) if col_result else 0
                    dist_count: int = col_result[0].get("dist", 0) if col_result else 0
                    null_frac = null_count / model_rows if model_rows > 0 else 0.0

                    col_label = col.ljust(24)
                    if dist_count == 1:
                        col_scan_lines.append(
                            f"  [!!] {col_label}  {dist_count:>8,} distinct — CONSTANT: all rows same value (check CASE WHEN literal or SELECT alias)"
                        )
                        diagnosis_lines.append(
                            f"  - {col} CONSTANT: verify CASE WHEN literals match source values (run SELECT DISTINCT on source col)"
                        )
                    elif null_frac > 0.5:
                        pct = null_frac * 100
                        col_scan_lines.append(
                            f"  [!!] {col_label}  {null_count:>8,} nulls ({pct:.1f}%) — LEFT JOIN may be dropping values; use COALESCE or fix join key"
                        )
                        diagnosis_lines.append(
                            f"  - {col} {pct:.0f}% null: verify join key is correct; consider COALESCE({col}, 0) if nulls are valid zeros"
                        )
                    else:
                        col_scan_lines.append(
                            f"  [OK]  {col_label}  {dist_count:>8,} distinct, {null_count:,} nulls"
                        )
                except Exception as e:
                    col_scan_lines.append(f"  [--] {col}: error ({sanitize_mcp_error(str(e), cap=100)})")

        except Exception:
            col_scan_header = "Column scan: unavailable (PRAGMA table_info failed)"

    elif sample_nulls and model_rows == 0:
        col_scan_header = "Column scan: skipped (model has 0 rows)"

    # Step 5: Assemble report.
    report_lines: list[str] = [
        f"Source audit for model '{model_name}' ({model_rows:,} rows):",
        "",
        "Sources:",
    ]
    report_lines.extend(source_lines)

    if col_scan_header:
        report_lines.append("")
        report_lines.append(col_scan_header)
        report_lines.extend(col_scan_lines)

    if diagnosis_lines:
        report_lines.append("")
        report_lines.append("Diagnosis:")
        report_lines.extend(diagnosis_lines)

    return "\n".join(report_lines)


@mcp.tool()
async def compare_join_types(
    connection_name: str,
    left_table: str,
    right_table: str,
    join_keys: str,
    where_clause: str = "",
) -> str:
    """
    Compare row counts across different JOIN types between two tables.

    Shows what INNER JOIN, LEFT JOIN, RIGHT JOIN, and FULL OUTER JOIN would produce,
    helping you choose the correct JOIN type for your model. Also shows how many
    rows from each side have no match in the other table.

    Args:
        connection_name: Name of a configured database connection
        left_table: Left table name (can be schema.table or just table)
        right_table: Right table name (can be schema.table or just table)
        join_keys: Comma-separated join key pairs, e.g. "a.id = b.id, a.date = b.date"
        where_clause: Optional WHERE clause (without the WHERE keyword)

    Returns:
        Formatted report showing row counts for each JOIN type and match analysis.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if not left_table or not _MODEL_NAME_RE.match(left_table):
        return f"Error: Invalid left_table name '{left_table}'. Use only letters, numbers, underscores, dots (1-256 chars)."
    if not right_table or not _MODEL_NAME_RE.match(right_table):
        return f"Error: Invalid right_table name '{right_table}'. Use only letters, numbers, underscores, dots (1-256 chars)."
    if not join_keys or not join_keys.strip():
        return "Error: join_keys cannot be empty. Provide at least one join key pair, e.g. \"a.id = b.id\"."
    if err := _validate_sql(join_keys):
        return f"Error: {err}"
    if where_clause and where_clause.strip():
        if err := _validate_sql(where_clause):
            return f"Error: {err}"

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection"

        extras = await store.get_credential_extras(connection_name)

    from .connectors.pool_manager import pool_manager

    # Extract left and right columns from the first join key for NULL detection.
    # join_keys like "a.id = b.id" — extract "a.id" and "b.id"
    first_key = join_keys.split(",")[0].strip()
    parts = first_key.split("=")
    if len(parts) != 2:
        return "Error: join_keys must be in format 'a.col = b.col'. Could not parse left/right columns."
    left_col = parts[0].strip()
    right_col = parts[1].strip()

    where_part = f"WHERE {where_clause}" if where_clause and where_clause.strip() else ""

    _qt_left = _quote_table(left_table)
    _qt_right = _quote_table(right_table)

    sql = f"""
WITH
left_count AS (SELECT COUNT(*) AS cnt FROM {_qt_left}),
right_count AS (SELECT COUNT(*) AS cnt FROM {_qt_right}),
inner_join AS (
    SELECT COUNT(*) AS cnt
    FROM {_qt_left} a
    INNER JOIN {_qt_right} b ON {join_keys}
    {where_part}
),
left_join AS (
    SELECT COUNT(*) AS cnt,
           COUNT({right_col}) AS matched,
           COUNT(*) - COUNT({right_col}) AS unmatched
    FROM {_qt_left} a
    LEFT JOIN {_qt_right} b ON {join_keys}
    {where_part}
),
right_join AS (
    SELECT COUNT(*) AS cnt,
           COUNT({left_col}) AS matched,
           COUNT(*) - COUNT({left_col}) AS unmatched
    FROM {_qt_left} a
    RIGHT JOIN {_qt_right} b ON {join_keys}
    {where_part}
),
full_join AS (
    SELECT COUNT(*) AS cnt
    FROM {_qt_left} a
    FULL OUTER JOIN {_qt_right} b ON {join_keys}
    {where_part}
)
SELECT
    (SELECT cnt FROM left_count) AS left_rows,
    (SELECT cnt FROM right_count) AS right_rows,
    (SELECT cnt FROM inner_join) AS inner_rows,
    (SELECT cnt FROM left_join) AS left_join_rows,
    (SELECT matched FROM left_join) AS left_matched,
    (SELECT unmatched FROM left_join) AS left_unmatched,
    (SELECT cnt FROM right_join) AS right_join_rows,
    (SELECT matched FROM right_join) AS right_matched,
    (SELECT unmatched FROM right_join) AS right_unmatched,
    (SELECT cnt FROM full_join) AS full_join_rows
"""

    try:
        async with pool_manager.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
            result = await connector.execute(sql)
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"

    if not result:
        return "Error: Query returned no results."

    row = result[0]
    left_rows: int = row.get("left_rows", 0)
    right_rows: int = row.get("right_rows", 0)
    inner_rows: int = row.get("inner_rows", 0)
    left_join_rows: int = row.get("left_join_rows", 0)
    left_unmatched: int = row.get("left_unmatched", 0)
    right_join_rows: int = row.get("right_join_rows", 0)
    right_unmatched: int = row.get("right_unmatched", 0)
    full_join_rows: int = row.get("full_join_rows", 0)

    lines = [
        f"JOIN Impact Analysis: {left_table} × {right_table}",
        f"  ON {join_keys}",
        "",
        "Source Tables:",
        f"  {left_table}: {left_rows:,} rows",
        f"  {right_table}: {right_rows:,} rows",
        "",
        "JOIN Results:",
        f"  INNER JOIN:      {inner_rows:,} rows",
        f"  LEFT JOIN:       {left_join_rows:,} rows  ({left_unmatched:,} left rows have no match)",
        f"  RIGHT JOIN:      {right_join_rows:,} rows  ({right_unmatched:,} right rows have no match)",
        f"  FULL OUTER JOIN: {full_join_rows:,} rows",
    ]

    if inner_rows < left_join_rows:
        lines.append("")
        lines.append(f"⚠ INNER JOIN drops {left_join_rows - inner_rows:,} rows from {left_table} that have no match in {right_table}.")
        lines.append(f"  Use LEFT JOIN to preserve all {left_table} rows.")

    if inner_rows > left_rows or inner_rows > right_rows:
        lines.append("")
        lines.append(f"⚠ FAN-OUT detected: INNER JOIN ({inner_rows:,}) > source rows. Join keys are not unique — duplicates in one table multiply rows in the other.")

    if left_join_rows == inner_rows:
        lines.append("")
        lines.append(f"✓ All {left_table} rows match — LEFT JOIN and INNER JOIN produce the same result.")

    return "\n".join(lines)


# ─── dbt project discovery + validation ─────────────────────────────────────


@mcp.tool()
async def dbt_project_map(
    project_dir: str,
    focus: str = "all",
    max_models_per_section: int = 40,
    include_columns: bool = False,
) -> str:
    """
    Yml-direct dbt project discovery — fast, comprehensive, broken-project safe.

    Scans a dbt project directory and returns a compact, LLM-optimized markdown
    view of every model (complete, stub, missing, or orphan), every source,
    every macro, plus a topologically-sorted work order for actionable models.

    Unlike `dbt parse`, this tool DOES NOT depend on dbt itself — it reads yml
    files and sql files directly with PyYAML and regex. That means it works on
    broken projects, projects with missing packages, projects with no profile,
    and projects where dbt parse would refuse to run. Critically, it surfaces
    missing-model yml entries that `dbt parse` silently drops as "orphan
    patches" — the exact thing the agent needs to find.

    Args:
        project_dir: absolute path to the dbt project root (where dbt_project.yml lives)
        focus: which view to render. One of:
            - "all" (default): full project overview grouped by directory
            - "work_order": just the actionable models in build order, with deps + columns
            - "missing": only models defined in yml but with no .sql file
            - "stubs": only sql files classified as incomplete/stubbed
            - "sources": source namespaces with their tables
            - "macros": available custom macros grouped by file
            - "model:<name>": deep-dive on one model (columns, deps, tests, description)
        max_models_per_section: per-section truncation threshold (default 40)
        include_columns: include column lists inline for complete models (default off)

    Returns:
        markdown-formatted project map
    """
    import asyncio

    from .deployment import is_cloud_mode
    if is_cloud_mode():
        return "Error: dbt project map is not available in cloud mode"
    if not project_dir or not project_dir.strip():
        return "Error: project_dir is required"
    # Offload the sync scan + render to a worker thread so the MCP event loop
    # stays responsive on large projects.
    return await asyncio.to_thread(
        _build_project_map,
        project_dir.strip(),
        focus,
        max_models_per_section,
        include_columns,
    )


@mcp.tool()
async def dbt_project_validate(
    project_dir: str,
    timeout: int = 60,
) -> str:
    """
    Run `dbt parse` against a project and surface structural errors + warnings.

    This is the pre-build validation step — does the project compile? Use it
    when the agent suspects a problem (after editing yml files, after adding
    new models, before running `dbt run`). Much cheaper than `dbt run` because
    it does not execute any SQL, but catches the same class of Jinja / ref /
    source / yml-syntax errors that would fail a run.

    Output includes:
      - success/failure + degradation mode (profile_missing, packages_missing,
        parse_failed, dbt_not_installed, timeout, etc.)
      - error list with context
      - orphan-patch list (yml-defined models with no .sql file — the "missing
        models" that `dbt_project_map` surfaces via the yml-direct path)
      - non-orphan warnings

    Args:
        project_dir: absolute path to the dbt project root
        timeout: subprocess timeout in seconds (default 60, clamped to 1-300)

    Returns:
        markdown-formatted validation report
    """
    import asyncio
    from pathlib import Path as _Path

    from .deployment import is_cloud_mode
    if is_cloud_mode():
        return "Error: dbt project validation is not available in cloud mode"
    if not project_dir or not project_dir.strip():
        return "Error: project_dir is required"

    clean_dir = project_dir.strip()

    # Require absolute path to prevent relative path confusion.
    if not _Path(clean_dir).is_absolute():
        return "Error: project_dir must be an absolute path"

    # Reject path traversal — check resolved path for .. segments.
    try:
        resolved = _Path(clean_dir).resolve()
    except (ValueError, OSError) as exc:
        return f"Error: invalid project_dir: {exc}"

    # Reject if any part of the original (unresolved) path contains .. segments.
    if ".." in _Path(clean_dir).parts:
        return "Error: project_dir must not contain '..' segments"

    # Clamp timeout to a safe range: minimum 1s, maximum 300s (5 minutes).
    clamped_timeout = max(1, min(timeout, 300))

    # _validate_project calls subprocess.run, which would block this handler's
    # event loop and can stall MCP heartbeats on Windows. Offload to a thread.
    result = await asyncio.to_thread(
        _validate_project,
        str(resolved),
        clamped_timeout,
    )
    return _format_validation_result(result)


# ─── Project management tools ────────────────────────────────────────────────


@mcp.tool()
async def create_project(name: str, connection_name: str) -> str:
    """Create a new dbt project wired to an existing connection."""
    from .models import ProjectCreate, ProjectSource
    from . import project_store

    try:
        proj = ProjectCreate(
            name=name,
            connection_name=connection_name,
            source=ProjectSource.new,
        )
        info = project_store.create_project(proj)
    except ValueError as e:
        return f"Error: {sanitize_mcp_error(str(e))}"
    return (
        f"Created project '{info.name}' at {info.project_dir}\n"
        f"  connection: {info.connection_name}\n"
        f"  db_type: {info.db_type}\n"
        f"  storage: {info.storage.value}"
    )


@mcp.tool()
async def list_projects() -> str:
    """List all configured dbt projects."""
    from . import project_store

    projects = project_store.list_projects()
    if not projects:
        return "No projects configured."
    lines = [f"Found {len(projects)} project(s):\n"]
    for p in projects:
        lines.append(
            f"  - {p.name}  ({p.db_type}, {p.status.value})  "
            f"connection={p.connection_name}  models={p.model_count}"
        )
    return "\n".join(lines)


@mcp.tool()
async def get_project(name: str) -> str:
    """Get dbt project detail including path and model count."""
    from . import project_store

    proj = project_store.get_project(name)
    if not proj:
        return f"Error: Project '{name}' not found."
    lines = [
        f"Project: {proj.name}",
        f"  id: {proj.id}",
        f"  connection: {proj.connection_name}",
        f"  db_type: {proj.db_type}",
        f"  project_dir: {proj.project_dir}",
        f"  storage: {proj.storage.value}",
        f"  source: {proj.source.value}",
        f"  status: {proj.status.value}",
        f"  model_count: {proj.model_count}",
        f"  dbt_version: {proj.dbt_version}",
    ]
    if proj.description:
        lines.append(f"  description: {proj.description}")
    if proj.tags:
        lines.append(f"  tags: {', '.join(proj.tags)}")
    if proj.git_remote:
        lines.append(f"  git_remote: {proj.git_remote}")
    return "\n".join(lines)


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    """Run the MCP server.

    Transport is selected via SP_MCP_TRANSPORT env var (default: stdio).
    When running as streamable-http, wraps the Starlette app with
    MCPAuthMiddleware and serves it with uvicorn.
    """
    import os as _entry_os
    transport = _entry_os.environ.get("SP_MCP_TRANSPORT", "stdio")

    if transport == "streamable-http":
        import uvicorn
        from .mcp_auth import MCPAuthMiddleware

        port = int(_entry_os.environ.get("SP_MCP_PORT", "8000"))
        starlette_app = mcp.streamable_http_app()
        authenticated_app = MCPAuthMiddleware(starlette_app)
        uvicorn.run(authenticated_app, host="0.0.0.0", port=port, server_header=False)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
