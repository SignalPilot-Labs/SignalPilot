"""Query tools: query_database, validate_sql, explain_query, check_budget, etc."""

from __future__ import annotations

import time

import httpx

from gateway.engine import inject_limit
from gateway.engine import validate_sql as engine_validate_sql
from gateway.errors import query_error_hint
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _gateway_url, _gw_headers, _store_session
from gateway.mcp.server import mcp
from gateway.mcp.validation import _CONN_NAME_RE, _validate_connection_name, _validate_sql
from gateway.mcp_errors import sanitize_mcp_error, sanitize_proxy_response


@audited_tool(mcp)
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

    from gateway.governance.annotations import load_annotations
    from gateway.governance.plan_limits import check_query_limit, get_org_limits

    async with _store_session() as store:
        # Enforce daily query limit
        plan = await get_org_limits(store.org_id)
        try:
            check_query_limit(store.org_id, plan)
        except Exception as e:
            return f"Error: {e}"

        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        # Load annotations for blocked tables (Feature #19)
        from gateway.governance.context import require_org_id

        annotations = load_annotations(require_org_id(), connection_name)
        blocked_tables = annotations.blocked_tables

        # Validate SQL (with blocked tables from annotations)
        validation = engine_validate_sql(sql, blocked_tables=blocked_tables or None)
        if not validation.ok:
            return f"Query blocked: {validation.blocked_reason}"

        # Inject LIMIT
        row_limit = min(row_limit, 10_000)
        try:
            safe_sql = inject_limit(sql, row_limit)
        except ValueError as exc:
            return f"Query blocked: {exc}"

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection (restart gateway to reload)"

        from gateway.connectors.health_monitor import health_monitor
        from gateway.connectors.pool_manager import pool_manager

        extras = await store.get_credential_extras(connection_name)
        start = time.monotonic()
        try:
            async with pool_manager.connection(
                conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
            ) as connector:
                rows = await connector.execute(safe_sql)
        except Exception as e:
            elapsed_err = (time.monotonic() - start) * 1000
            health_monitor.record(connection_name, elapsed_err, False, str(e)[:200], conn_info.db_type)
            err_str = str(e)
            hint = query_error_hint(err_str, conn_info.db_type)
            sanitized = sanitize_mcp_error(err_str, cap=300)
            return f"Query error: {sanitized}" + (f"\n\nHint: {hint}" if hint else "")

        elapsed_ms = (time.monotonic() - start) * 1000
        health_monitor.record(connection_name, elapsed_ms, True, db_type=conn_info.db_type)

        # Apply PII redaction if enabled on this connection
        from gateway.governance.pii import PIIRedactor

        pii_redactor = PIIRedactor()
        if conn_info.pii_enabled and conn_info.pii_rules:
            for col_name, rule in conn_info.pii_rules.items():
                pii_redactor.add_rule(col_name, rule)
        for col_name, rule in annotations.pii_columns.items():
            pii_redactor.add_rule(col_name, rule)
        if pii_redactor.has_rules():
            rows = pii_redactor.redact_rows(rows)

        # Charge query cost to budget
        from gateway.governance.budget import budget_ledger

        query_cost_usd = (elapsed_ms / 1000) * 0.000014
        budget_ok = await budget_ledger.charge("default", query_cost_usd)
        if not budget_ok:
            return f"Query budget exhausted. This query would cost ~${query_cost_usd:.6f}. Remaining budget: $0.00"

    # Build status footer
    meta_parts = [f"{len(rows)} rows", f"{elapsed_ms:.0f}ms"]

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


@audited_tool(mcp)
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
    from gateway.governance.budget import budget_ledger

    async with _store_session() as _store:
        budget = await budget_ledger.get_session(session_id)
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


@audited_tool(mcp)
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
            headers=_gw_headers(),
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


@audited_tool(mcp)
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
                headers=_gw_headers(),
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
        # Extract error details
        error_text = r.text[:500]
        # Get db_type for dialect-specific hints
        db_type = ""
        try:
            async with httpx.AsyncClient(timeout=5) as client2:
                r2 = await client2.get(f"{gw}/api/connections/{connection_name}", headers=_gw_headers())
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


@audited_tool(mcp)
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
            headers=_gw_headers(),
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


@audited_tool(mcp)
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
                headers=_gw_headers(),
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


@audited_tool(mcp)
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
    cte_pattern = re.compile(r"(?:WITH\s+|,\s*)(\w+)\s+AS\s*\(", re.IGNORECASE)
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
            remaining = sql_stripped
            # Remove leading WITH
            remaining_no_with = re.sub(r"^\s*WITH\s+", "", remaining, flags=re.IGNORECASE)

            # Simple approach: for each CTE up to i, extract by matching parentheses
            # This is a simplified parser; won't handle all edge cases
            test_sql = (
                f"WITH {remaining_no_with.split('SELECT', 1)[0].rstrip().rstrip(',')} SELECT * FROM {cte_name} LIMIT 5"
            )

            # Alternative: ask gateway to run it
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{gw}/api/query",
                    json={
                        "connection_name": connection_name,
                        "sql": test_sql,
                        "row_limit": 5,
                    },
                    headers=_gw_headers(),
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
                        r2 = await client2.get(f"{gw}/api/connections/{connection_name}", headers=_gw_headers())
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
                headers=_gw_headers(),
            )
        if resp.status_code == 200:
            data = resp.json()
            lines.append(f"OK ✓ — {data.get('row_count', 0)} rows returned")
        else:
            lines.append(f"ERROR ✗: {sanitize_mcp_error(resp.text[:300], cap=300)}")
    except Exception as e:
        lines.append(f"ERROR: {sanitize_mcp_error(str(e))}")

    return "\n".join(lines)
