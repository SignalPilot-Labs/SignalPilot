"""Notebook CRUD and analysis REST API endpoints."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response

from gateway.models.notebooks import (
    BatchNotebookRequest,
    BatchResult,
    BatchResultItem,
    NotebookAnalysis,
    NotebookInfo,
    NotebookSummary,
    NotebookUpdate,
    NotebookUpload,
)
from gateway.security.scope_guard import RequireScope
from gateway.store.notebook_files import (
    _analyze_notebook_content,
    _delete_notebook_file,
    _load_notebook_file,
    _load_notebook_file_raw,
    _parse_notebook,
    _save_notebook_file,
)

from .deps import StoreD

router = APIRouter(prefix="/api")

_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
NotebookIdP = Annotated[str, Path(pattern=_UUID_PATTERN)]


@router.get("/notebooks", dependencies=[RequireScope("read")])
async def list_notebooks(
    store: StoreD,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List all notebooks with pagination."""
    items, total = await asyncio.gather(
        store.list_notebooks(limit=limit, offset=offset),
        store.count_notebooks(),
    )
    return {"items": items, "total": total}


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
    return updated or info


@router.get("/notebooks/search", dependencies=[RequireScope("read")])
async def search_notebooks(
    store: StoreD,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Search notebooks by name, description, or tags."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' must not be empty.")
    results, total = await asyncio.gather(
        store.search_notebooks(query=q, limit=limit, offset=offset),
        store.count_search_notebooks(query=q),
    )
    return {"items": results, "total": total}


@router.get("/notebooks/summary", dependencies=[RequireScope("read")])
async def get_notebooks_summary(store: StoreD) -> NotebookSummary:
    """Get aggregate statistics across all notebooks."""
    return await store.get_notebooks_summary()


@router.post("/notebooks/batch/analyze", dependencies=[RequireScope("write")])
async def batch_analyze_notebooks(body: BatchNotebookRequest, store: StoreD) -> BatchResult:
    """Analyze multiple notebooks in a single request. Returns per-ID results."""
    existing_ids = set(await store.batch_get_notebook_ids(body.notebook_ids))
    results: list[BatchResultItem] = []

    for notebook_id in body.notebook_ids:
        if notebook_id not in existing_ids:
            results.append(BatchResultItem(notebook_id=notebook_id, success=False, error="not found"))
            continue

        nb = _load_notebook_file(notebook_id)
        if not nb:
            results.append(BatchResultItem(notebook_id=notebook_id, success=False, error="file not found"))
            continue

        analysis = _analyze_notebook_content(nb)
        analyzed_at = time.time()
        analysis_json = {**analysis, "notebook_id": notebook_id, "analyzed_at": analyzed_at}
        await store.update_notebook_analysis(
            notebook_id=notebook_id,
            analysis_json=analysis_json,
            analyzed_at=analyzed_at,
        )
        results.append(BatchResultItem(notebook_id=notebook_id, success=True))

    succeeded = sum(1 for r in results if r.success)
    return BatchResult(results=results, succeeded=succeeded, failed=len(results) - succeeded)


@router.post("/notebooks/batch/delete", dependencies=[RequireScope("write")])
async def batch_delete_notebooks(body: BatchNotebookRequest, store: StoreD) -> BatchResult:
    """Delete multiple notebooks in a single request. Returns per-ID results."""
    db_results = await store.batch_delete_notebooks(body.notebook_ids)
    results: list[BatchResultItem] = []

    for notebook_id, success, error in db_results:
        if success:
            _delete_notebook_file(notebook_id)
        results.append(BatchResultItem(notebook_id=notebook_id, success=success, error=error))

    succeeded = sum(1 for r in results if r.success)
    return BatchResult(results=results, succeeded=succeeded, failed=len(results) - succeeded)


