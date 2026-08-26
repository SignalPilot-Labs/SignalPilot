"""Workspace Files API — the S3-backed durable filesystem for projects.

This is the storage plane of Notebook Runtime v2: sandboxes hydrate from the
snapshot endpoint and write back through files:batch; the browser reads files
without any compute attached. Branch names may contain '/', so the branch
always travels as a query/body parameter, never a path segment.

Deleting a file is a new revision — prior revisions keep serving it (410/404
discipline: a deleted *project* answers 410 Gone with a tombstone, a path that
never existed answers 404).
"""

from __future__ import annotations

import base64
import binascii
import re

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from ..auth import DBSession, OrgID, UserID
from ..security.scope_guard import RequireScope
from ..workspace_store import (
    RevisionConflict,
    WorkspacePathError,
    WorkspaceStore,
    blob_key,
    workspace_object_storage,
)
from ..workspace_store.store import RevisionNotFound, Upsert
from .deps import ProjectsGate, StoreD

router = APIRouter(prefix="/api", dependencies=[ProjectsGate])

_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_INLINE_BYTES = 8 * 1024 * 1024


def get_workspace_store() -> WorkspaceStore:
    """FastAPI dependency: the S3-backed workspace store."""
    return WorkspaceStore(workspace_object_storage())


WorkspaceStoreD = Annotated[WorkspaceStore, Depends(get_workspace_store)]


def _valid_branch(branch: str) -> str:
    if not _BRANCH_RE.match(branch) or ".." in branch:
        raise HTTPException(status_code=400, detail="Invalid branch name")
    return branch


async def _require_project(store, ws: WorkspaceStore, db, project_id: str) -> None:
    """404 for a project that never existed, 410 Gone for a deleted one whose
    revision history remains — old links tombstone instead of erroring."""
    project = await store.get_workspace_project(project_id)
    if project is not None:
        return
    if await ws.has_revisions(db, project_id=project_id):
        raise HTTPException(
            status_code=410,
            detail={"tombstone": True, "project_id": project_id, "reason": "Project was deleted"},
        )
    raise HTTPException(status_code=404, detail="Project not found")


def _confined(path: str) -> str:
    from ..workspace_store import confine_relpath

    try:
        return confine_relpath(path)
    except WorkspacePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Single-file operations ───────────────────────────────────────────────────


@router.get(
    "/workspace-projects/{project_id}/files/{path:path}",
    dependencies=[RequireScope("read")],
)
async def get_file(
    project_id: str,
    path: str,
    org_id: OrgID,
    _user: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
    branch: str = Query("main"),
    revision: int | None = Query(None, ge=0),
):
    await _require_project(store, ws, db, project_id)
    result = await ws.read_file(
        db,
        org_id=org_id,
        project_id=project_id,
        branch=_valid_branch(branch),
        path=_confined(path),
        revision=revision,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="File not found at this revision")
    entry, blob = result
    return Response(
        content=blob,
        media_type="application/octet-stream",
        headers={
            "X-SP-Revision": str(revision) if revision is not None else "head",
            "X-SP-Sha256": entry.sha256,
        },
    )


@router.put(
    "/workspace-projects/{project_id}/files/{path:path}",
    dependencies=[RequireScope("write")],
)
async def put_file(
    project_id: str,
    path: str,
    request: Request,
    org_id: OrgID,
    user_id: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
    branch: str = Query("main"),
):
    await _require_project(store, ws, db, project_id)
    content = await request.body()
    if len(content) > _MAX_INLINE_BYTES:
        raise HTTPException(status_code=413, detail="Use files:upload-url for files over 8 MB")
    manifest = await ws.commit_at_head(
        db,
        org_id=org_id,
        project_id=project_id,
        branch=_valid_branch(branch),
        upserts=[Upsert(path=_confined(path), content=content)],
        deletes=[],
        created_by=user_id,
        message=f"put {path}",
    )
    return {"revision": manifest.revision}


