"""Schema exploration tool: explore_columns (tool 11)."""

from __future__ import annotations

import httpx

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _gateway_url, _gw_headers
from gateway.mcp.server import mcp
from gateway.mcp.validation import _validate_connection_name
from gateway.mcp_errors import sanitize_mcp_error, sanitize_proxy_response


@audited_tool(mcp)
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
                headers=_gw_headers(),
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
        lines = [
            f"{'View' if table_type == 'view' else 'Table'}: {table} ({rc:,} rows)"
            if isinstance(rc, int)
            else f"Table: {table} ({rc} rows)"
        ]
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