@router.get("/notebooks/{notebook_id}", dependencies=[RequireScope("read")])
async def get_notebook(notebook_id: NotebookIdP, store: StoreD) -> NotebookInfo:
    """Get notebook metadata by ID."""
    meta = await store.get_notebook_meta(notebook_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")
    return meta


@router.get("/notebooks/{notebook_id}/download", dependencies=[RequireScope("read")])
async def download_notebook(notebook_id: NotebookIdP, store: StoreD) -> Response:
    """Download the raw .ipynb file."""
    meta = await store.get_notebook_meta(notebook_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")
    content = _load_notebook_file_raw(notebook_id)
    if not content:
        raise HTTPException(status_code=404, detail=f"Notebook file for '{notebook_id}' not found")
    safe_name = meta.name.replace('"', "'").replace("\r", "").replace("\n", "")
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.ipynb"'},
    )


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
    return result


@router.get("/notebooks/{notebook_id}/cells", dependencies=[RequireScope("read")])
async def get_notebook_cells(
    notebook_id: NotebookIdP,
    store: StoreD,
    cell_type: str | None = None,
    cell_index: int | None = None,
) -> list[dict]:
    """Get cells from a notebook, optionally filtered by type or index."""
    meta = await store.get_notebook_meta(notebook_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")

    nb = _load_notebook_file(notebook_id)
    if not nb:
        raise HTTPException(status_code=404, detail=f"Notebook file for '{notebook_id}' not found")

    cells = nb.get("cells", [])

    if cell_index is not None:
        if cell_index < 0 or cell_index >= len(cells):
            raise HTTPException(
                status_code=400,
                detail=f"Cell index {cell_index} out of range (notebook has {len(cells)} cells).",
            )
        return [{"index": cell_index, **cells[cell_index]}]

    if cell_type is not None:
        return [{"index": i, **c} for i, c in enumerate(cells) if c.get("cell_type") == cell_type]

    return [{"index": i, **c} for i, c in enumerate(cells)]


@router.get("/notebooks/{notebook_id}/analysis", dependencies=[RequireScope("read")])
async def get_notebook_analysis(notebook_id: NotebookIdP, store: StoreD) -> NotebookAnalysis:
    """Get cached analysis for a notebook. Returns 404 if not yet analyzed."""
    analysis_json = await store.get_notebook_analysis_json(notebook_id)
    if analysis_json is None:
        meta = await store.get_notebook_meta(notebook_id)
        if not meta:
            raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")
        raise HTTPException(status_code=404, detail="Not yet analyzed")

    aj = analysis_json
    return NotebookAnalysis(
        notebook_id=notebook_id,
        cell_counts=aj.get("cell_counts", {}),
        imports=aj.get("imports", []),
        execution_order_gaps=aj.get("execution_order_gaps", []),
        error_cells=aj.get("error_cells", []),
        output_summary=aj.get("output_summary", {}),
        total_code_lines=aj.get("total_code_lines", 0),
        functions_defined=aj.get("functions_defined", []),
        kernel_info=aj.get("kernel_info"),
        analyzed_at=aj.get("analyzed_at", time.time()),
    )


@router.post("/notebooks/{notebook_id}/analyze", dependencies=[RequireScope("write")])
async def analyze_notebook(notebook_id: NotebookIdP, store: StoreD) -> NotebookAnalysis:
    """Run analysis on a notebook and store results."""
    meta = await store.get_notebook_meta(notebook_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")

    nb = _load_notebook_file(notebook_id)
    if not nb:
        raise HTTPException(status_code=404, detail=f"Notebook file for '{notebook_id}' not found")

    analysis = _analyze_notebook_content(nb)
    analyzed_at = time.time()
    analysis_json = {**analysis, "notebook_id": notebook_id, "analyzed_at": analyzed_at}

    await store.update_notebook_analysis(
        notebook_id=notebook_id,
        analysis_json=analysis_json,
        analyzed_at=analyzed_at,
    )

    return NotebookAnalysis(
        notebook_id=notebook_id,
        analyzed_at=analyzed_at,
        **analysis,
    )


@router.delete("/notebooks/{notebook_id}", status_code=204, dependencies=[RequireScope("write")])
async def delete_notebook(notebook_id: NotebookIdP, store: StoreD) -> None:
    """Delete a notebook. DB row is deleted first, then the file."""
    deleted = await store.delete_notebook_meta(notebook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")
    _delete_notebook_file(notebook_id)
