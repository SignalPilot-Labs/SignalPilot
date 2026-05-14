"""Notebook batch endpoints: batch analyze, batch delete."""

from __future__ import annotations

import time

from fastapi import APIRouter

from gateway.models.notebooks import BatchNotebookRequest, BatchResult, BatchResultItem
from gateway.security.scope_guard import RequireScope
from gateway.store.notebook_files import (
    _analyze_notebook_content,
    _delete_notebook_file,
    _load_notebook_file,
)

from ..deps import StoreD

router = APIRouter()


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
