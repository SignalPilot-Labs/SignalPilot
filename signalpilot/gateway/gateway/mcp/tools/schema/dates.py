"""Schema dates tool: get_date_boundaries (tool 3)."""

from __future__ import annotations

from gateway.errors.mcp import sanitize_mcp_error
from gateway.governance.context import current_org_id_var
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import mcp_org_id_var
from gateway.mcp.helpers import _fetch_date_boundaries
from gateway.mcp.server import mcp
from gateway.mcp.validation import _validate_connection_name


@audited_tool(mcp)
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

    org_id = mcp_org_id_var.get(None) or "local"
    token = current_org_id_var.set(org_id)
    try:
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
        from gateway.connectors.schema_cache import schema_cache

        schema = schema_cache.get(connection_name) or {}

        DATE_TYPE_KEYWORDS = ("date", "timestamp", "datetime")
        for key in sorted(schema.keys()):
            table = schema[key]
            table_schema = table.get("schema", "")
            table_name = table.get("name", key)
            full_name = f"{table_schema}.{table_name}" if table_schema else table_name
            date_cols = [
                col
                for col in table.get("columns", [])
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
                    " ← USE THIS for spine if this is your fact/event table" if tbl_max != result.global_max else ""
                )
                lines.append(f"  {tbl} → {tbl_max} ({count_str}){size_marker}{spine_marker}")
            lines.append("")
            lines.append("RULE: Use the max date of your PRIMARY FACT TABLE (orders, events, transactions)")
            lines.append("      as the date spine endpoint. Do NOT use the global max if it comes from a")
            lines.append("      dimension or reference table with a later date.")
        else:
            lines.append("GLOBAL MAX DATE: (no non-null date values found)")

        return "\n".join(lines)
    finally:
        current_org_id_var.reset(token)
