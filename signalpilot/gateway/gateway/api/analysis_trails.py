"""API endpoints for durable external analysis trails."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from gateway.models.analysis_trails import AnalysisTrailInfo
from gateway.security.scope_guard import RequireScope
from gateway.store import analysis_trails

from .deps import StoreD

router = APIRouter(prefix="/api/analysis-trails")


@router.get("/resolve", response_model=AnalysisTrailInfo, dependencies=[RequireScope("read")])
async def resolve_analysis_trail(
    store: StoreD,
    session_id: str | None = Query(default=None, max_length=300),
    file: str | None = Query(default=None, max_length=4000),
) -> AnalysisTrailInfo:
    """Resolve a public trail link to its durable project/branch metadata."""
    trail = await analysis_trails.resolve_trail(
        store.session,
        org_id=store._require_org_id(),
        thread_id=session_id,
        notebook_path=file,
    )
    if trail is None:
        raise HTTPException(status_code=404, detail="Analysis trail not found")
    return trail
