"""Notebook download endpoint: raw .ipynb file download."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from gateway.security.scope_guard import RequireScope
from gateway.store.notebook_files import _load_notebook_file_raw

from ..deps import StoreD
from .crud import NotebookIdP

router = APIRouter()


@router.get("/notebooks/{notebook_id}/download", dependencies=[RequireScope("read")])
async def download_notebook(notebook_id: NotebookIdP, store: StoreD) -> Response:
    """Download the raw .ipynb file."""
    meta = await store.get_notebook_meta(notebook_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Notebook '{notebook_id}' not found")
    content = _load_notebook_file_raw(notebook_id)
    if not content:
        raise HTTPException(status_code=404, detail=f"Notebook file for '{notebook_id}' not found")
    safe_name = meta.name.replace('"', "'").replace("\r", "").replace("\n", "")
    try:
        await store.log_notebook_activity(notebook_id, "download", None)
    except Exception:
        pass
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.ipynb"'},
    )
