"""Workspace project + file endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response

from ..models.workspace import FileInfo, WorkspaceProjectCreate, WorkspaceProjectInfo, WorkspaceProjectUpdate
from ..security.scope_guard import RequireScope
from .deps import S3D, StoreD

router = APIRouter(prefix="/api")

_MAX_FILE_SIZE = 10 * 1024 * 1024


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
    proj = await store.get_workspace_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


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
    proj = await store.get_workspace_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    await s3.delete_prefix(proj.s3_prefix)
    await store.delete_workspace_project(project_id)


# ─── File endpoints ──────────────────────────────────────────────────────────


@router.get("/workspace-projects/{project_id}/files", dependencies=[RequireScope("read")])
async def list_files(project_id: str, store: StoreD, s3: S3D, prefix: str = Query("", max_length=500)):
    proj = await store.get_workspace_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    s3_prefix = f"{proj.s3_prefix}/{prefix}" if prefix else proj.s3_prefix
    objects = await s3.list_objects(s3_prefix)
    files = [FileInfo(key=o["key"], size=o["size"], last_modified=o["last_modified"]) for o in objects]
    return {"project_id": project_id, "prefix": prefix, "files": files}


@router.get("/workspace-projects/{project_id}/files/{file_path:path}", dependencies=[RequireScope("read")])
async def read_file(project_id: str, file_path: str, store: StoreD, s3: S3D):
    proj = await store.get_workspace_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        data = await s3.get_object(f"{proj.s3_prefix}/{file_path}")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    content_type = "text/plain"
    if file_path.endswith(".json"):
        content_type = "application/json"
    elif file_path.endswith(".yml") or file_path.endswith(".yaml"):
        content_type = "text/yaml"
    elif file_path.endswith(".py"):
        content_type = "text/x-python"
    elif file_path.endswith(".sql"):
        content_type = "text/sql"
    return Response(content=data, media_type=content_type)


@router.put("/workspace-projects/{project_id}/files/{file_path:path}", status_code=201, dependencies=[RequireScope("write")])
async def write_file(project_id: str, file_path: str, request: Request, store: StoreD, s3: S3D):
    proj = await store.get_workspace_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    body = await request.body()
    if len(body) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large (max {_MAX_FILE_SIZE // 1024 // 1024}MB)")
    content_type = request.headers.get("content-type", "application/octet-stream")
    key = await s3.put_object(f"{proj.s3_prefix}/{file_path}", body, content_type)
    return {"key": key, "size": len(body)}


@router.delete("/workspace-projects/{project_id}/files/{file_path:path}", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_file(project_id: str, file_path: str, store: StoreD, s3: S3D):
    proj = await store.get_workspace_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    await s3.delete_object(f"{proj.s3_prefix}/{file_path}")
