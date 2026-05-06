"""Notebook report MCP tool: compile a structured analysis report."""

from __future__ import annotations

import re

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.store.notebook_files import _build_report_data, _load_notebook_file, _now_iso

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

@audited_tool(mcp)
async def get_notebook_report(notebook_id: str) -> str:
    """
    Compile a full analysis report for a notebook: metadata, analysis summary, cell listing, and output types.

    Args:
        notebook_id: UUID of the notebook

    Returns:
        Formatted text report including notebook metadata, analysis summary (if available),
        cell listing (type, line count, has output — up to 50 cells), and output types breakdown.
    """
    if not _UUID_RE.match(notebook_id):
        return f"Error: Invalid notebook ID '{notebook_id}'."

    async with _store_session() as store:
        meta = await store.get_notebook_meta(notebook_id)
        if not meta:
            return f"Error: Notebook '{notebook_id}' not found."
        analysis_json = await store.get_notebook_analysis_json(notebook_id)

    nb_content = _load_notebook_file(notebook_id)
    if not nb_content:
        return f"Error: Notebook file for '{notebook_id}' not found."

    report_data = _build_report_data(
        analysis_json=analysis_json,
        nb_content=nb_content,
    )

    lines: list[str] = [
        "Notebook Report",
        f"Generated at: {_now_iso()}",
        "",
        "=== Notebook Metadata ===",
        f"  ID:          {meta.id}",
        f"  Name:        {meta.name}",
        f"  Description: {meta.description or '(none)'}",
        f"  Tags:        {', '.join(meta.tags) if meta.tags else '(none)'}",
        f"  Cells:       {meta.cell_count} total ({meta.code_cell_count} code, {meta.markdown_cell_count} markdown)",
        f"  Kernel:      {meta.kernel_name or 'unknown'}",
        f"  Created at:  {meta.created_at}",
        f"  Updated at:  {meta.updated_at}",
        f"  Analyzed at: {meta.analyzed_at or '(not analyzed)'}",
        "",
    ]

    if analysis_json is not None:
        lines += [
            "=== Analysis Summary ===",
            f"  Imports ({len(analysis_json.get('imports', []))}): "
            f"{', '.join(analysis_json.get('imports', [])[:20]) or '(none)'}",
            f"  Functions defined ({len(analysis_json.get('functions_defined', []))}): "
            f"{', '.join(analysis_json.get('functions_defined', [])[:20]) or '(none)'}",
            f"  Error cells: {analysis_json.get('error_cells', []) or '(none)'}",
            f"  Execution order gaps: {analysis_json.get('execution_order_gaps', []) or '(none)'}",
            f"  Total code lines: {analysis_json.get('total_code_lines', 0)}",
            f"  Output summary: {analysis_json.get('output_summary', {}) or '(none)'}",
            "",
        ]
    else:
        lines += ["=== Analysis Summary ===", "  (not yet analyzed)", ""]

    nb_format_meta = report_data["metadata"]
    lines += [
        "=== Format Metadata ===",
        f"  nbformat: {nb_format_meta['nbformat']}",
        f"  nbformat_minor: {nb_format_meta['nbformat_minor']}",
        f"  kernel_info: {nb_format_meta['kernel_info'] or 'unknown'}",
        "",
    ]

    cell_details: list[dict] = report_data["cell_details"]
    total_cells = len(nb_content.get("cells", []))
    shown = len(cell_details)
    lines += [
        f"=== Cell Listing (showing {shown} of {total_cells}) ===",
    ]
    for cell in cell_details:
        output_flag = " [has output]" if cell["has_output"] else ""
        exec_info = f" exec#{cell['execution_count']}" if cell["execution_count"] is not None else ""
        lines.append(
            f"  [{cell['index']}] {cell['cell_type']}{exec_info} "
            f"— {cell['source_line_count']} line(s){output_flag}"
        )

    outputs_summary = report_data["outputs_summary"]
    lines += [
        "",
        "=== Outputs Summary ===",
        f"  Total outputs: {outputs_summary['total_outputs']}",
    ]
    for out_type, count in outputs_summary["by_type"].items():
        lines.append(f"  {out_type}: {count}")

    return "\n".join(lines)


__all__ = ["get_notebook_report"]