@router.delete(
    "/workspace-projects/{project_id}/files/{path:path}",
    dependencies=[RequireScope("write")],
)
async def delete_file(
    project_id: str,
    path: str,
    org_id: OrgID,
    user_id: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
    branch: str = Query("main"),
):
    await _require_project(store, ws, db, project_id)
    branch = _valid_branch(branch)
    path = _confined(path)
    try:
        manifest = await ws.load_manifest(db, org_id=org_id, project_id=project_id, branch=branch)
    except RevisionNotFound:
        raise HTTPException(status_code=404, detail="File not found")
    if manifest.entry(path) is None:
        raise HTTPException(status_code=404, detail="File not found")
    new_manifest = await ws.commit_at_head(
        db,
        org_id=org_id,
        project_id=project_id,
        branch=branch,
        upserts=[],
        deletes=[path],
        created_by=user_id,
        message=f"delete {path}",
    )
    return {"revision": new_manifest.revision}


# ── Listing / copy / move / search ───────────────────────────────────────────


class _BranchRef(BaseModel):
    branch: str = "main"
    revision: int | None = Field(None, ge=0)


class _ListRequest(_BranchRef):
    prefix: str | None = None


class _SearchRequest(_BranchRef):
    query: str = Field(min_length=1, max_length=200)


class _CopyRequest(BaseModel):
    branch: str = "main"
    source: str
    destination: str


async def _manifest_or_404(ws, db, *, org_id, project_id, branch, revision):
    try:
        return await ws.load_manifest(
            db, org_id=org_id, project_id=project_id, branch=branch, revision=revision
        )
    except RevisionNotFound:
        raise HTTPException(status_code=404, detail="No such revision")


@router.post(
    "/workspace-projects/{project_id}/files:list",
    dependencies=[RequireScope("read")],
)
async def list_files(
    project_id: str,
    body: _ListRequest,
    org_id: OrgID,
    _user: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
):
    await _require_project(store, ws, db, project_id)
    branch = _valid_branch(body.branch)
    try:
        manifest = await ws.load_manifest(
            db, org_id=org_id, project_id=project_id, branch=branch, revision=body.revision
        )
    except RevisionNotFound:
        return {"revision": None, "files": []}
    prefix = _confined(body.prefix) + "/" if body.prefix else ""
    files = [
        entry.to_json()
        for entry in manifest.entries
        if not prefix or entry.path.startswith(prefix)
    ]
    return {"revision": manifest.revision, "files": files}


@router.post(
    "/workspace-projects/{project_id}/files:search",
    dependencies=[RequireScope("read")],
)
async def search_files(
    project_id: str,
    body: _SearchRequest,
    org_id: OrgID,
    _user: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
):
    await _require_project(store, ws, db, project_id)
    manifest = await _manifest_or_404(
        ws, db, org_id=org_id, project_id=project_id,
        branch=_valid_branch(body.branch), revision=body.revision,
    )
    needle = body.query.lower()
    return {
        "revision": manifest.revision,
        "files": [entry.to_json() for entry in manifest.entries if needle in entry.path.lower()],
    }


@router.post(
    "/workspace-projects/{project_id}/files:copy",
    dependencies=[RequireScope("write")],
)
async def copy_file(
    project_id: str,
    body: _CopyRequest,
    org_id: OrgID,
    user_id: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
):
    return await _copy_or_move(project_id, body, org_id, user_id, db, store, ws, move=False)


@router.post(
    "/workspace-projects/{project_id}/files:move",
    dependencies=[RequireScope("write")],
)
async def move_file(
    project_id: str,
    body: _CopyRequest,
    org_id: OrgID,
    user_id: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
):
    return await _copy_or_move(project_id, body, org_id, user_id, db, store, ws, move=True)


