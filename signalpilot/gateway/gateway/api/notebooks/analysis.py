"""Notebook analysis endpoints: summary, analyze, get analysis, cells, report."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from gateway.models.notebooks import (
    NotebookAnalysis,
    NotebookReport,
    NotebookReportCell,
    NotebookReportMetadata,
    NotebookReportOutputsSummary,
    NotebookSummary,
)
from gateway.security.scope_guard import RequireScope
from gateway.store.notebook_files import (
    _analyze_notebook_content,
    _build_report_data,
    _load_notebook_file,
)

from ..deps import StoreD
from .crud import NotebookIdP

router = APIRouter()


@router.get("/notebooks/summary", dependencies=[RequireScope("read")])
async def get_notebooks_summary(store: StoreD) -> NotebookSummary:
    """Get aggregate statistics across all notebooks."""
    return await store.get_notebooks_summary()


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

    try:
        await store.log_notebook_activity(
            notebook_id, "analyze", {"reanalysis": meta.analyzed_at is not None}
        )
    except Exception:
        pass

    return NotebookAnalysis(
        notebook_id=notebook_id,
        analyzed_at=analyzed_at,
        **analysis,
    )


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


@router.get("/notebooks/{notebook_id}/report", dependencies=[RequireScope("read")])
async def get_notebook_report(notebook_id: NotebookIdP, store: StoreD) -> NotebookReport:
    """Get a structured analysis report for a notebook, including cell details and output summary."""
    meta = await store.get_notebook_meta(notebook_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")

    analysis_json = await store.get_notebook_analysis_json(notebook_id)

    nb_content = _load_notebook_file(notebook_id)
    if not nb_content:
        raise HTTPException(status_code=404, detail=f"Notebook file for '{notebook_id}' not found")

    report_data = _build_report_data(
        analysis_json=analysis_json,
        nb_content=nb_content,
    )

    analysis: NotebookAnalysis | None = None
    if analysis_json is not None:
        aj = analysis_json
        analysis = NotebookAnalysis(
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

    report = NotebookReport(
        report_version="1.0",
        generated_at=time.time(),
        notebook=meta,
        analysis=analysis,
        cell_details=[NotebookReportCell(**c) for c in report_data["cell_details"]],
        outputs_summary=NotebookReportOutputsSummary(**report_data["outputs_summary"]),
        metadata=NotebookReportMetadata(**report_data["metadata"]),
    )
    try:
        await store.log_notebook_activity(notebook_id, "export_report", None)
    except Exception:
        pass
    return report
