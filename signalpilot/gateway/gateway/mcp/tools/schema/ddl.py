"""Schema DDL tools: schema_diff, schema_ddl, schema_link (tools 8, 9, 10)."""

import httpx

from gateway.errors.mcp import sanitize_proxy_response
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _gateway_url, _gw_headers
from gateway.mcp.server import mcp
from gateway.mcp.validation import _CONN_NAME_RE


async def _no_xata_db_msg() -> str | None:
    """Friendly message when no Xata connection is registered, else None.

    The Xata branch tools stay always-listed (the skill layer loads them
    conditionally), but no-op gracefully with a clear message when there is no
    Xata database to act on. Fails open on a transient listing error.
    """
    gw = _gateway_url()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{gw}/api/connections", headers=_gw_headers())
        if r.status_code == 200:
            body = r.json()
            conns = body if isinstance(body, list) else body.get("connections", [])
            if any("xata" in str(c.get("db_type", "")).lower() for c in conns):
                return None
    except Exception:
        return None
    return "No Xata DB connected. Register a Xata database connection to use branch tools."


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
async def schema_diff_branches(base_connection: str, compare_connection: str) -> str:
    """
    Diff the live schemas of two database connections (e.g. two Xata branches).

    Unlike schema_diff (one connection vs. its own cached snapshot), this compares
    two distinct connections head-to-head. Use it to review an upstream branch
    BEFORE it merges: register the base branch and the feature branch as two
    connections, then diff to see every added/removed/retyped column that could
    break a dbt model or pipeline.

    Args:
        base_connection: The base/production branch connection name.
        compare_connection: The feature/upstream branch connection name.
    """
    if not _CONN_NAME_RE.match(base_connection) or not _CONN_NAME_RE.match(compare_connection):
        return "Error: Invalid connection name"

    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(
            f"{gw}/api/connections/{base_connection}/schema/diff/{compare_connection}",
            headers=_gw_headers(),
        )
    if r.status_code != 200:
        return sanitize_proxy_response(r.status_code, r.text)

    data = r.json()
    diff = data.get("diff", {})
    lines = [
        f"Schema Diff: {base_connection} (base) -> {compare_connection} (compare)",
        f"  Base tables: {data.get('base_table_count', 0)} | "
        f"Compare tables: {data.get('compare_table_count', 0)}",
    ]
    if not diff.get("has_changes"):
        lines.append("  No schema differences between the two branches.")
        return "\n".join(lines)

    if diff.get("added_tables"):
        lines.append(f"  Added tables: {', '.join(diff['added_tables'][:20])}")
    if diff.get("removed_tables"):
        lines.append(f"  Removed tables: {', '.join(diff['removed_tables'][:20])}")
    for m in diff.get("modified_tables", []):
        parts = [m["table"]]
        if m.get("added_columns"):
            parts.append(f"+cols: {', '.join(m['added_columns'][:10])}")
        if m.get("removed_columns"):
            parts.append(f"-cols: {', '.join(m['removed_columns'][:10])}")
        for tc in m.get("type_changes", []):
            parts.append(f"{tc['column']}: {tc['old_type']}→{tc['new_type']}")
        lines.append(f"    {' | '.join(parts)}")
    return "\n".join(lines)


@audited_tool(mcp)
async def xata_branch_diff(connection_name: str, base_branch: str, compare_branch: str) -> str:
    """
    Diff two Xata branches addressed from ONE registered workspace connection.

    Unlike schema_diff_branches (which needs two separate connections), this uses a
    single Xata workspace credential and swaps the branch per-call — ideal for
    reviewing an upstream branch before it merges. The gateway resolves both branch
    endpoints server-side; you only name the branches.

    Args:
        connection_name: The Xata workspace connection.
        base_branch: Base branch name (e.g. "main").
        compare_branch: Feature/upstream branch name to compare against base.
    """
    no_xata = await _no_xata_db_msg()
    if no_xata:
        return no_xata
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(
            f"{gw}/api/connections/{connection_name}/xata/branch-diff",
            params={"base": base_branch, "compare": compare_branch},
            headers=_gw_headers(),
        )
    if r.status_code != 200:
        return sanitize_proxy_response(r.status_code, r.text)

    data = r.json()
    diff = data.get("diff", {})
    lines = [f"Xata branch diff: {base_branch} (base) -> {compare_branch} (compare)"]
    if not diff.get("has_changes"):
        lines.append("  No schema differences between the two branches.")
        return "\n".join(lines)
    if diff.get("added_tables"):
        lines.append(f"  Added tables: {', '.join(diff['added_tables'][:20])}")
    if diff.get("removed_tables"):
        lines.append(f"  Removed tables: {', '.join(diff['removed_tables'][:20])}")
    for m in diff.get("modified_tables", []):
        parts = [m["table"]]
        if m.get("added_columns"):
            parts.append(f"+cols: {', '.join(m['added_columns'][:10])}")
        if m.get("removed_columns"):
            parts.append(f"-cols: {', '.join(m['removed_columns'][:10])}")
        for tc in m.get("type_changes", []):
            parts.append(f"{tc['column']}: {tc['old_type']}→{tc['new_type']}")
        lines.append(f"    {' | '.join(parts)}")
    return "\n".join(lines)


@audited_tool(mcp)
async def xata_list_branches(connection_name: str, project: str) -> str:
    """
    List branches in a Xata project (control plane).

    Args:
        connection_name: The Xata workspace connection.
        project: The Xata project id.
    """
    no_xata = await _no_xata_db_msg()
    if no_xata:
        return no_xata
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            f"{gw}/api/connections/{connection_name}/xata/projects/{project}/branches",
            headers=_gw_headers(),
        )
    if r.status_code != 200:
        return sanitize_proxy_response(r.status_code, r.text)
    branches = r.json().get("branches", [])
    if not branches:
        return f"No branches in project {project}."
    lines = [f"Branches in {project}:"]
    for b in branches:
        parent = b.get("parentID") or "—"
        lines.append(f"  {b.get('name')}  (id={b.get('id', '')[:12]}, parent={parent})")
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
