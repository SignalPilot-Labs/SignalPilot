"""Schema statistics tool: schema_statistics (tool 12)."""

from __future__ import annotations

import httpx

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _gateway_url, _gw_headers
from gateway.mcp.server import mcp
from gateway.mcp.validation import _validate_connection_name
from gateway.mcp_errors import sanitize_mcp_error, sanitize_proxy_response


@audited_tool(mcp)
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
            resp = await client.get(f"{gw}/api/connections/{connection_name}/schema/overview", headers=_gw_headers())
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
