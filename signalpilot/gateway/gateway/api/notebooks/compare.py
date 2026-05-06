"""Notebook compare endpoint: side-by-side comparison of two notebooks."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from gateway.models.notebooks import NotebookComparison
from gateway.security.scope_guard import RequireScope
from gateway.store.notebook_files import _load_notebook_file, build_notebook_comparison

from ..deps import StoreD
from .crud import NotebookIdP

router = APIRouter()


@router.get("/notebooks/{notebook_id}/compare/{other_id}", dependencies=[RequireScope("read")])
async def compare_notebooks(
    notebook_id: NotebookIdP,
    other_id: NotebookIdP,
    store: StoreD,
) -> NotebookComparison:
    """Compare two notebooks side-by-side, returning cell-level diffs and analysis differences."""
    if notebook_id == other_id:
        raise HTTPException(status_code=400, detail="Cannot compare a notebook with itself.")

    left_meta = await store.get_notebook_meta(notebook_id)
    if not left_meta:
        raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")

    right_meta = await store.get_notebook_meta(other_id)
    if not right_meta:
        raise HTTPException(status_code=404, detail=f"Notebook '{other_id}' not found")

    left_analysis_json = await store.get_notebook_analysis_json(notebook_id)
    right_analysis_json = await store.get_notebook_analysis_json(other_id)

    left_nb = _load_notebook_file(notebook_id)
    if not left_nb:
        raise HTTPException(status_code=404, detail=f"Notebook file for '{notebook_id}' not found")

    right_nb = _load_notebook_file(other_id)
    if not right_nb:
        raise HTTPException(status_code=404, detail=f"Notebook file for '{other_id}' not found")

    result = build_notebook_comparison(
        left_meta=left_meta,
        right_meta=right_meta,
        left_nb=left_nb,
        right_nb=right_nb,
        left_analysis=left_analysis_json,
        right_analysis=right_analysis_json,
    )
    try:
        await store.log_notebook_activity(notebook_id, "compare", {"other_id": other_id})
    except Exception:
        pass
    return result
