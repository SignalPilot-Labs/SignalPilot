"""Notebook management MCP tools: list, upload, get, analyze, search, delete."""

from __future__ import annotations

import json
import re
import time
import uuid

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.models.notebooks import NotebookUpload
from gateway.store.notebook_files import (
    _analyze_notebook_content,
    _cell_source,
    _delete_notebook_file,
    _load_notebook_file,
    _now_iso,
    _parse_notebook,
    _save_notebook_file,
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_MAX_CELL_PREVIEW_CHARS = 500
_MAX_OUTPUT_CHARS = 1000


@audited_tool(mcp)
async def list_notebooks() -> str:
    """
    List all uploaded notebooks.

    Returns:
        Notebook names, IDs, cell counts, and last updated timestamps.
    """
    async with _store_session() as store:
        notebooks = await store.list_notebooks()
    if not notebooks:
        return "No notebooks found. Use upload_notebook to add one."
    lines = [f"Found {len(notebooks)} notebook(s):\n"]
    for nb in notebooks:
        lines.append(
            f"  - {nb.name} (id: {nb.id}, {nb.cell_count} cells, "
            f"{nb.code_cell_count} code, updated: {nb.updated_at})"
        )
    return "\n".join(lines)


@audited_tool(mcp)
async def upload_notebook(name: str, content: str, description: str = "", tags: str = "") -> str:
    """
    Upload a Jupyter notebook (.ipynb JSON) to SignalPilot.

    Args:
        name: Notebook name (1-120 characters)
        content: Raw .ipynb JSON string
        description: Optional description (max 500 characters)
        tags: Comma-separated list of tags (optional)

    Returns:
        Notebook ID and confirmation.
    """
    name = name.strip()
    if not name or len(name) > 120:
        return "Error: Name must be between 1 and 120 characters."
    description = description.strip()
    if len(description) > 500:
        return "Error: Description must be under 500 characters."

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    try:
        nb = json.loads(content)
    except json.JSONDecodeError as e:
        return f"Error: Invalid notebook JSON: {e}"

    if not isinstance(nb, dict) or "cells" not in nb:
        return "Error: Content must be a valid Jupyter notebook (must have 'cells' key)."

    parsed = _parse_notebook(nb)
    notebook_id = str(uuid.uuid4())

    upload = NotebookUpload(
        name=name,
        content=content,
        description=description,
        tags=tag_list,
    )

    _save_notebook_file(notebook_id, content)

    async with _store_session() as store:
        try:
            info = await store.create_notebook(
                upload=upload,
                notebook_id=notebook_id,
                cell_count=parsed["cell_count"],
                code_cell_count=parsed["code_cell_count"],
                markdown_cell_count=parsed["markdown_cell_count"],
                kernel_name=parsed["kernel_name"],
            )
        except ValueError as e:
            _delete_notebook_file(notebook_id)
            return f"Error: {e}"

    return (
        f"Notebook uploaded: {info.id}\n"
        f"Name: {info.name}\n"
        f"Cells: {info.cell_count} ({info.code_cell_count} code, "
        f"{info.markdown_cell_count} markdown)"
    )


@audited_tool(mcp)
async def get_notebook(notebook_id: str) -> str:
    """
    Get a summary of a notebook including metadata and a preview of its cells.

    Args:
        notebook_id: UUID of the notebook

    Returns:
        Notebook metadata and truncated cell previews.
    """
    if not _UUID_RE.match(notebook_id):
        return f"Error: Invalid notebook ID '{notebook_id}'."

    async with _store_session() as store:
        meta = await store.get_notebook_meta(notebook_id)
    if not meta:
        return f"Error: Notebook '{notebook_id}' not found."

    nb = _load_notebook_file(notebook_id)
    if not nb:
        return f"Error: Notebook file for '{notebook_id}' not found."

    cells = nb.get("cells", [])
    lines = [
        f"Notebook: {meta.name}",
        f"ID: {meta.id}",
        f"Description: {meta.description}",
        f"Tags: {', '.join(meta.tags) if meta.tags else '(none)'}",
        f"Kernel: {meta.kernel_name or 'unknown'}",
        f"Cells: {meta.cell_count} ({meta.code_cell_count} code, {meta.markdown_cell_count} markdown)",
        f"Updated: {meta.updated_at}",
        f"Analyzed: {meta.analyzed_at or 'not yet analyzed'}",
        "",
        f"Cell preview (first {min(5, len(cells))} cells):",
    ]
    for i, cell in enumerate(cells[:5]):
        cell_type = cell.get("cell_type", "unknown")
        source = _cell_source(cell)
        preview = source[:_MAX_CELL_PREVIEW_CHARS]
        if len(source) > _MAX_CELL_PREVIEW_CHARS:
            preview += "..."
        lines.append(f"\n  [{i}] ({cell_type}): {preview}")

    return "\n".join(lines)


@audited_tool(mcp)
async def get_notebook_cell(notebook_id: str, cell_index: int = -1, cell_type: str = "") -> str:
    """
    Get specific cell(s) from a notebook.

    Args:
        notebook_id: UUID of the notebook
        cell_index: Zero-based cell index to retrieve. Use -1 to retrieve all cells.
        cell_type: Filter by cell type: "code", "markdown", or "raw". Empty means no filter.

    Returns:
        Cell source and metadata. If cell_index >= 0, returns that single cell.
        If cell_type is set, returns all cells of that type.
        If neither, returns all cells with their indices.
    """
    if not _UUID_RE.match(notebook_id):
        return f"Error: Invalid notebook ID '{notebook_id}'."

    nb = _load_notebook_file(notebook_id)
    if not nb:
        return f"Error: Notebook '{notebook_id}' not found."

    cells = nb.get("cells", [])

    if cell_index >= 0:
        if cell_index >= len(cells):
            return f"Error: Cell index {cell_index} out of range (notebook has {len(cells)} cells)."
        cell = cells[cell_index]
        source = _cell_source(cell)
        exec_count = cell.get("execution_count", "")
        return (
            f"Cell [{cell_index}] ({cell.get('cell_type', 'unknown')})"
            + (f" exec#{exec_count}" if exec_count else "")
            + f":\n{source}"
        )

    filtered = [
        (i, c) for i, c in enumerate(cells)
        if not cell_type or c.get("cell_type") == cell_type
    ]

    if not filtered:
        type_msg = f" of type '{cell_type}'" if cell_type else ""
        return f"No cells{type_msg} found in notebook '{notebook_id}'."

    lines = [f"Found {len(filtered)} cell(s):\n"]
    for i, cell in filtered:
        cell_type_val = cell.get("cell_type", "unknown")
        source = _cell_source(cell)
        preview = source[:_MAX_CELL_PREVIEW_CHARS]
        if len(source) > _MAX_CELL_PREVIEW_CHARS:
            preview += "..."
        lines.append(f"  [{i}] ({cell_type_val}): {preview}\n")

    return "\n".join(lines)


@audited_tool(mcp)
async def analyze_notebook(notebook_id: str) -> str:
    """
    Analyze a notebook: scan imports, detect errors, summarize outputs, find function definitions.

    Args:
        notebook_id: UUID of the notebook

    Returns:
        Formatted analysis text including imports, errors, execution gaps, and output summary.
    """
    if not _UUID_RE.match(notebook_id):
        return f"Error: Invalid notebook ID '{notebook_id}'."

    nb = _load_notebook_file(notebook_id)
    if not nb:
        return f"Error: Notebook '{notebook_id}' not found."

    analysis = _analyze_notebook_content(nb)
    analyzed_at = time.time()
    analysis_json = {**analysis, "notebook_id": notebook_id, "analyzed_at": analyzed_at}

    async with _store_session() as store:
        await store.update_notebook_analysis(
            notebook_id=notebook_id,
            analysis_json=analysis_json,
            analyzed_at=analyzed_at,
        )

    lines = [
        f"Analysis for notebook: {notebook_id}",
        f"Analyzed at: {_now_iso()}",
        "",
        f"Cell counts: {analysis['cell_counts']}",
        f"Total code lines: {analysis['total_code_lines']}",
        f"Imports ({len(analysis['imports'])}): {', '.join(analysis['imports'][:20]) or '(none)'}",
        f"Functions defined ({len(analysis['functions_defined'])}): "
        f"{', '.join(analysis['functions_defined'][:20]) or '(none)'}",
        f"Error cells (indices): {analysis['error_cells'] or '(none)'}",
        f"Execution order gaps: {analysis['execution_order_gaps'] or '(none)'}",
        f"Output summary: {analysis['output_summary'] or '(none)'}",
        f"Kernel: {analysis['kernel_info'] or 'unknown'}",
    ]
    return "\n".join(lines)


@audited_tool(mcp)
async def get_notebook_outputs(notebook_id: str) -> str:
    """
    Get all cell outputs from a notebook, including text, errors, and image placeholders.

    Args:
        notebook_id: UUID of the notebook

    Returns:
        Formatted text of all code cell outputs.
    """
    if not _UUID_RE.match(notebook_id):
        return f"Error: Invalid notebook ID '{notebook_id}'."

    nb = _load_notebook_file(notebook_id)
    if not nb:
        return f"Error: Notebook '{notebook_id}' not found."

    cells = nb.get("cells", [])
    lines = []

    for i, cell in enumerate(cells):
        if cell.get("cell_type") != "code":
            continue
        outputs = cell.get("outputs", [])
        if not outputs:
            continue
        lines.append(f"Cell [{i}] outputs:")
        for output in outputs:
            output_type = output.get("output_type", "unknown")
            if output_type in ("stream", "display_data", "execute_result"):
                text_data = output.get("text", output.get("data", {}).get("text/plain", ""))
                if isinstance(text_data, list):
                    text_data = "".join(text_data)
                text_data = text_data[:_MAX_OUTPUT_CHARS]
                if output.get("data") and "image/png" in output["data"]:
                    lines.append(f"  [{output_type}]: [image: image/png]")
                elif output.get("data") and "image/svg+xml" in output["data"]:
                    lines.append(f"  [{output_type}]: [image: image/svg+xml]")
                else:
                    lines.append(f"  [{output_type}]: {text_data}")
            elif output_type == "error":
                ename = output.get("ename", "Error")
                evalue = output.get("evalue", "")
                traceback = output.get("traceback", [])
                tb_str = "\n".join(traceback[:5]) if traceback else ""
                lines.append(f"  [error] {ename}: {evalue}")
                if tb_str:
                    lines.append(f"  Traceback:\n{tb_str[:_MAX_OUTPUT_CHARS]}")
            else:
                lines.append(f"  [{output_type}]")

    if not lines:
        return f"No outputs found in notebook '{notebook_id}'."
    return "\n".join(lines)


@audited_tool(mcp)
async def search_notebooks(query: str) -> str:
    """
    Search notebooks by name, description, or tags.

    Args:
        query: Search string (case-insensitive)

    Returns:
        Matching notebooks with IDs and metadata.
    """
    query = query.strip()
    if not query:
        return "Error: Query must not be empty."

    async with _store_session() as store:
        results = await store.search_notebooks(query=query, limit=50, offset=0)

    if not results:
        return f"No notebooks found matching '{query}'."

    lines = [f"Found {len(results)} notebook(s) matching '{query}':\n"]
    for nb in results:
        lines.append(
            f"  - {nb.name} (id: {nb.id}, {nb.cell_count} cells, updated: {nb.updated_at})"
        )
    return "\n".join(lines)


@audited_tool(mcp)
async def delete_notebook(notebook_id: str) -> str:
    """
    Delete a notebook and its file.

    Args:
        notebook_id: UUID of the notebook to delete

    Returns:
        Confirmation message.
    """
    if not _UUID_RE.match(notebook_id):
        return f"Error: Invalid notebook ID '{notebook_id}'."

    async with _store_session() as store:
        deleted = await store.delete_notebook_meta(notebook_id)

    if not deleted:
        return f"Error: Notebook '{notebook_id}' not found."

    _delete_notebook_file(notebook_id)
    return f"Notebook '{notebook_id}' deleted."
