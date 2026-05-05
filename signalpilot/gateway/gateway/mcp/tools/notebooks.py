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
async def get_notebooks_summary() -> str:
    """
    Get aggregate statistics across all notebooks: totals, analysis status, error counts, and top imports.

    Returns:
        Summary text with total notebooks, cells, analysis status breakdown, error counts, and top imports.
    """
    async with _store_session() as store:
        summary = await store.get_notebooks_summary()

    lines = [
        "Notebooks summary:",
        f"  Total notebooks: {summary.total_notebooks}",
        f"  Total cells: {summary.total_cells} ({summary.total_code_cells} code, {summary.total_markdown_cells} markdown)",
        f"  Total code lines: {summary.total_code_lines}",
        f"  Analyzed: {summary.analyzed_count} | Pending: {summary.pending_count}",
        f"  Notebooks with errors: {summary.notebooks_with_errors}",
        f"  Total error cells: {summary.total_error_cells}",
        f"  Top imports: {', '.join(summary.top_imports[:10]) if summary.top_imports else '(none)'}",
    ]
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
async def update_notebook_metadata(
    notebook_id: str,
    name: str = "",
    description: str = "",
    tags: str = "",
) -> str:
    """
    Update notebook metadata: name, description, and/or tags.

    Args:
        notebook_id: UUID of the notebook to update
        name: New notebook name (1-120 characters). Leave empty to keep current.
        description: New description (max 500 characters). Leave empty to keep current.
        tags: Comma-separated list of tags. Leave empty to keep current tags.

    Returns:
        Confirmation with updated fields, or an error message.
    """
    if not _UUID_RE.match(notebook_id):
        return f"Error: Invalid notebook ID '{notebook_id}'."

    name_val = name.strip() if name else ""
    description_val = description.strip() if description else ""
    tags_val = tags.strip() if tags else ""

    if not name_val and not description_val and not tags_val:
        return "Error: At least one field must be provided."

    name_arg: str | None = None
    if name_val:
        if len(name_val) > 120:
            return "Error: Name must be between 1 and 120 characters."
        name_arg = name_val

    description_arg: str | None = None
    if description_val:
        if len(description_val) > 500:
            return "Error: Description must be under 500 characters."
        description_arg = description_val

    tags_arg: list[str] | None = None
    if tags_val:
        tags_arg = [t.strip() for t in tags_val.split(",") if t.strip()]

    async with _store_session() as store:
        try:
            info = await store.update_notebook_metadata(
                notebook_id,
                name=name_arg,
                description=description_arg,
                tags=tags_arg,
            )
        except ValueError as e:
            return f"Error: {e}"

    if info is None:
        return "Notebook not found."

    updated_fields = []
    if name_arg is not None:
        updated_fields.append(f"name: {info.name}")
    if description_arg is not None:
        updated_fields.append(f"description: {info.description}")
    if tags_arg is not None:
        updated_fields.append(f"tags: {', '.join(info.tags) if info.tags else '(none)'}")

    return (
        f"Notebook '{notebook_id}' updated.\n"
        + "\n".join(f"  {f}" for f in updated_fields)
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
async def get_notebook_file(notebook_id: str) -> str:
    """
    Get the raw .ipynb JSON content of a notebook file.

    Args:
        notebook_id: UUID of the notebook

    Returns:
        The full notebook JSON content as a string, suitable for saving as .ipynb.
    """
    if not _UUID_RE.match(notebook_id):
        return f"Error: Invalid notebook ID '{notebook_id}'."

    nb = _load_notebook_file(notebook_id)
    if not nb:
        return f"Error: Notebook '{notebook_id}' not found."

    return json.dumps(nb, indent=1)


@audited_tool(mcp)
async def search_notebooks(query: str, limit: int = 50, offset: int = 0) -> str:
    """
    Search notebooks by name, description, or tags.

    Args:
        query: Search string (case-insensitive)
        limit: Maximum number of results to return (default 50, max 100)
        offset: Number of results to skip for pagination (default 0)

    Returns:
        Matching notebooks with IDs and metadata.
    """
    query = query.strip()
    if not query:
        return "Error: Query must not be empty."

    async with _store_session() as store:
        results = await store.search_notebooks(query=query, limit=limit, offset=offset)

    if not results:
        return f"No notebooks found matching '{query}'."

    if offset > 0:
        header = f"Found {len(results)} notebook(s) matching '{query}' (showing from offset {offset}):\n"
    else:
        header = f"Found {len(results)} notebook(s) matching '{query}':\n"

    lines = [header]
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
