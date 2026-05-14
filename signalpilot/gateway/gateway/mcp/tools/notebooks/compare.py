"""Notebook comparison MCP tool: diff two notebooks side-by-side."""

from __future__ import annotations

import re

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.store.notebook_files import _load_notebook_file, _now_iso, build_notebook_comparison

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_MAX_CELL_LINES = 50


@audited_tool(mcp)
async def compare_notebooks(notebook_id: str, other_notebook_id: str) -> str:
    """
    Compare two notebooks side-by-side, showing cell-level diffs and analysis differences.

    Args:
        notebook_id: UUID of the left (base) notebook
        other_notebook_id: UUID of the right (comparison) notebook

    Returns:
        Formatted text showing metadata diff, analysis diff, cell summary, and per-cell status.
    """
    if not _UUID_RE.match(notebook_id):
        return f"Error: Invalid notebook ID '{notebook_id}'."
    if not _UUID_RE.match(other_notebook_id):
        return f"Error: Invalid notebook ID '{other_notebook_id}'."
    if notebook_id == other_notebook_id:
        return "Error: Cannot compare a notebook with itself."

    async with _store_session() as store:
        left_meta = await store.get_notebook_meta(notebook_id)
        if not left_meta:
            return f"Error: Notebook '{notebook_id}' not found."

        right_meta = await store.get_notebook_meta(other_notebook_id)
        if not right_meta:
            return f"Error: Notebook '{other_notebook_id}' not found."

        left_analysis_json = await store.get_notebook_analysis_json(notebook_id)
        right_analysis_json = await store.get_notebook_analysis_json(other_notebook_id)

    left_nb = _load_notebook_file(notebook_id)
    if not left_nb:
        return f"Error: Notebook file for '{notebook_id}' not found."

    right_nb = _load_notebook_file(other_notebook_id)
    if not right_nb:
        return f"Error: Notebook file for '{other_notebook_id}' not found."

    comparison = build_notebook_comparison(
        left_meta=left_meta,
        right_meta=right_meta,
        left_nb=left_nb,
        right_nb=right_nb,
        left_analysis=left_analysis_json,
        right_analysis=right_analysis_json,
    )

    lines: list[str] = [
        "Notebook Comparison",
        f"Generated at: {_now_iso()}",
        "",
        "=== Notebooks ===",
        f"  LEFT  [{left_meta.id}]  {left_meta.name}",
        f"  RIGHT [{right_meta.id}]  {right_meta.name}",
        "",
        "=== Metadata ===",
        f"  Cells:       LEFT {left_meta.cell_count}  vs  RIGHT {right_meta.cell_count}",
        f"  Code cells:  LEFT {left_meta.code_cell_count}  vs  RIGHT {right_meta.code_cell_count}",
        f"  MD cells:    LEFT {left_meta.markdown_cell_count}  vs  RIGHT {right_meta.markdown_cell_count}",
        f"  Kernel:      LEFT {left_meta.kernel_name or 'unknown'}  vs  RIGHT {right_meta.kernel_name or 'unknown'}",
        "",
    ]

    s = comparison.summary
    lines += [
        "=== Cell Summary ===",
        f"  Added:     {s.added}",
        f"  Removed:   {s.removed}",
        f"  Modified:  {s.modified}",
        f"  Unchanged: {s.unchanged}",
        "",
    ]

    if comparison.analysis is not None:
        a = comparison.analysis
        lines += [
            "=== Analysis Diff ===",
            f"  Left imports ({len(a.left_imports)}):    {', '.join(a.left_imports[:10]) or '(none)'}",
            f"  Right imports ({len(a.right_imports)}):  {', '.join(a.right_imports[:10]) or '(none)'}",
            f"  Added imports:   {', '.join(a.added_imports) or '(none)'}",
            f"  Removed imports: {', '.join(a.removed_imports) or '(none)'}",
            f"  Left functions ({len(a.left_functions)}):    {', '.join(a.left_functions[:10]) or '(none)'}",
            f"  Right functions ({len(a.right_functions)}):  {', '.join(a.right_functions[:10]) or '(none)'}",
            f"  Added functions:   {', '.join(a.added_functions) or '(none)'}",
            f"  Removed functions: {', '.join(a.removed_functions) or '(none)'}",
            f"  Left error cells:  {a.left_error_cells or '(none)'}",
            f"  Right error cells: {a.right_error_cells or '(none)'}",
            f"  Code lines:  LEFT {a.left_code_lines}  vs  RIGHT {a.right_code_lines}",
            "",
        ]
    else:
        lines += ["=== Analysis Diff ===", "  (one or both notebooks not yet analyzed)", ""]

    total_diffs = len(comparison.cell_diffs)
    shown = comparison.cell_diffs[:_MAX_CELL_LINES]
    lines += [f"=== Cell Diffs (showing {len(shown)} of {total_diffs}) ==="]
    for diff in shown:
        left_info = f"{diff.left_type or '-'} {diff.left_source_lines or 0}L" if diff.left_source_lines is not None else "-"
        right_info = f"{diff.right_type or '-'} {diff.right_source_lines or 0}L" if diff.right_source_lines is not None else "-"
        lines.append(f"  [{diff.index}] {diff.status.upper():10s}  LEFT: {left_info}  RIGHT: {right_info}")

    return "\n".join(lines)


__all__ = ["compare_notebooks"]
