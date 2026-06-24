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


def _classify_breaking(diff: dict) -> tuple[list[str], list[str]]:
    """Split a schema diff into (breaking, safe) human-readable change descriptions."""
    breaking: list[str] = []
    safe: list[str] = []
    for t in diff.get("removed_tables", []):
        breaking.append(f"Table dropped: {t}")
    for t in diff.get("added_tables", []):
        safe.append(f"Table added: {t}")
    for m in diff.get("modified_tables", []):
        tbl = m.get("table", "")
        for c in m.get("removed_columns", []):
            breaking.append(f"Column dropped: {tbl}.{c}")
        for tc in m.get("type_changes", []):
            breaking.append(f"Type changed: {tbl}.{tc['column']}: {tc['old_type']} → {tc['new_type']}")
        for c in m.get("added_columns", []):
            safe.append(f"Column added: {tbl}.{c}")
    return breaking, safe


def _render_branch_diff_html(base: str, compare: str, diff: dict) -> str:
    """Self-contained HTML pre-merge impact report for a branch diff."""
    import html as _html

    breaking, safe = _classify_breaking(diff)
    block = bool(breaking)
    verdict = (
        "BLOCK MERGE — breaking changes" if block
        else ("SAFE TO MERGE" if diff.get("has_changes") else "NO SCHEMA CHANGES")
    )
    color = "#dc2626" if block else "#16a34a"

    def _li(items: list[str], cls: str) -> str:
        return "".join(f'<li class="{cls}">{_html.escape(x)}</li>' for x in items) or '<li class="none">none</li>'

    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Xata branch diff</title>
<style>
body{{font-family:system-ui,Segoe UI,Arial,sans-serif;background:#0b0e14;color:#e6e6e6;margin:0;padding:32px}}
.card{{max-width:860px;margin:0 auto;background:#11151f;border:1px solid #232a3a;border-radius:12px;padding:28px}}
h1{{font-size:18px;margin:0 0 4px}} .sub{{color:#9aa4b2;font-size:13px;margin-bottom:18px}}
.verdict{{display:inline-block;padding:8px 14px;border-radius:8px;font-weight:600;color:#fff;background:{color};margin-bottom:18px}}
h2{{font-size:13px;color:#9aa4b2;text-transform:uppercase;letter-spacing:.06em;margin:22px 0 8px}}
ul{{list-style:none;padding:0;margin:0}}
li{{padding:6px 10px;border-radius:6px;margin-bottom:4px;font-size:14px;font-family:ui-monospace,monospace}}
.brk{{background:#2a1416;color:#fca5a5}} .safe{{background:#0f2417;color:#86efac}} .none{{color:#6b7280}}
</style></head><body><div class="card">
<h1>🦋 Xata pre-merge schema-impact report</h1>
<div class="sub">base <b>{_html.escape(base)}</b> &larr; compare <b>{_html.escape(compare)}</b></div>
<div class="verdict">{verdict}</div>
<h2>Breaking changes ({len(breaking)}) — downstream models/queries may fail</h2>
<ul>{_li(breaking, "brk")}</ul>
<h2>Safe / additive changes ({len(safe)})</h2>
<ul>{_li(safe, "safe")}</ul>
</div></body></html>"""


async def _save_branch_diff_report(base: str, compare: str, diff: dict) -> str:
    """Render the diff as an HTML report, persist it, return a shareable URL (JSON)."""
    import json as _json
    import os as _os

    from gateway.errors.mcp import sanitize_mcp_error
    from gateway.mcp.context import _store_session
    from gateway.models.reports import ReportCreate

    breaking, _safe = _classify_breaking(diff)
    html_doc = _render_branch_diff_html(base, compare, diff)
    try:
        async with _store_session() as store:
            report = await store.insert_report(
                ReportCreate(title=f"Xata branch diff: {base} <- {compare}", html=html_doc, scope_ref=None),
                user_id=None,
                agent="xata_branch_diff",
            )
        web = (_os.getenv("SP_WEB_URL") or _os.getenv("SIGNALPILOT_WEB_URL") or "http://localhost:3200").rstrip("/")
        return _json.dumps({
            "status": "created",
            "verdict": "block_merge" if breaking else "safe_to_merge",
            "breaking_changes": len(breaking),
            "report_url": f"{web}/reports?report={report.id}",
            "report_id": report.id,
        })
    except Exception as exc:
        return f"Error rendering HTML diff: {sanitize_mcp_error(str(exc))}"


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
async def xata_branch_diff(
    connection_name: str, base_branch: str, compare_branch: str, format: str = "text"
) -> str:
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
        format: "text" (default) for an inline summary, or "html" to render a
                review-ready HTML impact report and return a shareable URL.
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

    if format.lower() == "html":
        return await _save_branch_diff_report(base_branch, compare_branch, diff)

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
async def create_xata_branch(
    connection_name: str, project: str, branch_name: str, parent_branch: str = "main"
) -> str:
    """
    Create an instant copy-on-write Xata branch off a parent branch.

    The new branch is a zero-copy fork of `parent_branch` (e.g. fork "staging" to
    get realistic data). Use it to apply and validate schema/dbt changes in
    isolation before a human merges to production. The gateway resolves the parent
    branch id and credentials server-side; you never see a URL or key.

    Args:
        connection_name: The Xata connection.
        project: The Xata project id.
        branch_name: Name for the new branch (e.g. "agent/dim_users_20260624").
        parent_branch: Branch to fork from (default "main"; prefer "staging").
    """
    no_xata = await _no_xata_db_msg()
    if no_xata:
        return no_xata
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    gw = _gateway_url()
    base = f"{gw}/api/connections/{connection_name}/xata/projects/{project}/branches"
    async with httpx.AsyncClient(timeout=120) as client:
        rb = await client.get(base, headers=_gw_headers())
        if rb.status_code != 200:
            return sanitize_proxy_response(rb.status_code, rb.text)
        parent = next((b for b in rb.json().get("branches", []) if b.get("name") == parent_branch), None)
        if not parent:
            return f"Parent branch '{parent_branch}' not found in project {project}."
        r = await client.post(
            base,
            json={"branch_name": branch_name, "parent_id": parent["id"]},
            headers=_gw_headers(),
        )
    if r.status_code != 200:
        return sanitize_proxy_response(r.status_code, r.text)
    d = r.json()
    # Never surface the connection string / credentials to the agent.
    return f"Created Xata branch '{d.get('name', branch_name)}' (id={(d.get('id') or '')[:12]}) forked from '{parent_branch}'."


@audited_tool(mcp)
async def delete_xata_branch(connection_name: str, project: str, branch_name: str) -> str:
    """
    Delete a Xata branch by name (cleanup after a merge is complete).

    Only call this once the developer has confirmed the change was merged to
    production. Deletion is permanent.

    Args:
        connection_name: The Xata connection.
        project: The Xata project id.
        branch_name: The branch to delete.
    """
    no_xata = await _no_xata_db_msg()
    if no_xata:
        return no_xata
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.delete(
            f"{gw}/api/connections/{connection_name}/xata/projects/{project}/branches/{branch_name}",
            headers=_gw_headers(),
        )
    if r.status_code not in (200, 204):
        return sanitize_proxy_response(r.status_code, r.text)
    return f"Deleted Xata branch '{branch_name}'."


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
