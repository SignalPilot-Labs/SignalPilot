"""Schema DDL tools: schema_diff, schema_ddl, schema_link (tools 8, 9, 10)."""

from __future__ import annotations

import httpx

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _gateway_url, _gw_headers
from gateway.mcp.server import mcp
from gateway.mcp.validation import _CONN_NAME_RE
from gateway.mcp_errors import sanitize_proxy_response


@audited_tool(mcp)
async def schema_diff(connection_name: str) -> str:
    """
    Compare current database schema against the last cached version.

    Returns added/removed/modified tables and columns. Use this after DDL changes
    or migrations to verify what changed and update your understanding of the schema.
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(f"{gw}/api/connections/{connection_name}/schema/diff", headers=_gw_headers())
    if r.status_code != 200:
        return sanitize_proxy_response(r.status_code, r.text)

    data = r.json()
    lines = [f"Schema Diff for {connection_name}:"]
    lines.append(f"  Tables: {data.get('table_count', 0)}")

    if not data.get("has_cached"):
        lines.append(f"  {data.get('message', 'No cached schema — baseline stored.')}")
        return "\n".join(lines)

    diff = data.get("diff", {})
    if not diff.get("has_changes"):
        lines.append("  No changes detected")
        return "\n".join(lines)

    added = diff.get("added_tables", [])
    removed = diff.get("removed_tables", [])
    modified = diff.get("modified_tables", [])

    if added:
        lines.append(f"  Added tables ({len(added)}): {', '.join(added[:10])}")
    if removed:
        lines.append(f"  Removed tables ({len(removed)}): {', '.join(removed[:10])}")
    if modified:
        lines.append(f"  Modified tables ({len(modified)}):")
        for m in modified[:5]:
            parts = [m["table"]]
            if m.get("added_columns"):
                parts.append(f"+cols: {', '.join(m['added_columns'][:5])}")
            if m.get("removed_columns"):
                parts.append(f"-cols: {', '.join(m['removed_columns'][:5])}")
            if m.get("type_changes"):
                for tc in m["type_changes"][:3]:
                    parts.append(f"{tc['column']}: {tc['old_type']}→{tc['new_type']}")
            lines.append(f"    {' | '.join(parts)}")

    return "\n".join(lines)


@audited_tool(mcp)
async def schema_ddl(connection_name: str, max_tables: int = 50, compress: bool = False) -> str:
    """
    Get the database schema as CREATE TABLE DDL statements.

    DDL format is preferred over JSON/text for text-to-SQL because:
    - LLMs have seen massive DDL in training, making it the natural schema format
    - DDL encodes constraints (PK, FK, NOT NULL) in standard SQL syntax
    - Spider2.0 SOTA systems (DAIL-SQL, CHESS) use DDL format

    Use this when you need to write SQL queries against the database.
    For initial exploration, use schema_overview first, then compact_schema,
    then this tool for the final DDL needed to write queries.

    Args:
        connection_name: Name of the database connection
        max_tables: Maximum number of tables to include (default 50)
        compress: Enable ReFoRCE-style table grouping for large schemas (groups similar-prefix
                  tables, shows one DDL per group with member list — saves 30-50% tokens)
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            f"{gw}/api/connections/{connection_name}/schema/ddl",
            params={"max_tables": max_tables, "compress": compress},
            headers=_gw_headers(),
        )
    if r.status_code != 200:
        return sanitize_proxy_response(r.status_code, r.text)

    data = r.json()
    compressed = data.get("compressed_tables", 0)
    total_repr = data.get("total_tables_represented", data.get("table_count", 0))
    header = f"-- Schema DDL for {connection_name}\n-- Tables: {data.get('table_count', 0)} DDL"
    if compressed:
        header += f" + {compressed} compressed ({total_repr} total)"
    header += f", Est. tokens: {data.get('token_estimate', 0)}\n\n"
    return header + data.get("ddl", "")


@audited_tool(mcp)
async def schema_link(connection_name: str, question: str, format: str = "ddl", max_tables: int = 20) -> str:
    """
    Smart schema linking — find tables relevant to a natural language question.

    This is the recommended tool for writing SQL queries. Instead of loading the
    full schema, describe what you want to query and this tool returns only the
    relevant tables with their DDL, scored by relevance.

    Uses high-recall linking (EDBT 2026): matches question terms against table
    names, column names, and comments, then expands via foreign keys to ensure
    join paths are available.

    Args:
        connection_name: Name of the database connection
        question: Natural language question (e.g., "total revenue by customer last month")
        format: Output format — "ddl" (default, best for SQL gen), "compact", or "json"
        max_tables: Maximum tables to include (default 20)
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            f"{gw}/api/connections/{connection_name}/schema/link",
            params={"question": question, "format": format, "max_tables": max_tables},
            headers=_gw_headers(),
        )
    if r.status_code != 200:
        return sanitize_proxy_response(r.status_code, r.text)

    data = r.json()
    linked = data.get("linked_tables", 0)
    total = data.get("total_tables", 0)
    header = f"-- Schema linked for: {question}\n-- Linked {linked}/{total} tables\n"

    if format == "compact":
        return header + "\n" + data.get("schema", "")
    if format == "json":
        import json as _json

        return header + "\n" + _json.dumps(data.get("tables", {}), indent=2, default=str)
    tokens = data.get("token_estimate", 0)
    header += f"-- Est. tokens: {tokens}\n\n"
    return header + data.get("ddl", "")
