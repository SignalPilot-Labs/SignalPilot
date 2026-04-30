"""Schema exploration tool: explore_column (tool 13)."""

from __future__ import annotations

import httpx

from gateway.errors.mcp import sanitize_mcp_error, sanitize_proxy_response
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _gateway_url, _gw_headers
from gateway.mcp.server import mcp
from gateway.mcp.validation import _validate_connection_name


@audited_tool(mcp)
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
                headers=_gw_headers(),
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
