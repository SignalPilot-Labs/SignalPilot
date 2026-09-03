"""dbt map endpoints: trigger compiles, serve the stored lineage graph.

The graph is produced by the sandbox compile pipeline (gateway/dbt_map) and
stored in workspace S3; these endpoints only read the index row and artifacts,
so any page — not just the notebook — can render lineage.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..db.models import GatewayDbtManifest
from ..dbt_map import schedule_compile
from ..models.dbt_map import DbtMapCompileResponse, DbtMapInfo, DbtMapResponse
from ..security.scope_guard import RequireScope
from ..workspace_store import workspace_object_storage
from .deps import ProjectsGate, StoreD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[ProjectsGate])


def _to_info(row: GatewayDbtManifest) -> DbtMapInfo:
    return DbtMapInfo(
        id=row.id,
        project_id=row.project_id,
        branch=row.branch,
        revision=row.revision,
        status=row.status,
        trigger=row.trigger,
        error=row.error,
        dbt_version=row.dbt_version,
        node_count=row.node_count,
        manifest_bytes=row.manifest_bytes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _resolve_branch(store: StoreD, project_id: str, branch: str | None) -> str:
    if branch:
        return branch
    project = await store.get_workspace_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.default_branch or "main"


async def _latest_row(
    session, org_id: str, project_id: str, branch: str
) -> GatewayDbtManifest | None:
    return (
        await session.execute(
            select(GatewayDbtManifest)
            .where(
                GatewayDbtManifest.org_id == org_id,
                GatewayDbtManifest.project_id == project_id,
                GatewayDbtManifest.branch == branch,
            )
            .order_by(GatewayDbtManifest.revision.desc())
            .limit(1)
        )
    ).scalars().first()


@router.post(
    "/workspace-projects/{project_id}/dbt-map/compile",
    response_model=DbtMapCompileResponse,
    dependencies=[RequireScope("write")],
)
async def compile_dbt_map(project_id: str, store: StoreD, branch: str | None = Query(None)):
    org_id = store.org_id or "local"
    resolved = await _resolve_branch(store, project_id, branch)
    schedule_compile(org_id, project_id, resolved, trigger="manual")
    row = await _latest_row(store.session, org_id, project_id, resolved)
    return DbtMapCompileResponse(scheduled=True, map=_to_info(row) if row else None)


@router.get(
    "/workspace-projects/{project_id}/dbt-map",
    response_model=DbtMapResponse,
    dependencies=[RequireScope("read")],
)
async def get_dbt_map(
    project_id: str,
    store: StoreD,
    branch: str | None = Query(None),
    include_graph: bool = Query(True),
):
    org_id = store.org_id or "local"
    resolved = await _resolve_branch(store, project_id, branch)
    row = await _latest_row(store.session, org_id, project_id, resolved)
    if row is None:
        return DbtMapResponse(status="none")

    graph = None
    if include_graph and row.status == "success" and row.graph_key:
        storage = workspace_object_storage()
        if storage.enabled:
            data = await storage.get_bytes(row.graph_key)
            if data is not None:
                raw = await asyncio.to_thread(gzip.decompress, data)
                graph = json.loads(raw)
    return DbtMapResponse(status=row.status, map=_to_info(row), graph=graph)


@router.get(
    "/workspace-projects/{project_id}/dbt-map/manifest",
    dependencies=[RequireScope("read")],
)
async def get_dbt_map_manifest(
    project_id: str, store: StoreD, branch: str | None = Query(None)
):
    """Presigned URL for the raw (gzipped) manifest.json artifact."""
    org_id = store.org_id or "local"
    resolved = await _resolve_branch(store, project_id, branch)
    row = await _latest_row(store.session, org_id, project_id, resolved)
    if row is None or row.status != "success" or not row.manifest_key:
        raise HTTPException(status_code=404, detail="No compiled manifest for this branch")
    storage = workspace_object_storage()
    if not storage.enabled:
        raise HTTPException(status_code=503, detail="Workspace storage not configured")
    url = await storage.presign_get(row.manifest_key, expires_seconds=3600)
    return {"manifest_url": url, "revision": row.revision, "bytes": row.manifest_bytes}
