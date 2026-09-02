"""Query tools: plan_query, query_database, validation, and budgets."""

import json

import httpx
from sqlalchemy import select

from gateway.db.models import GatewayChatConversation, GatewayChatRun
from gateway.errors import query_error_hint
from gateway.errors.mcp import sanitize_mcp_error, sanitize_proxy_response
from gateway.governance.query_executor import (
    GovernedQueryContext,
    GovernedQueryError,
    governed_query_executor,
)
from gateway.governance.query_planner import (
    QueryPlanError,
    create_query_plan,
)
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import (
    _gateway_url,
    _gw_headers,
    _store_session,
    mcp_allowed_connection_var,
    mcp_execution_identity_var,
)
from gateway.mcp.server import mcp
from gateway.mcp.validation import _validate_connection_name, _validate_sql


def _selected_connection(connection_name: str | None) -> tuple[str | None, str | None]:
    """Resolve a run-bound connection without making the agent repeat it."""
    requested = (connection_name or "").strip()
    allowed = (mcp_allowed_connection_var.get(None) or "").strip()
    if allowed:
        if requested and requested != allowed:
            return None, "The requested connection is outside this session's scope"
        return allowed, None
    if not requested:
        return None, "connection_name is required when the session is not bound to one connection"
    return requested, None


async def _chat_query_context(store, *, path: str, plan_id: str | None = None) -> GovernedQueryContext:
    identity = mcp_execution_identity_var.get(None)
    if not identity or not identity.startswith("chat:"):
        return GovernedQueryContext(path=path)  # type: ignore[arg-type]
    run_id = identity.removeprefix("chat:")
    scoped = (
        await store.session.execute(
            select(GatewayChatRun, GatewayChatConversation)
            .join(GatewayChatConversation, GatewayChatConversation.id == GatewayChatRun.conversation_id)
            .where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.org_id == store._require_org_id(),
                GatewayChatRun.user_id == (store.user_id or "local"),
                GatewayChatRun.status == "running",
                GatewayChatRun.cancellation_requested_at.is_(None),
                GatewayChatConversation.surface == "standalone",
            )
        )
    ).one_or_none()
    if scoped is None:
        raise QueryPlanError("scope_mismatch", "Standalone query scope mismatch")
    run, conversation = scoped
    return GovernedQueryContext(
        path=path,  # type: ignore[arg-type]
        conversation_id=run.conversation_id,
        run_id=run.id,
        project_id=run.project_id,
        commit_sha=conversation.commit_sha,
        branch=conversation.branch,
        plan_id=plan_id,
    )


@audited_tool(mcp)
async def plan_query(
    sql: str,
    connection_name: str | None = None,
) -> str:
    """Optional route preflight. query_database plans automatically."""
    connection_name, scope_error = _selected_connection(connection_name)
    if scope_error:
        return f"Error: {scope_error}"
    assert connection_name is not None
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    async with _store_session() as store:
        try:
            context = await _chat_query_context(store, path="mcp")
            plan = await create_query_plan(
                store,
                connection_name=connection_name,
                sql=sql,
                purpose="Plan a governed analysis query",
                context=context,
            )
        except QueryPlanError as exc:
            return f"Planning error: {sanitize_mcp_error(str(exc), cap=300)}"
    return json.dumps(plan.as_agent_dict(), default=str)


@audited_tool(mcp)
async def query_database(
    sql: str,
    row_limit: int = 1000,
    connection_name: str | None = None,
) -> str:
    """
    Execute a governed, read-only SQL query against a connected database.

    All queries are validated through the SignalPilot governance pipeline:
    - SQL is parsed to AST and checked for DDL/DML (blocked)
    - Statement stacking is detected and blocked
    - LIMIT is automatically injected/clamped
    - Results are logged to the audit trail

    Args:
        sql: SQL query (SELECT only)
        row_limit: Max rows to return (default 1000, max 10000)
        connection_name: Optional outside a connection-bound chat session

    Returns:
        Query results as formatted text, or an error message.
    """
    connection_name, scope_error = _selected_connection(connection_name)
    if scope_error:
        return f"Error: {scope_error}"
    assert connection_name is not None
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if err := _validate_sql(sql):
        return f"Error: {err}"

    async with _store_session() as store:
        try:
            context = await _chat_query_context(store, path="mcp")
            if context.run_id:
                plan = await create_query_plan(
                    store,
                    connection_name=connection_name,
                    sql=sql,
                    purpose="Run a governed SQL query",
                    context=context,
                )
                if plan.route != "mcp":
                    return json.dumps(
                        {
                            "route": plan.route,
                            "approval_required": plan.approval_required,
                        }
                    )
                context = await _chat_query_context(store, path="mcp", plan_id=plan.plan_id)
            result = await governed_query_executor.execute(
                store,
                connection_name=connection_name,
                sql=sql,
                row_limit=min(row_limit, 10_000),
                timeout_seconds=150,
                context=context,
            )
        except (GovernedQueryError, QueryPlanError) as exc:
            return f"Query error: {sanitize_mcp_error(str(exc), cap=300)}"

    # Format parsed by standalone_chat/tool_projection/query.py; update tests there if you change this
    # Build status footer
    meta_parts = [
        f"{result.row_count} rows",
        f"{result.execution_ms:.0f}ms",
        f"result {result.result_id}",
        f"completeness: {result.completeness}",
    ]

    # PII redaction notice for the LLM
    redaction_notice = ""
    if result.pii_redacted:
        redacted_cols = ", ".join(result.pii_redacted)
        redaction_notice = (
            f"\n\n[PII REDACTED] The following columns were redacted by policy: {redacted_cols}. "
            f"Values shown as ***** (hide), sha256:... (hash), or partially masked. "
            f"Do not attempt to reverse or infer the original values."
        )

    if not result.rows:
        return f"Query returned 0 rows ({', '.join(meta_parts)})" + redaction_notice

    # Format as readable table
    columns = list(result.rows[0].keys())
    lines = [" | ".join(str(c) for c in columns)]
    lines.append("-" * len(lines[0]))
    # Cap model display, not the durable structured result. The floor is 50 rows;
    # narrow rows (metadata enumerations, column lists) keep printing within a
    # character budget so a schema listing is not cut off mid-table.
    display_floor = 50
    char_budget = 12000
    shown = 0
    chars = 0
    for row in result.rows:
        if shown >= 400:
            break
        line = " | ".join(str(row.get(c, "")) for c in columns)
        if shown >= display_floor and chars + len(line) > char_budget:
            break
        lines.append(line)
        shown += 1
        chars += len(line) + 1
    if result.row_count > shown:
        lines.append(
            f"[INCOMPLETE DISPLAY] {result.row_count} rows total; only the first {shown} are shown above. "
            f"The remaining {result.row_count - shown} rows exist but are not displayed. "
            f"Do not treat the list above as complete: re-run the query with a WHERE filter or OFFSET {shown} "
            f"to see every remaining row before concluding anything about what the full result does or does not contain."
        )
    if result.truncation_reason:
        lines.append(f"Completeness note: {result.truncation_reason}")

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

    Use the generate, explain, fix, and execute sequence because the plan can
    reveal errors before execution.

    Args:
        connection_name: Name of the database connection
        sql: SQL query to explain
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
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
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
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
            # Format parsed by standalone_chat/tool_projection/query.py; update tests there if you change this
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

    Prior successful queries can provide reusable patterns for follow-up work
    in the same session.

    Args:
        connection_name: Name of the database connection
        limit: Max queries to return (default 10, max 50)
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"

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
