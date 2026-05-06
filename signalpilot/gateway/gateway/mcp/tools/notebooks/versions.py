"""Notebook version history MCP tool: retrieve analysis metric snapshots over time."""

from __future__ import annotations

import re

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_LIMIT_DEFAULT = 50


def _format_delta(current: int, previous: int, label: str, lower_is_better: bool) -> str:
    """Return a formatted delta string with direction indicator."""
    diff = current - previous
    if diff == 0:
        return ""
    sign = "+" if diff > 0 else ""
    improvement = (diff < 0) if lower_is_better else (diff > 0)
    direction = "improvement" if improvement else "regression"
    return f" ({sign}{diff} {label} — {direction})"


@audited_tool(mcp)
async def get_notebook_versions(notebook_id: str, limit: int = _LIMIT_DEFAULT) -> str:
    """
    Retrieve version history for a notebook, showing how analysis metrics evolved over time.

    Args:
        notebook_id: UUID of the notebook
        limit: Maximum number of versions to return (default 50, max 100)

    Returns:
        Formatted text listing of version snapshots with metrics and deltas.
    """
    if not _UUID_RE.match(notebook_id):
        return f"Error: Invalid notebook ID '{notebook_id}'."

    async with _store_session() as store:
        meta = await store.get_notebook_meta(notebook_id)
        if not meta:
            return f"Error: Notebook '{notebook_id}' not found."
        versions = await store.list_notebook_versions(notebook_id, limit=limit, offset=0)
        total = await store.count_notebook_versions(notebook_id)

    if not versions:
        return f"No version history recorded for notebook '{meta.name}'."

    lines: list[str] = [
        f"Version history for: {meta.name}",
        f"Showing {len(versions)} of {total} version(s)",
        "",
    ]
    for i, ver in enumerate(versions):
        prev = versions[i + 1] if i + 1 < len(versions) else None
        lines.append(f"  v{ver.version_number} — analyzed at {ver.analyzed_at}")
        lines.append(f"    cells: {ver.total_cells} total, {ver.code_cells} code, {ver.markdown_cells} markdown")
        error_delta = (
            _format_delta(ver.error_cells, prev.error_cells, "error cell(s)", lower_is_better=True)
            if prev is not None
            else ""
        )
        lines.append(f"    error cells: {ver.error_cells}{error_delta}")
        code_lines_delta = (
            _format_delta(ver.total_code_lines, prev.total_code_lines, "line(s)", lower_is_better=False)
            if prev is not None
            else ""
        )
        lines.append(f"    code lines: {ver.total_code_lines}{code_lines_delta}")
        funcs_delta = (
            _format_delta(ver.functions_count, prev.functions_count, "function(s)", lower_is_better=False)
            if prev is not None
            else ""
        )
        lines.append(f"    functions: {ver.functions_count}{funcs_delta}")
        imports_delta = (
            _format_delta(ver.imports_count, prev.imports_count, "import(s)", lower_is_better=False)
            if prev is not None
            else ""
        )
        lines.append(f"    imports: {ver.imports_count}{imports_delta}")

    return "\n".join(lines)


__all__ = ["get_notebook_versions"]
