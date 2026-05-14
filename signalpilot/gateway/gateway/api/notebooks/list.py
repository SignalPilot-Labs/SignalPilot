"""Notebook list endpoint: paginated listing with sort and status filter."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from gateway.security.scope_guard import RequireScope
from gateway.store.notebooks import NOTEBOOK_SORT_KEYS, NOTEBOOK_STATUS_VALUES

from ..deps import StoreD

router = APIRouter()


@router.get("/notebooks", dependencies=[RequireScope("read")])
async def list_notebooks(
    store: StoreD,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
    status: str = "all",
) -> dict:
    """List all notebooks with pagination, sorting, and status filtering."""
    if sort_by not in NOTEBOOK_SORT_KEYS:
        raise HTTPException(status_code=400, detail=f"Invalid sort_by '{sort_by}'. Allowed: {sorted(NOTEBOOK_SORT_KEYS)}")
    if sort_dir not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="Invalid sort_dir. Allowed: 'asc', 'desc'")
    if status not in NOTEBOOK_STATUS_VALUES:
        raise HTTPException(status_code=400, detail=f"Invalid status '{status}'. Allowed: {sorted(NOTEBOOK_STATUS_VALUES)}")
    items = await store.list_notebooks(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, status=status)
    total = await store.count_notebooks(status=status)
    return {"items": items, "total": total}
