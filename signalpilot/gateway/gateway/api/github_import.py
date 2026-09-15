"""GitHub repo-link creation and one-click import.

Split out of ``gateway/api/github.py``: the in-process import-progress map,
the shared repo-link establishment helper (clone into the bare repo + import
the S3 revision), the repo-link / import endpoints, and the best-effort
GitHub -> S3 revision import used by both linking and sync.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from ..auth import OrgAdmin
from ..models.github import (
    GitHubRepoImportRequest,
    GitHubRepoImportResult,
    GitHubRepoLinkCreate,
    GitHubRepoLinkInfo,
)
from ..security.scope_guard import RequireScope
from .deps import RequireBillablePlan, StoreD

logger = logging.getLogger(__name__)

import_router = APIRouter()


async def _import_workspace_revision(session, *, org_id: str, project_id: str, branch: str | None, progress_cb=None):
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
            session,
            storage,
            org_id=org_id,
            project_id=project_id,
            branch=branch,
            progress_cb=progress_cb,
        )
        return {"imported": result.imported, "revision": result.revision}
    except Exception as e:
        logger.warning("Workspace import failed for project %s: %s", project_id, e)
        return {"error": str(e)}


# Live import progress, keyed by (org_id, repo_full_name). In-process only:
# the UI polls this while its POST /api/github/import is in flight, so the
# answering process is by construction the one doing the work.
_IMPORT_PROGRESS: dict[tuple[str, str], dict] = {}
_IMPORT_PROGRESS_MAX = 100


def _set_import_progress(
    org_id: str,
    repo_full_name: str,
    stage: str,
    *,
    done: int | None = None,
    total: int | None = None,
    error: str | None = None,
) -> None:
    import time as _time

    entry: dict = {"stage": stage, "updated_at": _time.time()}
    if done is not None:
        entry["done"] = done
        entry["total"] = total
    if error is not None:
        entry["error"] = error
    _IMPORT_PROGRESS[(org_id, repo_full_name)] = entry
    while len(_IMPORT_PROGRESS) > _IMPORT_PROGRESS_MAX:
        oldest = min(_IMPORT_PROGRESS, key=lambda k: _IMPORT_PROGRESS[k]["updated_at"])
        del _IMPORT_PROGRESS[oldest]


@import_router.get("/api/github/import/status", dependencies=[RequireScope("read")])
async def github_import_status(store: StoreD, repo_full_name: str = Query(...)):
    """Live stage of an in-flight import for this org's repo. Poll while the
    import POST is pending; `idle` means nothing is (or was recently) running."""
    entry = _IMPORT_PROGRESS.get((store.org_id or "local", repo_full_name))
    return entry or {"stage": "idle"}


async def _establish_repo_link(store, body: GitHubRepoLinkCreate) -> GitHubRepoLinkInfo:
    """Create the link row, clone into the bare repo, and import the S3 revision.

    Shared by the explicit repo-links endpoint and the one-click import flow.
    """
    from ..store import github as gh_store

    try:
        link = await gh_store.create_repo_link(
            store.session,
            org_id=store.org_id or "local",
            project_id=body.project_id,
            installation_id=body.installation_id,
            repo_full_name=body.repo_full_name,
            repo_id=body.repo_id,
            default_branch=body.default_branch,
        )
    except Exception as e:
        if "uq_gw_ghrepo_org_project" in str(e):
            raise HTTPException(status_code=409, detail="Project already linked to a repo")
        raise

    # Clone the GitHub repo into the bare repo synchronously before returning.
    # This must succeed: without it, the bare repo doesn't exist and clone-url is a lie.
    installation = await gh_store.get_installation(
        store.session,
        org_id=store.org_id or "local",
        installation_id=body.installation_id,
    )
    if not installation:
        raise HTTPException(status_code=400, detail="GitHub installation not found")

    token = await gh_store.get_valid_token(store.session, installation)
    remote_url = f"https://x-access-token:{token}@github.com/{body.repo_full_name}.git"

    import asyncio as _asyncio

    from ..git.repos import clone_from_remote, materialize_local_branches

    org_for_progress = store.org_id or "local"
    _set_import_progress(org_for_progress, body.repo_full_name, "cloning")
    try:
        # Blocking subprocess work — keep it off the event loop.
        await _asyncio.to_thread(clone_from_remote, body.project_id, remote_url)
        # The bare repo is usually pre-created at project creation, so the line
        # above does a `git fetch` that only populates refs/remotes/github/*.
        # Materialize local refs/heads/* (+ HEAD) so the pod's clone sees files.
        await _asyncio.to_thread(materialize_local_branches, body.project_id, body.default_branch or "main")
        logger.info("Cloned GitHub repo %s into bare repo for project %s", body.repo_full_name, body.project_id)
    except Exception as e:
        logger.error("GitHub clone failed for %s: %s", body.repo_full_name, e)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to clone GitHub repo: {e}. The repo link was created but the bare repo is missing.",
        )

    # Update last_sync_at
    import time as _time

    from sqlalchemy import update as _update

    from ..db.models import GatewayGitHubRepoLink

    await store.session.execute(
        _update(GatewayGitHubRepoLink).where(GatewayGitHubRepoLink.id == link.id).values(last_sync_at=_time.time())
    )
    await store.session.commit()

    # Three-tier model: GitHub is the canonical pull source — connecting a
    # repo imports its tree as the branch's next workspace (S3) revision.
    # Best-effort: a storage hiccup must not undo the link that was created.
    _set_import_progress(org_for_progress, body.repo_full_name, "importing-files")

    def _file_progress(done: int, total: int) -> None:
        _set_import_progress(org_for_progress, body.repo_full_name, "importing-files", done=done, total=total)

    await _import_workspace_revision(
        store.session,
        org_id=store.org_id or "local",
        project_id=body.project_id,
        branch=body.default_branch or None,
        progress_cb=_file_progress,
    )

    return link


@import_router.post(
    "/api/github/repo-links",
    status_code=201,
    response_model=GitHubRepoLinkInfo,
    dependencies=[RequireScope("write")],
)
async def create_repo_link(body: GitHubRepoLinkCreate, store: StoreD, _role: OrgAdmin):
    return await _establish_repo_link(store, body)


def _project_slug_for_repo(repo_full_name: str) -> str:
    import re as _re

    repo_name = repo_full_name.split("/")[-1]
    slug = _re.sub(r"[^a-zA-Z0-9_-]+", "-", repo_name).strip("-")
    return (slug or "project")[:64]


@import_router.post(
    "/api/github/import",
    status_code=201,
    response_model=GitHubRepoImportResult,
    dependencies=[RequireScope("write"), RequireBillablePlan],
)
async def import_github_repo(body: GitHubRepoImportRequest, store: StoreD, _role: OrgAdmin):
    """One-click import: auto-create a workspace project for a repo and link it.

    Idempotent — if the repo is already linked to a live project in this org,
    returns that project instead of creating a duplicate.
    """
    from ..store import github as gh_store

    org_id = store.org_id or "local"
    _set_import_progress(org_id, body.repo_full_name, "creating-project")

    existing = await gh_store.get_active_link_for_org_repo(
        store.session, org_id=org_id, repo_full_name=body.repo_full_name
    )
    if existing:
        project = await store.get_workspace_project(existing.project_id)
        if project and project.status == "active":
            _set_import_progress(org_id, body.repo_full_name, "done")
            return GitHubRepoImportResult(project=project, link=existing, created=False)
        # Stale link: its project was deleted or archived. Disconnect and re-import.
        await gh_store.delete_repo_link(store.session, org_id=org_id, link_id=existing.id)

    slug = _project_slug_for_repo(body.repo_full_name)
    repo_name = body.repo_full_name.split("/")[-1]
    project = None

    # Unlink keeps the project row. A re-link must re-attach to that project,
    # not fork a "name-2" duplicate: reuse the slug's project when it exists
    # and no other repo currently occupies it.
    from sqlalchemy import select as _select

    from ..db.models import GatewayWorkspaceProject

    orphan = (
        (
            await store.session.execute(
                _select(GatewayWorkspaceProject).where(
                    GatewayWorkspaceProject.org_id == org_id,
                    GatewayWorkspaceProject.name == slug,
                    GatewayWorkspaceProject.status == "active",
                )
            )
        )
        .scalars()
        .first()
    )
    if orphan is not None:
        occupied = await gh_store.get_repo_link_for_project(store.session, org_id=org_id, project_id=orphan.id)
        if occupied is None:
            project = await store.get_workspace_project(orphan.id)
            logger.info("Import re-attaching %s to existing project %s", body.repo_full_name, orphan.id)

    reused_project = project is not None

    for attempt in range(10):
        if project is not None:
            break
        candidate = slug if attempt == 0 else f"{slug[: 64 - len(str(attempt + 1)) - 1]}-{attempt + 1}"
        try:
            project = await store.create_workspace_project(
                name=candidate,
                display_name=repo_name,
                description="",
                source="github",
                tags=["github"],
            )
            break
        except Exception as e:
            if "uq_gw_wsproj_org_name" not in str(e):
                raise
            await store.session.rollback()
    if project is None:
        raise HTTPException(status_code=409, detail=f"Could not find a free project name for '{slug}'")

    try:
        link = await _establish_repo_link(
            store,
            GitHubRepoLinkCreate(
                project_id=project.id,
                installation_id=body.installation_id,
                repo_full_name=body.repo_full_name,
                repo_id=body.repo_id,
                default_branch=body.default_branch,
            ),
        )
    except HTTPException as exc:
        _set_import_progress(org_id, body.repo_full_name, "error", error=str(exc.detail)[:500])
        # A project created solely for this import holds nothing yet — remove
        # it so a retry starts clean. A REUSED project predates this call and
        # must survive; only its half-made link is rolled back.
        try:
            existing_link = await gh_store.get_repo_link_for_project(
                store.session, org_id=org_id, project_id=project.id
            )
            if existing_link is not None:
                await gh_store.delete_repo_link(store.session, org_id=org_id, link_id=existing_link.id)
            if not reused_project:
                await store.delete_workspace_project(project.id)
        except Exception as cleanup_err:
            logger.warning("Import cleanup failed for project %s: %s", project.id, cleanup_err)
        raise

    # Kick off the first dbt map compile so lineage is ready without any
    # manual step. Fire-and-forget: import success never depends on it.
    try:
        from ..dbt_map import schedule_compile

        schedule_compile(org_id, project.id, body.default_branch or "main", trigger="import")
    except Exception:
        logger.warning("dbt-map schedule after import failed for %s", project.id, exc_info=True)

    _set_import_progress(org_id, body.repo_full_name, "done")
    return GitHubRepoImportResult(project=project, link=link, created=True)
