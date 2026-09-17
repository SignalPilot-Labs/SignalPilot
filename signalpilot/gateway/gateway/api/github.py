"""GitHub App installation flow + REST endpoints."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from ..config.github import get_github_settings
from ..models.github import (
    GitCredentialsResponse,
    GitHubInstallationInfo,
    GitHubRepoImportRequest,
    GitHubRepoImportResult,
    GitHubRepoInfo,
    GitHubRepoLinkCreate,
    GitHubRepoLinkInfo,
)
from ..runtime.mode import is_cloud_mode
from ..security.scope_guard import RequireScope
from ._oauth_state import make_state, verify_state
from .deps import ProjectsGate, StoreD
from .github_installs import router as installs_router
from .github_prs import router as prs_router
from .github_sync import _import_workspace_revision
from .github_sync import router as sync_router

logger = logging.getLogger(__name__)

router = APIRouter()


# OAuth Flow.


def _github_settings_redirect(web_url: str, **params: str) -> RedirectResponse:
    query = urlencode(params)
    suffix = f"?{query}" if query else ""
    return RedirectResponse(url=f"{web_url.rstrip('/')}/settings/github{suffix}", status_code=302)


@router.get("/api/github/install-url", dependencies=[RequireScope("write")])
async def github_install_url(store: StoreD):
    """Return the GitHub App installation URL with HMAC-signed state.

    Authenticated endpoint: org_id comes from the Clerk JWT / API key,
    not from a spoofable query param. The frontend calls this, gets the URL,
    and redirects the browser.
    """
    settings = get_github_settings()
    if not settings.is_configured:
        raise HTTPException(status_code=503, detail="GitHub App not configured")

    org_id = store.org_id or "local"
    state = make_state(org_id)
    install_url = f"https://github.com/apps/{settings.sp_github_app_slug}/installations/new?state={state}"
    return {"install_url": install_url}


@router.get("/auth/github/callback")
async def github_oauth_callback(
    installation_id: int | None = Query(None),
    state: str = Query(""),
    setup_action: str = Query("install"),
):
    """GitHub App installation callback (no OAuth code exchange).

    GitHub sends the browser here after install / update / request with
    ``installation_id`` and our signed ``state``. The state binds the flow to
    the org that started it; the app JWT proves the installation exists and
    which account owns it; the installation's own repository list becomes
    the token scope. ``setup_action=update`` refreshes an existing row.
    """
    settings = get_github_settings()
    if not settings.is_configured:
        return _github_settings_redirect(settings.sp_web_url, error="github_app_not_configured")

    org_id: str | None
    if is_cloud_mode():
        # GitHub's "redirect on update" carries no state. That case is resolved
        # below from the existing claim; a NEW claim always needs a valid state.
        org_id = verify_state(state) if state else None
    else:
        # Local mode: empty state falls back to "local", non-empty state is verified
        if state:
            org_id = verify_state(state)
            if org_id is None:
                org_id = "local"
        else:
            org_id = "local"

    if setup_action == "request" or installation_id is None:
        if org_id is None:
            return _github_settings_redirect(settings.sp_web_url, error="oauth_state_invalid")
        # The installer lacks rights on the GitHub account and an owner must
        # approve the request first; no installation exists yet. The row is
        # created when the owner's approval redirect (or discover) arrives.
        logger.info("GitHub App installation requested for org=%s (pending approval)", org_id)
        return _github_settings_redirect(settings.sp_web_url, pending="true")

    from ..db.engine import get_session_factory
    from ..store.github_installs import (
        InstallationClaimedError,
        InstallationNotFoundError,
        RepositoryListingError,
        active_claim_owners,
        complete_installation,
    )

    factory = get_session_factory()
    try:
        async with factory() as session:
            if org_id is None:
                # No usable state: only a refresh of an EXISTING single-org
                # claim is allowed (setup_action=update lands here). Nobody
                # holding the installation means a new claim, which is refused.
                owners = await active_claim_owners(session, installation_id)
                if len(owners) != 1:
                    logger.warning(
                        "GitHub callback without state for installation %s: %d claim owner(s); refusing",
                        installation_id, len(owners),
                    )
                    return _github_settings_redirect(settings.sp_web_url, error="oauth_state_invalid")
                org_id = owners[0]
                logger.info("GitHub App stateless %s refresh for installation %s org=%s", setup_action, installation_id, org_id)
            await complete_installation(session, org_id=org_id, github_installation_id=installation_id)
    except InstallationClaimedError:
        return _github_settings_redirect(settings.sp_web_url, error="installation_claimed")
    except InstallationNotFoundError as exc:
        logger.warning("GitHub installation %s not found for org=%s: %s", installation_id, org_id, exc)
        return _github_settings_redirect(settings.sp_web_url, error="installation_not_found")
    except RepositoryListingError as exc:
        logger.warning("GitHub installation %s repo listing failed (org=%s): %s", installation_id, org_id, exc)
        return _github_settings_redirect(settings.sp_web_url, error="repository_listing_failed")

    logger.info(
        "GitHub App %s: installation_id=%s org=%s", setup_action, installation_id, org_id,
    )
    return _github_settings_redirect(settings.sp_web_url, installed="true")


# Installation CRUD.


@router.get(
    "/api/github/installations",
    response_model=list[GitHubInstallationInfo],
    dependencies=[RequireScope("read")],
)
async def list_installations(store: StoreD):
    from ..store import github as gh_store
    return await gh_store.list_installations(store.session, org_id=store.org_id or "local")


@router.delete(
    "/api/github/installations/{installation_id}",
    status_code=204,
    response_model=None,
    dependencies=[RequireScope("write")],
)
async def delete_installation(installation_id: str, store: StoreD):
    from ..store import github as gh_store
    ok = await gh_store.delete_installation(store.session, org_id=store.org_id or "local", installation_id=installation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Installation not found")


# Repo Listing.


@router.get(
    "/api/github/installations/{installation_id}/repos",
    response_model=list[GitHubRepoInfo],
    dependencies=[RequireScope("read")],
)
async def list_repos(installation_id: str, store: StoreD):
    from ..store import github as gh_store
    from ..store.github_installs import RepositoryListingError, refresh_installation_repositories

    row = await gh_store.get_installation(store.session, org_id=store.org_id or "local", installation_id=installation_id)
    if not row:
        raise HTTPException(status_code=404, detail="Installation not found")

    # Live listing through the app: repositories added to the installation on
    # GitHub appear immediately, and the stored token scope follows.
    try:
        repos = await refresh_installation_repositories(store.session, row)
    except RepositoryListingError as exc:
        raise HTTPException(status_code=502, detail=f"Could not list installation repositories: {exc}")

    return [
        GitHubRepoInfo(
            id=r["id"],
            full_name=r["full_name"],
            name=r["name"],
            private=r["private"],
            default_branch=r.get("default_branch", "main"),
            description=r.get("description"),
            html_url=r.get("html_url", ""),
        )
        for r in repos
    ]


# Repo Links.

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


@router.get("/api/github/import/status", dependencies=[RequireScope("read")])
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
        store.session, org_id=store.org_id or "local", installation_id=body.installation_id,
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
        await _asyncio.to_thread(
            materialize_local_branches, body.project_id, body.default_branch or "main"
        )
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
        _update(GatewayGitHubRepoLink)
        .where(GatewayGitHubRepoLink.id == link.id)
        .values(last_sync_at=_time.time())
    )
    await store.session.commit()

    # Three-tier model: GitHub is the canonical pull source — connecting a
    # repo imports its tree as the branch's next workspace (S3) revision.
    # Best-effort: a storage hiccup must not undo the link that was created.
    _set_import_progress(org_for_progress, body.repo_full_name, "importing-files")

    def _file_progress(done: int, total: int) -> None:
        _set_import_progress(
            org_for_progress, body.repo_full_name, "importing-files", done=done, total=total
        )

    await _import_workspace_revision(
        store.session,
        org_id=store.org_id or "local",
        project_id=body.project_id,
        branch=body.default_branch or None,
        progress_cb=_file_progress,
    )

    return link


@router.post(
    "/api/github/repo-links",
    status_code=201,
    response_model=GitHubRepoLinkInfo,
    dependencies=[RequireScope("write")],
)
async def create_repo_link(body: GitHubRepoLinkCreate, store: StoreD):
    return await _establish_repo_link(store, body)


def _project_slug_for_repo(repo_full_name: str) -> str:
    import re as _re

    repo_name = repo_full_name.split("/")[-1]
    slug = _re.sub(r"[^a-zA-Z0-9_-]+", "-", repo_name).strip("-")
    return (slug or "project")[:64]


@router.post(
    "/api/github/import",
    status_code=201,
    response_model=GitHubRepoImportResult,
    dependencies=[RequireScope("write"), ProjectsGate],
)
async def import_github_repo(body: GitHubRepoImportRequest, store: StoreD):
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
        await store.session.execute(
            _select(GatewayWorkspaceProject).where(
                GatewayWorkspaceProject.org_id == org_id,
                GatewayWorkspaceProject.name == slug,
                GatewayWorkspaceProject.status == "active",
            )
        )
    ).scalars().first()
    if orphan is not None:
        occupied = await gh_store.get_repo_link_for_project(
            store.session, org_id=org_id, project_id=orphan.id
        )
        if occupied is None:
            project = await store.get_workspace_project(orphan.id)
            logger.info(
                "Import re-attaching %s to existing project %s", body.repo_full_name, orphan.id
            )

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


@router.get(
    "/api/github/repo-links",
    response_model=list[GitHubRepoLinkInfo],
    dependencies=[RequireScope("read")],
)
async def list_repo_links(store: StoreD, project_id: str | None = Query(None)):
    from ..store import github as gh_store
    return await gh_store.list_repo_links(store.session, org_id=store.org_id or "local", project_id=project_id)


@router.delete(
    "/api/github/repo-links/{link_id}",
    status_code=204,
    response_model=None,
    dependencies=[RequireScope("write")],
)
async def delete_repo_link(link_id: str, store: StoreD):
    from ..store import github as gh_store
    ok = await gh_store.delete_repo_link(store.session, org_id=store.org_id or "local", link_id=link_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Repo link not found")


# Git Credentials.


@router.get(
    "/api/github/credentials/{project_id}",
    response_model=GitCredentialsResponse,
    # The response embeds a live installation token with push rights, so it is
    # a write capability (SP-12). Notebook/chat session tokens carry write.
    dependencies=[RequireScope("write")],
)
async def get_git_credentials(project_id: str, store: StoreD):
    from ..store import github as gh_store

    org_id = store.org_id or "local"
    link = await gh_store.get_repo_link_for_project(store.session, org_id=org_id, project_id=project_id)
    if not link:
        return GitCredentialsResponse(source="managed", clone_url=None)

    installation = await gh_store.get_installation(store.session, org_id=org_id, installation_id=link.installation_id)
    if not installation or installation.status != "active":
        return GitCredentialsResponse(source="github", clone_url=None, default_branch=link.default_branch)

    token = await gh_store.get_valid_token(store.session, installation)
    clone_url = f"https://x-access-token:{token}@github.com/{link.repo_full_name}.git"

    return GitCredentialsResponse(
        source="github",
        clone_url=clone_url,
        default_branch=link.default_branch,
        expires_at=installation.token_expires_at,
    )


router.include_router(sync_router)
router.include_router(installs_router)
router.include_router(prs_router)
