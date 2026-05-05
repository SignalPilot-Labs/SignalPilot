"""Notebook CRUD MCP tools: list, upload, update metadata, get, delete."""

from __future__ import annotations

import json
import re
import uuid

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.models.notebooks import NotebookUpload
from gateway.store.notebook_files import (
    _cell_source,
    _delete_notebook_file,
    _load_notebook_file,
    _parse_notebook,
    _save_notebook_file,
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_MAX_CELL_PREVIEW_CHARS = 500


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


__all__ = [
    "list_notebooks",
    "upload_notebook",
    "update_notebook_metadata",
    "get_notebook",
    "delete_notebook",
]
