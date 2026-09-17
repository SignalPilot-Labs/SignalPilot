"""GitHub sync + fetch endpoints (split from api/github.py to stay under the file-size limit).

Mounted by ``api/github.py`` via ``router.include_router`` so registration in
``api/__init__.py`` is unchanged.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ..security.scope_guard import RequireScope
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter()

async def _import_workspace_revision(
    session, *, org_id: str, project_id: str, branch: str | None, progress_cb=None
):
    """Best-effort GitHub → S3 revision import (three-tier pull side).

    Never raises: the git operation that preceded it already succeeded, and
    editing/linking must not be blocked by workspace-store availability.
    Returns a small status dict for inclusion in API responses.
    """
    from ..workspace_store import workspace_object_storage
    from ..workspace_store.github_sync import import_repo_to_revisions

    storage = workspace_object_storage()
    if not storage.enabled:
        return {"skipped": True, "reason": "workspace storage not configured"}
    try:
        result = await import_repo_to_revisions(
            session, storage, org_id=org_id, project_id=project_id, branch=branch,
            progress_cb=progress_cb,
        )
        return {"imported": result.imported, "revision": result.revision}
    except Exception as e:
        logger.warning("Workspace import failed for project %s: %s", project_id, e)
        return {"error": str(e)}


@router.post("/api/github/sync/{project_id}", dependencies=[RequireScope("write")])
async def sync_with_github(project_id: str, store: StoreD):
    """Bidirectional sync: fetch from GitHub, push local changes back.

    GitHub wins on conflicts: local branches are force-updated to match.
    Agent branches (signalpilot-agent/*, analysis/*) are never synced.
    If push can't fast-forward, creates a PR branch on GitHub.

    Three-tier model: before the git sync, the branch's head workspace (S3)
    revision is exported as a commit (store side); afterwards, inbound GitHub
    changes are imported as a new workspace revision (pull side).
    """
    from ..git.sync import sync_project_with_github
    from ..store import github as gh_store

    org_id = store.org_id or "local"
    link = await gh_store.get_repo_link_for_project(store.session, org_id=org_id, project_id=project_id)
    default_branch = (link.default_branch or "main") if link else "main"

    # Store side: commit the saved working copy (head S3 revision) onto the
    # bare repo so the git sync pushes it. Best-effort — export failure never
    # blocks the sync or editing.
    export_status: dict = {"skipped": True, "reason": "workspace storage not configured"}
    from ..workspace_store import workspace_object_storage

    storage = workspace_object_storage()
    if storage.enabled:
        from ..workspace_store.github_sync import export_revision_to_git
        from ..workspace_store.store import RevisionNotFound

        try:
            export = await export_revision_to_git(
                store.session, storage, org_id=org_id, project_id=project_id, branch=default_branch
            )
            export_status = {
                "revision": export.revision,
                "commit_sha": export.commit_sha,
                "pushed": export.pushed,
            }
        except RevisionNotFound:
            export_status = {"skipped": True, "reason": "no workspace revisions on branch"}
        except Exception as e:
            logger.warning("Workspace export failed for project %s: %s", project_id, e)
            export_status = {"error": str(e)}

    result = await sync_project_with_github(project_id, org_id)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Pull side: whatever the fetch brought in becomes the next S3 revision.
    result["workspace_export"] = export_status
    result["workspace_import"] = await _import_workspace_revision(
        store.session, org_id=org_id, project_id=project_id, branch=default_branch
    )
    return result


@router.post("/api/github/fetch/{project_id}", dependencies=[RequireScope("read")])
async def fetch_from_github_endpoint(project_id: str, store: StoreD):
    """Fetch latest from GitHub into the bare repo (one-way pull)."""
    from ..git.sync import fetch_all, pull_branch
    from ..store import github as gh_store

    org_id = store.org_id or "local"
    link = await gh_store.get_repo_link_for_project(store.session, org_id=org_id, project_id=project_id)
    if not link:
        raise HTTPException(status_code=404, detail="No GitHub repo linked")

    installation = await gh_store.get_installation(store.session, org_id=org_id, installation_id=link.installation_id)
    if not installation:
        raise HTTPException(status_code=404, detail="GitHub installation not found")

    token = await gh_store.get_valid_token(store.session, installation)
    remote_url = f"https://x-access-token:{token}@github.com/{link.repo_full_name}.git"

    result = fetch_all(project_id, remote_url)
    if result.get("fetched"):
        pull_result = pull_branch(project_id, remote_url, link.default_branch or "main")
        result["pull"] = pull_result
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Pull side of the three-tier model: inbound GitHub changes become the
    # branch's next workspace (S3) revision.
    result["workspace_import"] = await _import_workspace_revision(
        store.session, org_id=org_id, project_id=project_id,
        branch=link.default_branch or "main",
    )
    return result
