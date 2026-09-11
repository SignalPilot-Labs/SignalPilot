"""dbt map endpoints: trigger compiles, serve the stored lineage graph.

The graph is produced by the sandbox compile pipeline (gateway/dbt_map) and
stored in workspace S3; these endpoints only read the index row and artifacts,
so any page, not just the notebook, can render lineage.

Read paths go through gateway.dbt_map.graph_cache: the gzipped graph is
fetched and decoded once per graph_key, and every payload variant (full,
skeleton, per-model cone, columns) plus its gzip envelope is memoized.

GET /dbt-map response shape (unchanged for graph=full):
    {"status": str, "map": DbtMapInfo | null, "graph": dict | null}
graph=skeleton drops test nodes and columns and adds per-node
`column_count` and `tests`; see gateway/dbt_map/slices.py.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import select

from ..db.models import GatewayDbtManifest
from ..dbt_map import schedule_compile
from ..dbt_map.graph_cache import GraphEntry, graph_cache, sql_map_cache
from ..dbt_map.row_cache import RowSnapshot, row_cache
from ..dbt_map.slices import MAX_COLUMN_IDS, columns_for, resolve_ref
from ..dbt_map.sql_slices import SQL_RESOURCE_TYPES, extract_sql_map, sql_payload
from ..models.dbt_map import DbtMapCompileResponse, DbtMapInfo, DbtMapResponse
from ..security.scope_guard import RequireScope
from ..workspace_store import workspace_object_storage
from .dbt_map_responses import (
    accepts_gzip,
    envelope_prefix,
    etag_for_row,
    etag_matches,
    json_bytes_response,
    json_response,
    not_modified,
)
from .deps import ProjectsGate, StoreD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[ProjectsGate])


def _to_info(row: GatewayDbtManifest | RowSnapshot) -> DbtMapInfo:
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


async def _lookup(store: StoreD, project_id: str, branch: str | None) -> tuple[str, RowSnapshot | None]:
    """Resolved branch plus latest-row snapshot, served from the TTL cache when fresh."""
    org_id = store.org_id or "local"
    key = (org_id, project_id, branch or None)
    hit = row_cache.get(key)
    if hit is not None:
        return hit
    resolved = await _resolve_branch(store, project_id, branch)
    row = await _latest_row(store.session, org_id, project_id, resolved)
    value = (resolved, RowSnapshot.from_row(row) if row is not None else None)
    row_cache.put(key, value)
    if branch is None:
        # Explicit requests for the default branch share the same answer.
        row_cache.put((org_id, project_id, resolved), value)
    return value


async def _row_for(store: StoreD, project_id: str, branch: str | None) -> RowSnapshot | None:
    _resolved, row = await _lookup(store, project_id, branch)
    return row


async def _graph_entry(row: RowSnapshot) -> GraphEntry | None:
    """Cached decoded graph for a successful row; None when nothing is stored."""
    if row.status != "success" or not row.graph_key:
        return None
    key = row.graph_key
    entry = graph_cache.get(key)
    if entry is not None:
        return entry
    storage = workspace_object_storage()
    if not storage.enabled:
        return None
    return await graph_cache.get_or_load(key, lambda: storage.get_bytes(key))


async def _require_graph(store: StoreD, project_id: str, branch: str | None):
    row = await _row_for(store, project_id, branch)
    if row is None or row.status != "success" or not row.graph_key:
        raise HTTPException(status_code=404, detail="No compiled dbt map for this branch")
    entry = await _graph_entry(row)
    if entry is None:
        raise HTTPException(status_code=404, detail="dbt map graph is not available")
    return row, entry


def _resolve_or_raise(graph: dict, ref: str) -> str:
    uid, candidates = resolve_ref(graph, ref)
    if uid is not None:
        return uid
    if candidates:
        raise HTTPException(
            status_code=409,
            detail={"message": f"Ambiguous model ref {ref!r}", "candidates": candidates},
        )
    raise HTTPException(status_code=404, detail=f"Unknown model {ref!r}")


async def _sql_map(row: RowSnapshot) -> tuple[str, dict, str] | None:
    """(cache key, sql map, source) from the sql artifact, else the manifest."""
    if row.sql_key:
        key, source = row.sql_key, "artifact"
        extractor = json.loads
    elif row.manifest_key:
        key, source = row.manifest_key, "manifest"

        def extractor(raw: bytes) -> dict:
            return extract_sql_map((json.loads(raw) or {}).get("nodes") or {})
    else:
        return None
    sql_map = sql_map_cache.get(key)
    if sql_map is None:
        storage = workspace_object_storage()
        if not storage.enabled:
            return None
        sql_map = await sql_map_cache.get_or_load(key, lambda: storage.get_bytes(key), extractor)
    if sql_map is None:
        return None
    return key, sql_map, source


def _parse_hops(hops: str) -> int | None:
    if hops == "all":
        return None
    try:
        value = int(hops)
    except ValueError:
        value = -1
    if value < 0:
        raise HTTPException(status_code=422, detail="hops must be a non-negative integer or 'all'")
    return value


@router.post(
    "/workspace-projects/{project_id}/dbt-map/compile",
    response_model=DbtMapCompileResponse,
    dependencies=[RequireScope("write")],
)
async def compile_dbt_map(project_id: str, store: StoreD, branch: str | None = Query(None)):
    org_id = store.org_id or "local"
    resolved = await _resolve_branch(store, project_id, branch)
    schedule_compile(org_id, project_id, resolved, trigger="manual")
    # Readers must see the new compile row on their next poll.
    row_cache.invalidate_project(org_id, project_id)
    row = await _latest_row(store.session, org_id, project_id, resolved)
    return DbtMapCompileResponse(scheduled=True, map=_to_info(row) if row else None)


@router.get(
    "/workspace-projects/{project_id}/dbt-map",
    dependencies=[RequireScope("read")],
)
async def get_dbt_map(
    request: Request,
    project_id: str,
    store: StoreD,
    branch: str | None = Query(None),
    include_graph: bool = Query(True),
    graph: Literal["full", "skeleton"] = Query("full"),
) -> Response:
    """Latest compile state, with the distilled graph inline (DbtMapResponse shape)."""
    row = await _row_for(store, project_id, branch)
    etag = etag_for_row(row)
    if etag_matches(request, etag):
        return not_modified(etag)
    if row is None:
        return json_response(DbtMapResponse(status="none"), etag)

    info = _to_info(row)
    entry = await _graph_entry(row) if include_graph else None
    if entry is None:
        return json_response(DbtMapResponse(status=row.status, map=info), etag)

    body, gz = await entry.envelope(graph, etag, envelope_prefix(row.status, info))
    return json_bytes_response(body, etag, gzip_body=gz if accepts_gzip(request) else None)


@router.get(
    "/workspace-projects/{project_id}/dbt-map/columns",
    dependencies=[RequireScope("read")],
)
async def get_dbt_map_columns(
    request: Request,
    project_id: str,
    store: StoreD,
    nodes: str = Query(..., description="Comma-separated unique_ids, max 50"),
    branch: str | None = Query(None),
) -> Response:
    """`{"columns": {unique_id: [{name, description, data_type?}]}}`; unknown ids omitted."""
    ids = list(dict.fromkeys(part.strip() for part in nodes.split(",") if part.strip()))
    if len(ids) > MAX_COLUMN_IDS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_COLUMN_IDS} node ids per request")
    row, entry = await _require_graph(store, project_id, branch)
    etag = etag_for_row(row)
    if etag_matches(request, etag):
        return not_modified(etag)
    return json_response({"columns": columns_for(entry.graph, ids)}, etag)


@router.get(
    "/workspace-projects/{project_id}/dbt-map/model/{ref}",
    dependencies=[RequireScope("read")],
)
async def get_dbt_map_model(
    request: Request,
    project_id: str,
    ref: str,
    store: StoreD,
    branch: str | None = Query(None),
    hops: str = Query("all", description="Cone depth in each direction, or 'all'"),
) -> Response:
    """Focused model with full columns plus its skeleton cone.

    `ref` is an exact unique_id or a unique model name (case-insensitive);
    ambiguous names return 409 with `candidates`, unknown names 404.
    """
    depth = _parse_hops(hops)
    row, entry = await _require_graph(store, project_id, branch)
    etag = etag_for_row(row)
    if etag_matches(request, etag):
        return not_modified(etag)
    uid = _resolve_or_raise(entry.graph, ref)
    cone = entry.cone(uid, depth)
    payload = {"status": row.status, "map": _to_info(row).model_dump(mode="json"), **cone}
    return json_response(payload, etag)


@router.get(
    "/workspace-projects/{project_id}/dbt-map/model/{ref}/sql",
    dependencies=[RequireScope("read")],
)
async def get_dbt_map_model_sql(
    request: Request,
    project_id: str,
    ref: str,
    store: StoreD,
    branch: str | None = Query(None),
) -> Response:
    """Raw and compiled SQL for a model, seed or snapshot.

    Served from the per-compile sql artifact when the row has one, else
    extracted once from the stored manifest. Strings over 512 KB are cut
    and flagged with `truncated: true`.
    """
    row, entry = await _require_graph(store, project_id, branch)
    etag = etag_for_row(row)
    if etag_matches(request, etag):
        return not_modified(etag)
    uid = _resolve_or_raise(entry.graph, ref)
    node = (entry.graph.get("nodes") or {}).get(uid)
    if node is None:
        raise HTTPException(status_code=404, detail=f"{uid!r} is a source; sources have no SQL")
    if node.get("resource_type") not in SQL_RESOURCE_TYPES:
        raise HTTPException(status_code=404, detail=f"{uid!r} is not a model, seed or snapshot")
    found = await _sql_map(row)
    if found is None:
        raise HTTPException(status_code=404, detail="No SQL artifact stored for this dbt map")
    key, sql_map, source = found
    payload = sql_map_cache.payload(key, uid, lambda: sql_payload(uid, node, sql_map.get(uid), source))
    return json_response(payload, etag)


@router.get(
    "/workspace-projects/{project_id}/dbt-map/manifest",
    dependencies=[RequireScope("read")],
)
async def get_dbt_map_manifest(
    project_id: str, store: StoreD, branch: str | None = Query(None)
):
    """Presigned URL for the raw (gzipped) manifest.json artifact."""
    row = await _row_for(store, project_id, branch)
    if row is None or row.status != "success" or not row.manifest_key:
        raise HTTPException(status_code=404, detail="No compiled manifest for this branch")
    storage = workspace_object_storage()
    if not storage.enabled:
        raise HTTPException(status_code=503, detail="Workspace storage not configured")
    url = await storage.presign_get(row.manifest_key, expires_seconds=3600)
    return {"manifest_url": url, "revision": row.revision, "bytes": row.manifest_bytes}
