"""Notebook versions endpoint: paginated version history."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from gateway.security.scope_guard import RequireScope

from ..deps import StoreD
from .crud import NotebookIdP

router = APIRouter()


@router.get("/notebooks/{notebook_id}/versions", dependencies=[RequireScope("read")])
async def get_notebook_versions(
    notebook_id: NotebookIdP,
    store: StoreD,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Get paginated version history for a notebook."""
    meta = await store.get_notebook_meta(notebook_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")
    items = await store.list_notebook_versions(notebook_id, limit=limit, offset=offset)
    total = await store.count_notebook_versions(notebook_id)
    return {"items": [i.model_dump() for i in items], "total": total}
