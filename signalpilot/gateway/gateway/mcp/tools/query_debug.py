"""Query diagnostics tools: estimate_query_cost and debug_cte_query.

Split from ``query.py`` to keep both files under the 600-line limit; the
tools are re-exported there so ``gateway.mcp`` registration is unchanged.
"""

import httpx

from gateway.errors import query_error_hint
from gateway.errors.mcp import sanitize_mcp_error, sanitize_proxy_response
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _gateway_url, _gw_headers
from gateway.mcp.server import mcp
from gateway.mcp.validation import _validate_connection_name, _validate_sql


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
