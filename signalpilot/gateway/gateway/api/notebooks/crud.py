"""Notebook CRUD endpoints: upload, get, delete, update."""

from __future__ import annotations

import json
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from gateway.models.notebooks import NotebookInfo, NotebookUpdate, NotebookUpload
from gateway.security.scope_guard import RequireScope
from gateway.store.notebook_files import (
    _analyze_notebook_content,
    _delete_notebook_file,
    _parse_notebook,
    _save_notebook_file,
)

from ..deps import StoreD

router = APIRouter()

_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
NotebookIdP = Annotated[str, Path(pattern=_UUID_PATTERN)]


@router.post("/notebooks", status_code=201, dependencies=[RequireScope("write")])
async def upload_notebook(upload: NotebookUpload, store: StoreD) -> NotebookInfo:
    """Upload a Jupyter notebook. Saves file first, then inserts DB row."""
    try:
        nb = json.loads(upload.content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Invalid notebook JSON.")

    if not isinstance(nb, dict) or "cells" not in nb:
        raise HTTPException(status_code=422, detail="Content must be a valid Jupyter notebook (must have 'cells' key).")

    parsed = _parse_notebook(nb)
    analysis = _analyze_notebook_content(nb)
    analyzed_at = time.time()
    notebook_id = str(uuid.uuid4())

    _save_notebook_file(notebook_id, upload.content)

    try:
        info = await store.create_notebook(
            upload=upload,
            notebook_id=notebook_id,
            cell_count=parsed["cell_count"],
            code_cell_count=parsed["code_cell_count"],
            markdown_cell_count=parsed["markdown_cell_count"],
            kernel_name=parsed["kernel_name"],
        )
    except ValueError:
        _delete_notebook_file(notebook_id)
        raise HTTPException(status_code=409, detail="A notebook with this name already exists.")

    analysis_json = {**analysis, "notebook_id": notebook_id, "analyzed_at": analyzed_at}
    await store.update_notebook_analysis(
        notebook_id=notebook_id,
        analysis_json=analysis_json,
        analyzed_at=analyzed_at,
    )

    updated = await store.get_notebook_meta(notebook_id)
    try:
        await store.log_notebook_activity(notebook_id, "upload", {"name": info.name})
    except Exception:
        pass
    return updated or info


@router.get("/notebooks/{notebook_id}", dependencies=[RequireScope("read")])
async def get_notebook(notebook_id: NotebookIdP, store: StoreD) -> NotebookInfo:
    """Get notebook metadata by ID."""
    meta = await store.get_notebook_meta(notebook_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")
    return meta


@router.delete("/notebooks/{notebook_id}", status_code=204, dependencies=[RequireScope("write")])
async def delete_notebook(notebook_id: NotebookIdP, store: StoreD) -> None:
    """Delete a notebook. DB row is deleted first, then the file."""
    meta = await store.get_notebook_meta(notebook_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")
    notebook_name = meta.name
    deleted = await store.delete_notebook_meta(notebook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")
    _delete_notebook_file(notebook_id)
    try:
        await store.log_notebook_activity(notebook_id, "delete", {"name": notebook_name})
    except Exception:
        pass


@router.patch("/notebooks/{notebook_id}", dependencies=[RequireScope("write")])
async def update_notebook(notebook_id: NotebookIdP, update: NotebookUpdate, store: StoreD) -> NotebookInfo:
    """Update notebook metadata (name, description, tags). At least one field must be provided."""
    if update.name is None and update.description is None and update.tags is None:
        raise HTTPException(status_code=400, detail="At least one field must be provided.")
    try:
        result = await store.update_notebook_metadata(
            notebook_id,
            name=update.name,
            description=update.description,
            tags=update.tags,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if result is None:
        raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")
    changed: dict[str, object] = {}
    if update.name is not None:
        changed["name"] = update.name
    if update.description is not None:
        changed["description"] = update.description
    if update.tags is not None:
        changed["tags"] = update.tags
    try:
        await store.log_notebook_activity(notebook_id, "update", changed)
    except Exception:
        pass
    return result
