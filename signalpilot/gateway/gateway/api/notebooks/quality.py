"""Notebook quality endpoint: list analyzed notebooks sorted by quality score."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from gateway.models.notebooks import NotebookQualityItem
from gateway.security.scope_guard import RequireScope

from ..deps import StoreD

router = APIRouter()

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 500


@router.get("/notebooks/quality", dependencies=[RequireScope("read")])
async def get_notebooks_quality(
    store: StoreD,
    max_score: int = 100,
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
    sort_dir: str = "desc",
) -> dict:
    """List analyzed notebooks filtered by quality score.

    Returns notebooks with quality_score <= max_score, sorted by quality score.

    Args:
        max_score: Upper bound on quality score (inclusive). Default 100 (all notebooks).
        limit: Maximum number of results. Default 50.
        offset: Number of results to skip for pagination. Default 0.
        sort_dir: Sort direction by quality score: 'asc' or 'desc'. Default 'desc'.

    Returns:
        {"items": [...], "total": int}
    """
    if max_score < 0 or max_score > 100:
        raise HTTPException(status_code=422, detail="max_score must be between 0 and 100.")
    if sort_dir not in {"asc", "desc"}:
        raise HTTPException(status_code=422, detail="sort_dir must be 'asc' or 'desc'.")

    all_items = await store.list_analyzed_notebooks()

    filtered = [item for item in all_items if item.quality_score <= max_score]

    reverse = sort_dir == "desc"
    filtered.sort(key=lambda item: item.quality_score, reverse=reverse)

    total = len(filtered)
    offset = max(0, offset)
    limit = min(max(1, limit), _MAX_LIMIT)
    page: list[NotebookQualityItem] = filtered[offset: offset + limit]

    return {"items": [item.model_dump() for item in page], "total": total}
