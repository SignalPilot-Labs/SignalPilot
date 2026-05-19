"""Workspace project, branch, and file endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel as _BaseModel

from ..models.workspace import (
    BranchCreate,
    BranchInfo,
    FileInfo,
    UserSessionInfo,
    UserSessionUpdate,
    WorkspaceProjectCreate,
    WorkspaceProjectInfo,
    WorkspaceProjectUpdate,
)
from ..security.scope_guard import RequireScope
from .deps import S3D, StoreD

router = APIRouter(prefix="/api")

_MAX_FILE_SIZE = 10 * 1024 * 1024


def _branch_prefix(s3_prefix: str, branch: str) -> str:
    return f"{s3_prefix}/branches/{branch}/files"


def _detect_content_type(path: str) -> str:
    if path.endswith(".json"):
        return "application/json"
    if path.endswith(".yml") or path.endswith(".yaml"):
        return "text/yaml"
    if path.endswith(".py"):
        return "text/x-python"
    if path.endswith(".sql"):
        return "text/sql"
    if path.endswith(".csv"):
        return "text/csv"
    if path.endswith(".md"):
        return "text/markdown"
    return "text/plain"


async def _get_project_or_404(store, project_id: str) -> WorkspaceProjectInfo:
    proj = await store.get_workspace_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


async def _get_branch_or_404(store, project_id: str, branch_name: str) -> BranchInfo:
    branch = await store.get_branch(project_id, branch_name)
    if not branch or branch.status != "active":
        raise HTTPException(status_code=404, detail=f"Branch '{branch_name}' not found")
    return branch


def _check_write_permission(branch: BranchInfo, request: Request) -> None:
    """Block writes to protected branches unless caller has 'service' scope."""
    if not branch.is_protected:
        return
    auth = getattr(request.state, "auth", {})
    scopes = auth.get("scopes", [])
    if "service" in scopes:
        return
    raise HTTPException(
        status_code=403,
        detail=f"Cannot write directly to protected branch '{branch.name}'. Use a feature branch and merge via git.",
    )


# ─── Project CRUD ────────────────────────────────────────────────────────────


@router.post("/workspace-projects", status_code=201, response_model=WorkspaceProjectInfo, dependencies=[RequireScope("write")])
async def create_project(body: WorkspaceProjectCreate, store: StoreD):
    try:
        return await store.create_workspace_project(
            name=body.name,
            display_name=body.display_name,
            description=body.description,
            connection_name=body.connection_name,
            tags=body.tags,
            settings=body.settings,
        )
    except Exception as e:
        if "uq_gw_wsproj_org_name" in str(e):
            raise HTTPException(status_code=409, detail=f"Project '{body.name}' already exists")
        raise


@router.get("/workspace-projects", dependencies=[RequireScope("read")])
async def list_projects(
    store: StoreD,
    status: str | None = Query(None, max_length=20),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    projects, total = await store.list_workspace_projects(status=status, limit=limit, offset=offset)
    return {"projects": projects, "total": total}


@router.get("/workspace-projects/{project_id}", response_model=WorkspaceProjectInfo, dependencies=[RequireScope("read")])
async def get_project(project_id: str, store: StoreD):
    return await _get_project_or_404(store, project_id)


@router.put("/workspace-projects/{project_id}", response_model=WorkspaceProjectInfo, dependencies=[RequireScope("write")])
async def update_project(project_id: str, body: WorkspaceProjectUpdate, store: StoreD):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    proj = await store.update_workspace_project(project_id, updates)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


@router.delete("/workspace-projects/{project_id}", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_project(project_id: str, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    await s3.delete_prefix(proj.s3_prefix)
    await store.delete_workspace_project(project_id)


# ─── Branch Management ───────────────────────────────────────────────────────


@router.post("/workspace-projects/{project_id}/branches", status_code=201, response_model=BranchInfo, dependencies=[RequireScope("write")])
async def create_branch(project_id: str, body: BranchCreate, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    await store.ensure_main_branch(project_id)
    source = await _get_branch_or_404(store, project_id, body.from_branch)
    try:
        branch = await store.create_branch(project_id, name=body.name, from_branch=body.from_branch)
    except Exception as e:
        if "uq_gw_branch_proj_name" in str(e):
            raise HTTPException(status_code=409, detail=f"Branch '{body.name}' already exists")
        raise
    src_prefix = _branch_prefix(proj.s3_prefix, body.from_branch)
    dst_prefix = _branch_prefix(proj.s3_prefix, body.name)
    objects = await s3.list_objects(src_prefix, max_keys=5000)
    for obj in objects:
        suffix = obj["key"][len(f"{src_prefix}/"):] if obj["key"].startswith(f"{src_prefix}/") else obj["key"]
        await s3.copy_object(obj["key"], f"{dst_prefix}/{suffix}")
    return branch


@router.get("/workspace-projects/{project_id}/branches", dependencies=[RequireScope("read")])
async def list_branches(project_id: str, store: StoreD):
    await _get_project_or_404(store, project_id)
    await store.ensure_main_branch(project_id)
    branches = await store.list_branches(project_id)
    return {"branches": branches}


@router.delete("/workspace-projects/{project_id}/branches/{branch_name}", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_branch(project_id: str, branch_name: str, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    try:
        deleted = await store.delete_branch(project_id, branch_name)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Branch '{branch_name}' not found")
    await s3.delete_prefix(_branch_prefix(proj.s3_prefix, branch_name))


# ─── User Session ────────────────────────────────────────────────────────────


@router.get("/workspace-projects/{project_id}/user-session", response_model=UserSessionInfo, dependencies=[RequireScope("read")])
async def get_user_session(project_id: str, store: StoreD):
    await _get_project_or_404(store, project_id)
    return await store.get_user_session(project_id)


@router.put("/workspace-projects/{project_id}/user-session", response_model=UserSessionInfo, dependencies=[RequireScope("write")])
async def update_user_session(project_id: str, body: UserSessionUpdate, store: StoreD):
    await _get_project_or_404(store, project_id)
    try:
        return await store.switch_branch(project_id, body.branch)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── Branch-Scoped File Endpoints ────────────────────────────────────────────


@router.get("/workspace-projects/{project_id}/branches/{branch_name}/files", dependencies=[RequireScope("read")])
async def list_branch_files(project_id: str, branch_name: str, store: StoreD, s3: S3D, prefix: str = Query("", max_length=500)):
    proj = await _get_project_or_404(store, project_id)
    await _get_branch_or_404(store, project_id, branch_name)
    bp = _branch_prefix(proj.s3_prefix, branch_name)
    s3_prefix = f"{bp}/{prefix}" if prefix else bp
    objects = await s3.list_objects(s3_prefix)
    strip_prefix = f"{bp}/"
    files = [
        FileInfo(key=o["key"][len(strip_prefix):] if o["key"].startswith(strip_prefix) else o["key"], size=o["size"], last_modified=o["last_modified"])
        for o in objects
    ]
    return {"project_id": project_id, "branch": branch_name, "prefix": prefix, "files": files}


@router.get("/workspace-projects/{project_id}/branches/{branch_name}/files/{file_path:path}", dependencies=[RequireScope("read")])
async def read_branch_file(project_id: str, branch_name: str, file_path: str, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    await _get_branch_or_404(store, project_id, branch_name)
    try:
        data = await s3.get_object(f"{_branch_prefix(proj.s3_prefix, branch_name)}/{file_path}")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    return Response(content=data, media_type=_detect_content_type(file_path))


@router.put("/workspace-projects/{project_id}/branches/{branch_name}/files/{file_path:path}", status_code=201, dependencies=[RequireScope("write")])
async def write_branch_file(project_id: str, branch_name: str, file_path: str, request: Request, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    branch = await _get_branch_or_404(store, project_id, branch_name)
    _check_write_permission(branch, request)
    body = await request.body()
    if len(body) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large (max {_MAX_FILE_SIZE // 1024 // 1024}MB)")
    ct = request.headers.get("content-type", "application/octet-stream")
    key = await s3.put_object(f"{_branch_prefix(proj.s3_prefix, branch_name)}/{file_path}", body, ct)
    return {"key": key, "size": len(body)}


@router.delete("/workspace-projects/{project_id}/branches/{branch_name}/files/{file_path:path}", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_branch_file(project_id: str, branch_name: str, file_path: str, request: Request, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    branch = await _get_branch_or_404(store, project_id, branch_name)
    _check_write_permission(branch, request)
    await s3.delete_object(f"{_branch_prefix(proj.s3_prefix, branch_name)}/{file_path}")


class _FileOp(_BaseModel):
    source: str
    destination: str


class _SearchQuery(_BaseModel):
    q: str
    max_results: int = 50


@router.post("/workspace-projects/{project_id}/branches/{branch_name}/files:rename", dependencies=[RequireScope("write")])
async def rename_branch_file(project_id: str, branch_name: str, body: _FileOp, request: Request, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    branch = await _get_branch_or_404(store, project_id, branch_name)
    _check_write_permission(branch, request)
    bp = _branch_prefix(proj.s3_prefix, branch_name)
    moved = await _copy_and_delete(s3, bp, body.source, body.destination)
    return {"moved": moved}


@router.post("/workspace-projects/{project_id}/branches/{branch_name}/files:copy", dependencies=[RequireScope("write")])
async def copy_branch_file(project_id: str, branch_name: str, body: _FileOp, request: Request, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    branch = await _get_branch_or_404(store, project_id, branch_name)
    _check_write_permission(branch, request)
    bp = _branch_prefix(proj.s3_prefix, branch_name)
    copied = await _copy_tree(s3, bp, body.source, body.destination)
    return {"copied": copied}


@router.post("/workspace-projects/{project_id}/branches/{branch_name}/files:move", dependencies=[RequireScope("write")])
async def move_branch_file(project_id: str, branch_name: str, body: _FileOp, request: Request, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    branch = await _get_branch_or_404(store, project_id, branch_name)
    _check_write_permission(branch, request)
    bp = _branch_prefix(proj.s3_prefix, branch_name)
    moved = await _copy_and_delete(s3, bp, body.source, body.destination)
    return {"moved": moved}


@router.post("/workspace-projects/{project_id}/branches/{branch_name}/files:search", dependencies=[RequireScope("read")])
async def search_branch_files(project_id: str, branch_name: str, body: _SearchQuery, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    await _get_branch_or_404(store, project_id, branch_name)
    bp = _branch_prefix(proj.s3_prefix, branch_name)
    all_files = await s3.list_objects(bp, max_keys=5000)
    query = body.q.lower()
    strip = f"{bp}/"
    matches = []
    for f in all_files:
        rel = f["key"][len(strip):] if f["key"].startswith(strip) else f["key"]
        if query in rel.lower():
            matches.append(FileInfo(key=rel, size=f["size"], last_modified=f["last_modified"]))
            if len(matches) >= body.max_results:
                break
    return {"query": body.q, "results": matches}


# ─── Backward-Compatible Flat File Endpoints (route to main branch) ──────────


@router.get("/workspace-projects/{project_id}/files", dependencies=[RequireScope("read")])
async def list_files(project_id: str, store: StoreD, s3: S3D, prefix: str = Query("", max_length=500)):
    proj = await _get_project_or_404(store, project_id)
    await store.ensure_main_branch(project_id)
    bp = _branch_prefix(proj.s3_prefix, "main")
    s3_prefix = f"{bp}/{prefix}" if prefix else bp
    objects = await s3.list_objects(s3_prefix)
    strip = f"{bp}/"
    files = [
        FileInfo(key=o["key"][len(strip):] if o["key"].startswith(strip) else o["key"], size=o["size"], last_modified=o["last_modified"])
        for o in objects
    ]
    return {"project_id": project_id, "prefix": prefix, "files": files}


@router.get("/workspace-projects/{project_id}/files/{file_path:path}", dependencies=[RequireScope("read")])
async def read_file(project_id: str, file_path: str, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    await store.ensure_main_branch(project_id)
    try:
        data = await s3.get_object(f"{_branch_prefix(proj.s3_prefix, 'main')}/{file_path}")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    return Response(content=data, media_type=_detect_content_type(file_path))


@router.put("/workspace-projects/{project_id}/files/{file_path:path}", status_code=201, dependencies=[RequireScope("write")])
async def write_file(project_id: str, file_path: str, request: Request, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    await store.ensure_main_branch(project_id)
    body = await request.body()
    if len(body) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large (max {_MAX_FILE_SIZE // 1024 // 1024}MB)")
    ct = request.headers.get("content-type", "application/octet-stream")
    key = await s3.put_object(f"{_branch_prefix(proj.s3_prefix, 'main')}/{file_path}", body, ct)
    return {"key": key, "size": len(body)}


@router.delete("/workspace-projects/{project_id}/files/{file_path:path}", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_file(project_id: str, file_path: str, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    await store.ensure_main_branch(project_id)
    await s3.delete_object(f"{_branch_prefix(proj.s3_prefix, 'main')}/{file_path}")


@router.post("/workspace-projects/{project_id}/files:rename", dependencies=[RequireScope("write")])
async def rename_file(project_id: str, body: _FileOp, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    await store.ensure_main_branch(project_id)
    bp = _branch_prefix(proj.s3_prefix, "main")
    return {"moved": await _copy_and_delete(s3, bp, body.source, body.destination)}


@router.post("/workspace-projects/{project_id}/files:copy", dependencies=[RequireScope("write")])
async def copy_file(project_id: str, body: _FileOp, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    await store.ensure_main_branch(project_id)
    bp = _branch_prefix(proj.s3_prefix, "main")
    return {"copied": await _copy_tree(s3, bp, body.source, body.destination)}


@router.post("/workspace-projects/{project_id}/files:move", dependencies=[RequireScope("write")])
async def move_file(project_id: str, body: _FileOp, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    await store.ensure_main_branch(project_id)
    bp = _branch_prefix(proj.s3_prefix, "main")
    return {"moved": await _copy_and_delete(s3, bp, body.source, body.destination)}


@router.post("/workspace-projects/{project_id}/files:search", dependencies=[RequireScope("read")])
async def search_files(project_id: str, body: _SearchQuery, store: StoreD, s3: S3D):
    proj = await _get_project_or_404(store, project_id)
    await store.ensure_main_branch(project_id)
    bp = _branch_prefix(proj.s3_prefix, "main")
    all_files = await s3.list_objects(bp, max_keys=5000)
    query = body.q.lower()
    strip = f"{bp}/"
    matches = []
    for f in all_files:
        rel = f["key"][len(strip):] if f["key"].startswith(strip) else f["key"]
        if query in rel.lower():
            matches.append(FileInfo(key=rel, size=f["size"], last_modified=f["last_modified"]))
            if len(matches) >= body.max_results:
                break
    return {"query": body.q, "results": matches}


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _copy_tree(s3, prefix: str, source: str, destination: str) -> int:
    src = f"{prefix}/{source}"
    dst = f"{prefix}/{destination}"
    head = await s3.head_object(src)
    if head:
        await s3.copy_object(src, dst)
        return 1
    objects = await s3.list_objects(src, max_keys=5000)
    if not objects:
        raise HTTPException(status_code=404, detail=f"Source not found: {source}")
    count = 0
    src_rel = f"{src}/"
    for obj in objects:
        suffix = obj["key"][len(src_rel):] if obj["key"].startswith(src_rel) else obj["key"][len(src):]
        await s3.copy_object(obj["key"], f"{dst}/{suffix}")
        count += 1
    return count


async def _copy_and_delete(s3, prefix: str, source: str, destination: str) -> int:
    count = await _copy_tree(s3, prefix, source, destination)
    src = f"{prefix}/{source}"
    head = await s3.head_object(src)
    if head:
        await s3.delete_object(src)
    else:
        await s3.delete_prefix(src)
    return count
