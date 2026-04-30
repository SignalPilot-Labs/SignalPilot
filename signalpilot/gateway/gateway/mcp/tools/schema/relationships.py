"""Schema relationships tools: find_join_path, get_relationships (tools 4, 5)."""

from __future__ import annotations

import json

import httpx

from gateway.errors.mcp import sanitize_proxy_response
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _gateway_url, _gw_headers
from gateway.mcp.server import mcp
from gateway.mcp.validation import _CONN_NAME_RE


@audited_tool(mcp)
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
            headers=_gw_headers(),
        )
        if resp.status_code != 200:
            return sanitize_proxy_response(resp.status_code, resp.text)
        data = resp.json()

    paths = data.get("paths", [])
    if not paths:
        return f"No join path found between {from_table} and {to_table} within {max_hops} hops"

    lines = [f"Join paths: {from_table} → {to_table} ({len(paths)} found)\n"]
    for i, p in enumerate(paths):
        lines.append(f"Path {i + 1} ({p['hops']} hop{'s' if p['hops'] != 1 else ''}):")
        lines.append(f"  Tables: {' → '.join(p['tables'])}")
        for j in p.get("joins", []):
            lines.append(f"  JOIN ON {j['from']} = {j['to']}")
        if p.get("sql_hint"):
            lines.append(f"  SQL: {p['sql_hint']}")
        lines.append("")
    return "\n".join(lines)


@audited_tool(mcp)
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
            headers=_gw_headers(),
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
    if format == "graph":
        adj = data.get("adjacency", {})
        if not adj:
            return "No relationships found"
        lines = [f"Table Graph ({len(adj)} tables):\n"]
        for table, neighbors in adj.items():
            lines.append(f"  {table} ↔ {', '.join(neighbors)}")
        return "\n".join(lines)
    return json.dumps(data, indent=2)
