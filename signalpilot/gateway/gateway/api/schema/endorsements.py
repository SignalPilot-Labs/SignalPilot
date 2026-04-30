"""Schema endorsement endpoints (HEX Data Browser pattern)."""

from __future__ import annotations

import logging

from fastapi import HTTPException

from gateway.api.deps import (
    StoreD,
    require_connection,
)
from gateway.api.schema._router import router
from gateway.connectors.schema_cache import schema_cache
from gateway.scope_guard import RequireScope

logger = logging.getLogger(__name__)


# ─── Schema Endorsements (HEX Data Browser pattern) ────────────────────────


@router.get("/connections/{name}/schema/endorsements", dependencies=[RequireScope("read")])
async def get_endorsements(name: str, store: StoreD):
    """Get schema endorsement config for a connection."""
    await require_connection(store, name)
    return await store.get_schema_endorsements(name)


@router.put("/connections/{name}/schema/endorsements", dependencies=[RequireScope("write")])
async def update_endorsements(name: str, store: StoreD, body: dict):
    """Set schema endorsement config for a connection.

    Body: {"endorsed": ["schema.table", ...], "hidden": ["schema.table", ...], "mode": "all|endorsed_only"}
    """
    await require_connection(store, name)
    mode = body.get("mode", "all")
    if mode not in ("all", "endorsed_only"):
        raise HTTPException(status_code=422, detail="mode must be 'all' or 'endorsed_only'")
    endorsed = body.get("endorsed", [])
    hidden = body.get("hidden", [])
    if len(endorsed) > 1000:
        raise HTTPException(status_code=422, detail="endorsed list must have at most 1000 items")
    if len(hidden) > 1000:
        raise HTTPException(status_code=422, detail="hidden list must have at most 1000 items")
    for item in endorsed:
        if isinstance(item, str) and len(item) > 256:
            raise HTTPException(status_code=422, detail="Each endorsed item must be at most 256 characters")
    for item in hidden:
        if isinstance(item, str) and len(item) > 256:
            raise HTTPException(status_code=422, detail="Each hidden item must be at most 256 characters")
    result = await store.set_schema_endorsements(name, body)
    schema_cache.invalidate(name)
    return result
