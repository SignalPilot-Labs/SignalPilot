"""GitHub App installation flow + REST endpoints."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from ..auth import OrgAdmin
from ..config.github import get_github_settings
from ..git.repos import github_token_remote_url
from ..models.github import (
    GitCredentialsResponse,
    GitHubInstallationInfo,
    GitHubRepoInfo,
    GitHubRepoLinkInfo,
)
from ..runtime.mode import is_cloud_mode
from ..security.scope_guard import RequireScope
from ._oauth_state import make_state, verify_state
from .deps import StoreD
from .github_import import (
    _establish_repo_link,  # noqa: F401  (re-export)
    _project_slug_for_repo,  # noqa: F401  (re-export)
    _set_import_progress,  # noqa: F401  (re-export)
    import_router,
)
from .github_installs import router as installs_router
from .github_prs import router as prs_router
from .github_sync import router as sync_router

logger = logging.getLogger(__name__)

router = APIRouter()


# OAuth Flow.


def _github_settings_redirect(web_url: str, **params: str) -> RedirectResponse:
    query = urlencode(params)
    suffix = f"?{query}" if query else ""
    return RedirectResponse(url=f"{web_url.rstrip('/')}/settings/github{suffix}", status_code=302)


@router.get("/api/github/install-url", dependencies=[RequireScope("write")])
async def github_install_url(store: StoreD, _role: OrgAdmin):
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
async def delete_installation(installation_id: str, store: StoreD, _role: OrgAdmin):
    from ..store import github as gh_store

    ok = await gh_store.delete_installation(
        store.session, org_id=store.org_id or "local", installation_id=installation_id
    )
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

    row = await gh_store.get_installation(
        store.session, org_id=store.org_id or "local", installation_id=installation_id
    )
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

# Import progress, repo-link creation and one-click import live in
# github_import.py; they register here so the route table is unchanged.
router.include_router(import_router)


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
async def delete_repo_link(link_id: str, store: StoreD, _role: OrgAdmin):
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
    clone_url = github_token_remote_url(token, link.repo_full_name)

    return GitCredentialsResponse(
        source="github",
        clone_url=clone_url,
        default_branch=link.default_branch,
        expires_at=installation.token_expires_at,
    )


router.include_router(sync_router)
router.include_router(installs_router)
router.include_router(prs_router)
