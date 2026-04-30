"""Schema exploration tool: explore_table (tool 6)."""

from __future__ import annotations

import httpx

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _gateway_url, _gw_headers
from gateway.mcp.server import mcp
from gateway.mcp.validation import _CONN_NAME_RE
from gateway.mcp_errors import sanitize_proxy_response


@audited_tool(mcp)
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
            headers=_gw_headers(),
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
        lines.append("\nSample values:")
        for col_name, vals in samples.items():
            lines.append(f"  {col_name}: {', '.join(str(v) for v in vals[:5])}")

    return "\n".join(lines)
