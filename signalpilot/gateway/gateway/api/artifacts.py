"""Unified artifacts listing API.

One org-scoped endpoint over every artifact source the gateway knows about
(eval today; see :mod:`gateway.store.artifacts_index` for why chat and
notebook artifacts are absent). This route only *lists* — each record's
``download.route`` points at the existing kind-specific download endpoint,
which keeps its own auth and content negotiation.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from ..auth import DBSession, OrgID
from ..security.scope_guard import RequireScope
from ..store import artifacts_index

router = APIRouter(prefix="/api")


@router.get("/artifacts", dependencies=[RequireScope("read")])
async def list_artifacts(
    org_id: OrgID,
    db: DBSession,
    kind: str | None = Query(None, pattern="^(eval|notebook)$"),
    run_id: str | None = Query(None, max_length=200),
    project_id: str | None = Query(None, max_length=200),
    since: str | None = Query(None, description="ISO-8601 lower bound on created_at"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    since_dt: datetime | None = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(status_code=400, detail="since must be an ISO-8601 timestamp")

    records, total = await artifacts_index.list_artifacts(
        db,
        org_id=org_id,
        project_id=project_id,
        kind=kind,
        run_id=run_id,
        since=since_dt,
        limit=limit,
        offset=offset,
    )
    return {"artifacts": [record.to_dict() for record in records], "total": total}
