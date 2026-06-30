"""Reports REST API endpoints — rendered HTML reports.

Mutations require admin scope (mirrors knowledge governance). Deletion is
permanent (hard delete) by design.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from ..models.reports import Report, ReportCreate, ReportSummary
from ..security.scope_guard import RequireScope
from ..store.reports import ReportSizeExceeded
from .deps import StoreD

router = APIRouter(prefix="/api")


@router.get("/reports", response_model=list[ReportSummary], dependencies=[RequireScope("read")])
async def list_reports(store: StoreD, scope_ref: str | None = None):
    """List report metadata (no HTML body), newest first."""
    return await store.list_reports(scope_ref=scope_ref, limit=200, offset=0)


@router.get("/reports/{report_id}", response_model=Report, dependencies=[RequireScope("read")])
async def get_report(report_id: uuid.UUID, store: StoreD):
    """Get a single report including its HTML body."""
    report = await store.get_report(str(report_id), bump_view=True)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found")
    return report


@router.post("/reports", response_model=Report, status_code=201, dependencies=[RequireScope("admin")])
async def create_report(payload: ReportCreate, store: StoreD):
    """Create a new HTML report (admin only)."""
    try:
        return await store.insert_report(payload, user_id=store.user_id)
    except ReportSizeExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


@router.delete("/reports/{report_id}", status_code=204, dependencies=[RequireScope("admin")])
async def delete_report(report_id: uuid.UUID, store: StoreD):
    """Permanently delete a report (admin only)."""
    deleted = await store.delete_report(str(report_id))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found")
