"""Schema-watch CRUD + run-now endpoints.

A watch periodically introspects a connection and opens a GitHub PR when the
schema fingerprint drifts. Admin scope on mutations; the background loop in
main.py executes due watches.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db.models import GatewaySchemaWatch
from ..security.scope_guard import RequireScope
from .deps import StoreD

router = APIRouter(prefix="/api")


class SchemaWatchCreate(BaseModel):
    connection_name: str = Field(..., min_length=1, max_length=100)
    github_repo: str = Field(..., min_length=3, max_length=200, pattern=r"^[\w.-]+/[\w.-]+$")
    interval_s: int = Field(86400, ge=60, le=30 * 86400)
    github_base_branch: str | None = Field(None, max_length=100)
    enabled: bool = True


class SchemaWatchInfo(BaseModel):
    id: str
    connection_name: str
    github_repo: str
    github_base_branch: str | None
    interval_s: int
    enabled: bool
    last_run_at: float | None
    last_change_at: float | None
    last_pr_url: str | None
    last_error: str | None
    created_at: float


def _to_info(w: GatewaySchemaWatch) -> SchemaWatchInfo:
    return SchemaWatchInfo(
        id=w.id,
        connection_name=w.connection_name,
        github_repo=w.github_repo,
        github_base_branch=w.github_base_branch,
        interval_s=w.interval_s,
        enabled=w.enabled,
        last_run_at=w.last_run_at,
        last_change_at=w.last_change_at,
        last_pr_url=w.last_pr_url,
        last_error=w.last_error,
        created_at=w.created_at,
    )


async def _get_watch(store: StoreD, watch_id: str) -> GatewaySchemaWatch:
    result = await store.session.execute(
        select(GatewaySchemaWatch).where(
            GatewaySchemaWatch.id == watch_id,
            GatewaySchemaWatch.org_id == store.org_id,
        )
    )
    watch = result.scalar_one_or_none()
    if watch is None:
        raise HTTPException(status_code=404, detail="schema watch not found")
    return watch


@router.get("/schema-watches", response_model=list[SchemaWatchInfo], dependencies=[RequireScope("read")])
async def list_schema_watches(store: StoreD):
    result = await store.session.execute(
        select(GatewaySchemaWatch).where(GatewaySchemaWatch.org_id == store.org_id)
    )
    return [_to_info(w) for w in result.scalars().all()]


@router.post(
    "/schema-watches", response_model=SchemaWatchInfo, status_code=201, dependencies=[RequireScope("admin")]
)
async def create_schema_watch(payload: SchemaWatchCreate, store: StoreD):
    from ..schema_watch.runner import new_watch

    conn = await store.get_connection(payload.connection_name)
    if conn is None:
        raise HTTPException(status_code=404, detail=f"connection '{payload.connection_name}' not found")
    watch = new_watch(
        org_id=store.org_id or "local",
        connection_name=payload.connection_name,
        github_repo=payload.github_repo,
        interval_s=payload.interval_s,
        github_base_branch=payload.github_base_branch,
        enabled=payload.enabled,
    )
    store.session.add(watch)
    try:
        await store.session.commit()
    except IntegrityError:
        await store.session.rollback()
        raise HTTPException(status_code=409, detail="watch already exists for this connection+repo")
    return _to_info(watch)


@router.get("/schema-watches/{watch_id}", response_model=SchemaWatchInfo, dependencies=[RequireScope("read")])
async def get_schema_watch(watch_id: str, store: StoreD):
    return _to_info(await _get_watch(store, watch_id))


@router.delete("/schema-watches/{watch_id}", status_code=204, response_model=None, dependencies=[RequireScope("admin")])
async def delete_schema_watch(watch_id: str, store: StoreD):
    watch = await _get_watch(store, watch_id)
    await store.session.delete(watch)
    await store.session.commit()


@router.post("/schema-watches/{watch_id}/run", dependencies=[RequireScope("admin")])
async def run_schema_watch_now(watch_id: str, store: StoreD):
    """Run a watch immediately (baseline on first run, PR on drift)."""
    from ..schema_watch.runner import run_watch

    watch = await _get_watch(store, watch_id)
    return await run_watch(store.session, watch)
