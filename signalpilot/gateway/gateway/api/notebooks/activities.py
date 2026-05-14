"""Notebook activities endpoint: paginated activity log."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from gateway.security.scope_guard import RequireScope
from gateway.store.notebook_activities import NOTEBOOK_ACTION_VALUES

from ..deps import StoreD
from .crud import NotebookIdP

router = APIRouter()


@router.get("/notebooks/{notebook_id}/activities", dependencies=[RequireScope("read")])
async def get_notebook_activities(
    notebook_id: NotebookIdP,
    store: StoreD,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
) -> dict:
    """Get paginated activity log for a notebook."""
    meta = await store.get_notebook_meta(notebook_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")
    if action is not None and action not in NOTEBOOK_ACTION_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action '{action}'. Allowed: {sorted(NOTEBOOK_ACTION_VALUES)}",
        )
    items = await store.get_notebook_activities(
        notebook_id, limit=limit, offset=offset, action=action
    )
    total = await store.count_notebook_activities(notebook_id, action=action)
    return {"items": [i.model_dump() for i in items], "total": total}
