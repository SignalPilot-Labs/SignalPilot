"""Workspace project CRUD + git clone-url endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..models.workspace import (
    WorkspaceProjectCreate,
    WorkspaceProjectInfo,
    WorkspaceProjectUpdate,
)
from ..security.scope_guard import RequireScope
from .deps import S3D, StoreD

router = APIRouter(prefix="/api")


async def _get_project_or_404(store, project_id: str) -> WorkspaceProjectInfo:
    proj = await store.get_workspace_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


# ─── Project CRUD ────────────────────────────────────────────────────────────


@router.post("/workspace-projects", status_code=201, response_model=WorkspaceProjectInfo, dependencies=[RequireScope("write")])
async def create_project(body: WorkspaceProjectCreate, store: StoreD):
    try:
        return await store.create_workspace_project(
            name=body.name,
            display_name=body.display_name,
            description=body.description,
            source=body.source,
            connection_name=body.connection_name,
            git_remote=body.git_remote,
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


@router.get("/workspace-projects/{project_id}/clone-url", dependencies=[RequireScope("read")])
async def get_clone_url(project_id: str, store: StoreD, request: Request):
    """Return the git clone URL for this project.

    Embeds auth token so notebooks/agents can clone directly.
    """
    project = await _get_project_or_404(store, project_id)

    from ..git.repos import repo_exists
    if not repo_exists(project_id):
        raise HTTPException(status_code=404, detail="Git repository not initialized")

    auth = getattr(request.state, "auth", None) or {}
    token = ""
    if auth.get("auth_method") == "api_key":
        token = request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    elif auth.get("auth_method") in ("local_key", "local_nokey"):
        from ..store import get_local_api_key
        token = get_local_api_key()

    scheme = request.url.scheme
    host = request.headers.get("host", "localhost:3300")

    if token:
        clone_url = f"{scheme}://x-access-token:{token}@{host}/git/{project_id}.git"
    else:
        clone_url = f"{scheme}://{host}/git/{project_id}.git"

    return {
        "clone_url": clone_url,
        "default_branch": project.default_branch or "main",
        "source": project.source,
        "has_repo": True,
    }


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