async def _copy_or_move(project_id, body, org_id, user_id, db, store, ws, *, move: bool):
    await _require_project(store, ws, db, project_id)
    try:
        manifest = await ws.copy_file(
            db,
            org_id=org_id,
            project_id=project_id,
            branch=_valid_branch(body.branch),
            source=_confined(body.source),
            destination=_confined(body.destination),
            created_by=user_id,
            move=move,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Source file not found")
    except RevisionNotFound:
        raise HTTPException(status_code=404, detail="Branch has no revisions")
    return {"revision": manifest.revision}


# ── Batch commit (the sync agent's write path) ───────────────────────────────


class _BatchUpsert(BaseModel):
    path: str
    content_b64: str | None = None
    sha256: str | None = None
    size: int | None = Field(None, ge=0)
    mode: int = 0o644
    mtime: float | None = None


class _BatchRequest(BaseModel):
    branch: str = "main"
    base_revision: int | None = Field(None, ge=0)
    upserts: list[_BatchUpsert] = Field(default_factory=list, max_length=500)
    deletes: list[str] = Field(default_factory=list, max_length=500)
    message: str | None = Field(None, max_length=500)


@router.post(
    "/workspace-projects/{project_id}/files:batch",
    dependencies=[RequireScope("write")],
)
async def batch_commit(
    project_id: str,
    body: _BatchRequest,
    org_id: OrgID,
    user_id: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
):
    await _require_project(store, ws, db, project_id)
    if not body.upserts and not body.deletes:
        raise HTTPException(status_code=400, detail="Empty batch")
    upserts: list[Upsert] = []
    for item in body.upserts:
        if item.content_b64 is not None:
            try:
                content = base64.b64decode(item.content_b64, validate=True)
            except (binascii.Error, ValueError):
                raise HTTPException(status_code=400, detail=f"Invalid base64 for {item.path}")
            upserts.append(
                Upsert(path=item.path, content=content, mode=item.mode, mtime=item.mtime)
            )
        else:
            if not item.sha256 or not _SHA256_RE.match(item.sha256) or item.size is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Reference upsert for {item.path} needs sha256 and size",
                )
            upserts.append(
                Upsert(
                    path=item.path,
                    sha256=item.sha256,
                    size=item.size,
                    mode=item.mode,
                    mtime=item.mtime,
                )
            )
    try:
        manifest = await ws.commit(
            db,
            org_id=org_id,
            project_id=project_id,
            branch=_valid_branch(body.branch),
            base_revision=body.base_revision,
            upserts=upserts,
            deletes=body.deletes,
            created_by=user_id,
            message=body.message,
        )
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RevisionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (WorkspacePathError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"revision": manifest.revision, "file_count": len(manifest.entries)}


class _UploadUrlRequest(BaseModel):
    sha256: str
    size: int = Field(ge=1)


@router.post(
    "/workspace-projects/{project_id}/files:upload-url",
    dependencies=[RequireScope("write")],
)
async def blob_upload_url(
    project_id: str,
    body: _UploadUrlRequest,
    org_id: OrgID,
    _user: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
):
    await _require_project(store, ws, db, project_id)
    if not _SHA256_RE.match(body.sha256):
        raise HTTPException(status_code=400, detail="sha256 must be 64 lowercase hex chars")
    key = blob_key(org_id, project_id, body.sha256)
    url = await ws.storage.presign_put(key)
    return {"url": url, "key": key}


# ── Snapshots and history ────────────────────────────────────────────────────


@router.get(
    "/workspace-projects/{project_id}/snapshot",
    dependencies=[RequireScope("read")],
)
async def snapshot(
    project_id: str,
    org_id: OrgID,
    _user: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
    branch: str = Query("main"),
    revision: int | None = Query(None, ge=0),
):
    await _require_project(store, ws, db, project_id)
    try:
        resolved, key = await ws.build_snapshot(
            db, org_id=org_id, project_id=project_id, branch=_valid_branch(branch), revision=revision
        )
    except RevisionNotFound:
        raise HTTPException(status_code=404, detail="No such revision")
    url = await ws.storage.presign_get(key, expires_seconds=3600)
    return {"revision": resolved, "url": url, "key": key}


@router.get(
    "/workspace-projects/{project_id}/revisions",
    dependencies=[RequireScope("read")],
)
async def revisions(
    project_id: str,
    org_id: OrgID,
    _user: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
    branch: str = Query("main"),
    limit: int = Query(100, ge=1, le=500),
):
    await _require_project(store, ws, db, project_id)
    rows = await ws.list_revisions(
        db, org_id=org_id, project_id=project_id, branch=_valid_branch(branch), limit=limit
    )
    return {
        "branch": branch,
        "revisions": [
            {
                "revision": row.revision,
                "parent": row.parent_revision,
                "created_at": row.created_at,
                "created_by": row.created_by,
                "message": row.message,
                "file_count": row.file_count,
                "total_bytes": row.total_bytes,
                "export_commit_sha": row.export_commit_sha,
            }
            for row in rows
        ],
    }
