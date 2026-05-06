"""Notebook search endpoint: full-text search with pagination and filters."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from gateway.security.scope_guard import RequireScope
from gateway.store.notebooks import NOTEBOOK_SORT_KEYS, NOTEBOOK_STATUS_VALUES

from ..deps import StoreD

router = APIRouter()


@router.get("/notebooks/search", dependencies=[RequireScope("read")])
async def search_notebooks(
    store: StoreD,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
    status: str = "all",
) -> dict:
    """Search notebooks by name, description, or tags."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' must not be empty.")
    if sort_by not in NOTEBOOK_SORT_KEYS:
        raise HTTPException(status_code=400, detail=f"Invalid sort_by '{sort_by}'. Allowed: {sorted(NOTEBOOK_SORT_KEYS)}")
    if sort_dir not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="Invalid sort_dir. Allowed: 'asc', 'desc'")
    if status not in NOTEBOOK_STATUS_VALUES:
        raise HTTPException(status_code=400, detail=f"Invalid status '{status}'. Allowed: {sorted(NOTEBOOK_STATUS_VALUES)}")
    results = await store.search_notebooks(query=q, limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, status=status)
    total = await store.count_search_notebooks(query=q, status=status)
    return {"items": results, "total": total}
