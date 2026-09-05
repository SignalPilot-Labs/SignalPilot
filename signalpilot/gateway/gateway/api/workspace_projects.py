"""Workspace project CRUD + git clone-url endpoint."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request

from ..auth import DBSession, OrgID, UserID
from ..config.gateway import _LOCAL_GATEWAY_URL_DEFAULT, get_gateway_settings
from ..models.workspace import (
    WorkspaceProjectCreate,
    WorkspaceProjectInfo,
    WorkspaceProjectUpdate,
)
from ..runtime.mode import is_cloud_mode
from ..security.scope_guard import RequireScope
from ..workspace_store.dbt_detect import resolve_dbt_project_dir_detailed
from ..workspace_store.store import RevisionNotFound
from .deps import ProjectsGate, StoreD
from .workspace_files import WorkspaceStoreD, _valid_branch

logger = logging.getLogger(__name__)

# Workspace projects and lineage are available on every current plan.
# The gate remains the centralized entitlement boundary for future tiers.
router = APIRouter(prefix="/api", dependencies=[ProjectsGate])


def _is_loopback_gateway_url(url: str) -> bool:
    try:
        hostname = urlparse(url).hostname
    except ValueError:
        return False
    return hostname in {"localhost", "127.0.0.1", "::1"}


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

    Returns clone URL and auth token separately. The token is passed via
    HTTP Basic Auth, not embedded in the URL, to prevent leaking in logs.
    """
    project = await _get_project_or_404(store, project_id)

    from ..git.repos import repo_exists
    if not repo_exists(project_id):
        raise HTTPException(status_code=404, detail="Git repository not initialized")

    auth = getattr(request.state, "auth", None) or {}
    token = ""
    if auth.get("auth_method") == "api_key":
        token = request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    elif auth.get("auth_method") == "notebook_session":
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    elif auth.get("auth_method") in ("local_key", "local_nokey"):
        from ..store import get_local_api_key
        token = get_local_api_key()
    if not token:
        bearer = request.headers.get("authorization", "")
        if bearer.startswith("Bearer "):
            token = bearer[7:].strip()

    # R11-S-1: never reflect the inbound Host header in cloud mode — a spoofed
    # Host would steer the pod's authenticated git clone to an attacker origin.
    gw = get_gateway_settings()
    configured = (gw.sp_public_gateway_url or "").rstrip("/")
    if is_cloud_mode():
        # Use the public gateway URL (served via Caddy :443 -> gateway :3300). The
        # in-pod git client clones/pushes through this; hitting the gateway's
        # internal :3300 directly returns 403 from the git Smart-HTTP backend
        # (auth/host differs from the Caddy-proxied path), so the public URL is
        # required. Server-configured value, not the inbound Host header, so the
        # R11-S-1 Host-spoofing protection holds.
        base_url = f"{configured}/git/{project_id}.git"
    elif (
        configured
        and configured != _LOCAL_GATEWAY_URL_DEFAULT
        and not _is_loopback_gateway_url(configured)
    ):
        base_url = f"{configured}/git/{project_id}.git"
    else:
        # Local-mode dev fallback only: derive from Host so localhost:<random> works.
        scheme = request.url.scheme
        host = request.headers.get("host", "localhost:3300")
        base_url = f"{scheme}://{host}/git/{project_id}.git"

    return {
        "clone_url": base_url,
        "auth_token": token,
        "auth_method": "basic",
        "auth_username": "x-access-token",
        "default_branch": project.default_branch or "main",
        "source": project.source,
        "has_repo": True,
    }


@router.get("/workspace-projects/{project_id}/dbt-project-dir", dependencies=[RequireScope("read")])
async def get_dbt_project_dir(
    project_id: str,
    org_id: OrgID,
    _user: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
    branch: str = Query("main"),
):
    """Resolve where the dbt project lives inside this workspace project.

    An explicit settings["dbt_project_dir"] wins when the directory exists in
    the branch manifest; otherwise the shallowest manifest directory holding a
    dbt_project.yml (alphabetical tie-break); otherwise None. "" means the
    project root.
    """
    project = await _get_project_or_404(store, project_id)
    try:
        manifest = await ws.load_manifest(
            db, org_id=org_id, project_id=project_id, branch=_valid_branch(branch)
        )
    except RevisionNotFound:
        manifest = None  # branch has no revisions yet — nothing to detect
    value, source, detected = resolve_dbt_project_dir_detailed(project.settings, manifest)
    return {"dbt_project_dir": value, "detected": detected, "source": source}


@router.put("/workspace-projects/{project_id}", response_model=WorkspaceProjectInfo, dependencies=[RequireScope("write")])
async def update_project(project_id: str, body: WorkspaceProjectUpdate, store: StoreD):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    existing = await _get_project_or_404(store, project_id)
    if "sp-demo" in (existing.tags or []) and "tags" in updates:
        required = [
            tag
            for tag in (existing.tags or [])
            if tag == "sp-demo" or tag.startswith(("demo:", "journey:demo-"))
        ]
        updates["tags"] = list(dict.fromkeys([*required, *updates["tags"]]))
    proj = await store.update_workspace_project(project_id, updates)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


@router.delete("/workspace-projects/{project_id}", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_project(project_id: str, store: StoreD):
    """Delete a project and everything it owns: repo links, dbt maps, S3
    objects, and the bare git repo. The linked GitHub repo is never touched.
    Cascades are best-effort — a storage hiccup must not leave the project row
    behind for a retry loop to trip on."""
    import asyncio as _asyncio

    from sqlalchemy import delete as _delete

    from ..db.models import GatewayDbtManifest, GatewayGitHubRepoLink
    from ..git.repos import delete_repo
    from ..workspace_store import workspace_object_storage
    from ..workspace_store.store import WorkspaceStore

    await _get_project_or_404(store, project_id)
    org_id = store.org_id or "local"

    await store.session.execute(
        _delete(GatewayGitHubRepoLink).where(
            GatewayGitHubRepoLink.org_id == org_id,
            GatewayGitHubRepoLink.project_id == project_id,
        )
    )
    await store.session.execute(
        _delete(GatewayDbtManifest).where(
            GatewayDbtManifest.org_id == org_id,
            GatewayDbtManifest.project_id == project_id,
        )
    )
    await store.session.commit()

    storage = workspace_object_storage()
    if storage.enabled:
        try:
            purged = await WorkspaceStore(storage).purge_project_objects(
                org_id=org_id, project_id=project_id
            )
            logger.info("Project %s delete: purged %d S3 objects", project_id, purged)
        except Exception:
            logger.warning("Project %s delete: S3 purge failed", project_id, exc_info=True)
    try:
        await _asyncio.to_thread(delete_repo, project_id)
    except Exception:
        logger.warning("Project %s delete: bare repo removal failed", project_id, exc_info=True)

    await store.delete_workspace_project(project_id)
