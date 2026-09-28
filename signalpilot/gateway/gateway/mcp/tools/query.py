"""Query tools: plan_query, query_database, validation, and budgets."""

import json

import httpx
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select

from gateway.db.models import GatewayChatConversation, GatewayChatRun
from gateway.errors import query_error_hint
from gateway.errors.mcp import DB_ERROR_CAP, sanitize_mcp_error, sanitize_proxy_response
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

# Re-exported so gateway.mcp and existing imports keep resolving these tools here.
from gateway.mcp.tools.query_debug import (
    debug_cte_query as debug_cte_query,
)
from gateway.mcp.tools.query_debug import (
    estimate_query_cost as estimate_query_cost,
)
from gateway.mcp.validation import _validate_connection_name, _validate_sql

# A route other than "mcp" is the agent's only notice that this query will not
# run here. The route code alone says nothing, so every code carries its own
# next step in the tool result instead of in the system prompt.
_ROUTE_NEXT_STEP = {
    "aggregate_required": (
        "This query would return more data than query_database can return, so it did not run. "
        "Rewrite it as a bounded warehouse aggregate with GROUP BY, tighter filters, or fewer "
        "columns, then call query_database again."
    ),
    "notebook_sdk": (
        "This query is too large for query_database or needs Python, so it did not run. "
        "Run it in the notebook with the sp SDK instead."
    ),
    "dataset_ref": (
        "This result is too large to return here and is available as a dataset reference. "
        "Read it in the notebook with the sp SDK instead of query_database."
    ),
    "refuse": (
        "Governance refused this query, so it will not run here or anywhere else. "
        "Stop this line of work and tell the user that governance refused the query."
    ),
}


def _route_payload(plan) -> dict[str, object]:
    """The plan decision plus the next step the route calls for."""
    payload = dict(plan.as_agent_dict())
    if plan.route != "mcp":
        payload["next_step"] = _ROUTE_NEXT_STEP.get(
            plan.route,
            f"This query was routed to {plan.route} and cannot run here. "
            "Tell the user that query_database cannot run this query.",
        )
    return payload


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
            # A ToolError becomes an isError result, so the SDK and the chat
            # UI count the failure instead of recording a successful call.
            raise ToolError(f"Planning error: {sanitize_mcp_error(str(exc), cap=DB_ERROR_CAP)}") from exc
    return json.dumps(_route_payload(plan), default=str)


@audited_tool(mcp)
async def query_database(
    sql: str,
    row_limit: int = 1000,
    connection_name: str | None = None,
    description: str = "",
) -> str:
    """
    Execute a governed, read-only SQL query against a connected database.

    Always pass `description`: one short sentence, in plain words, that says what
    this query finds out. It is shown to the user as the title of the query card
    while the query runs, so name the mart or table and the question, for
    example "Checking the date range of the rpt_daily_profitability mart" or
    "Counting orders per region for Q3". Do not repeat the SQL.

    All queries are validated through the SignalPilot governance pipeline:
    - SQL is parsed to AST and checked for DDL/DML (blocked)
    - Statement stacking is detected and blocked
    - LIMIT is automatically injected/clamped
    - Results are logged to the audit trail

    Args:
        sql: SQL query (SELECT only)
        row_limit: Max rows to return (default 1000, max 10000)
        connection_name: Optional outside a connection-bound chat session
        description: One sentence, max 140 characters, naming what the query
            finds out. Shown to the user as the card title; not used for
            execution.

    Returns:
        Query results as formatted text. Governance rejections and warehouse
        failures are raised as tool errors whose text starts "Query error:".
    """
    del description  # Display-only: the chat UI reads it from the tool input.
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
                    return json.dumps(_route_payload(plan), default=str)
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
            # Governance and warehouse failures are tool errors: raising a
            # ToolError makes the SDK mark the result isError, so the chat UI,
            # the audit trail and the failure metrics all see it as a failure.
            raise ToolError(f"Query error: {sanitize_mcp_error(str(exc), cap=DB_ERROR_CAP)}") from exc

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
