"""GitHub App OAuth flow + REST endpoints."""

from __future__ import annotations

import logging
import time
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from ..config.github import get_github_settings
from ..models.github import (
    GitCredentialsResponse,
    GitHubInstallationInfo,
    GitHubRepoInfo,
    GitHubRepoLinkCreate,
    GitHubRepoLinkInfo,
)
from ..runtime.mode import is_cloud_mode
from ..security.scope_guard import RequireScope
from ._oauth_state import make_state, verify_state
from .deps import StoreD

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
    installation_id: int = Query(...),
    code: str = Query(None),
    state: str = Query(""),
    setup_action: str = Query("install"),
):
    settings = get_github_settings()
    if not settings.is_configured:
        return _github_settings_redirect(settings.sp_web_url, error="github_app_not_configured")

    if is_cloud_mode():
        if not state:
            return _github_settings_redirect(settings.sp_web_url, error="oauth_state_invalid")
        org_id = verify_state(state)
        if org_id is None:
            return _github_settings_redirect(settings.sp_web_url, error="oauth_state_invalid")
    else:
        # Local mode: empty state falls back to "local", non-empty state is verified
        if state:
            org_id = verify_state(state)
            if org_id is None:
                org_id = "local"
        else:
            org_id = "local"

    from ..db.engine import get_session_factory
    from ..github_client import (
        create_installation_token,
        create_unrestricted_installation_token,
        exchange_code_for_token,
        generate_app_jwt,
        get_installation_details,
        list_user_installation_repositories,
        list_user_installations,
    )
    from ..store import github as gh_store
    from ..store.crypto import _encrypt

    # Repository ids the authorizing user can actually reach inside the
    # installation. Populated in cloud mode only; stays None in local mode,
    # where there is no user token to intersect against.
    authorized_repository_ids: list[int] | None = None

    # Installation IDs are guessable integers, not authorization proof. Complete
    # the user-authorization leg and require the installation to be accessible
    # to the user who authorized this flow before minting a token for it.
    # Local mode skips this: there is no tenant boundary to cross.
    if is_cloud_mode():
        if not code:
            return _github_settings_redirect(settings.sp_web_url, error="oauth_code_missing")
        if not settings.sp_github_app_client_secret:
            logger.error("SP_GITHUB_APP_CLIENT_SECRET not set — cannot verify installation ownership")
            return _github_settings_redirect(settings.sp_web_url, error="github_app_not_configured")
        try:
            token_resp = await exchange_code_for_token(
                settings.sp_github_app_client_id, settings.sp_github_app_client_secret, code
            )
            user_token = token_resp.get("access_token")
            if not user_token:
                raise ValueError(token_resp.get("error", "no access_token in response"))
            user_installations = await list_user_installations(user_token)
        except Exception as e:
            logger.warning("GitHub user authorization failed for org=%s: %s", org_id, e)
            return _github_settings_redirect(settings.sp_web_url, error="oauth_verification_failed")
        if installation_id not in {inst.get("id") for inst in user_installations}:
            logger.warning(
                "GitHub installation_id=%s not accessible to authorizing user (org=%s)",
                installation_id, org_id,
            )
            return _github_settings_redirect(settings.sp_web_url, error="installation_not_authorized")

        # Installation visibility does not grant access to every installation repository.
        # Restrict the token to repositories that the user can access.
        # Refuse authorization when the intersection is empty.
        try:
            user_repos = await list_user_installation_repositories(user_token, installation_id)
        except Exception as e:
            logger.warning("Could not enumerate user-accessible repos for org=%s: %s", org_id, e)
            return _github_settings_redirect(settings.sp_web_url, error="oauth_verification_failed")
        authorized_repository_ids = [r["id"] for r in user_repos if r.get("id") is not None]
        if not authorized_repository_ids:
            logger.warning(
                "GitHub installation_id=%s has no user-accessible repositories (org=%s) — refusing to mint",
                installation_id, org_id,
            )
            return _github_settings_redirect(settings.sp_web_url, error="no_accessible_repositories")

    app_jwt = generate_app_jwt(settings.sp_github_app_id, settings.sp_github_app_private_key)
    details = await get_installation_details(app_jwt, installation_id)
    if authorized_repository_ids:
        token_data = await create_installation_token(
            app_jwt, installation_id, repository_ids=authorized_repository_ids
        )
    else:
        # Local/single-tenant install: no user token exists to intersect
        # against and there is no tenant boundary to cross.
        token_data = await create_unrestricted_installation_token(app_jwt, installation_id)

    token = token_data["token"]
    from datetime import datetime
    expires_str = token_data.get("expires_at", "")
    if expires_str:
        expires_at = datetime.fromisoformat(expires_str.replace("Z", "+00:00")).timestamp()
    else:
        expires_at = time.time() + 3600

    factory = get_session_factory()
    async with factory() as session:
        await gh_store.upsert_installation(
            session,
            org_id=org_id,
            github_installation_id=installation_id,
            github_account_login=details.get("account", {}).get("login", "unknown"),
            github_account_type=details.get("account", {}).get("type", "User"),
            access_token_enc=_encrypt(token),
            token_expires_at=expires_at,
            permissions=details.get("permissions"),
            authorized_repository_ids=authorized_repository_ids,
        )

    logger.info("GitHub App installed: installation_id=%s org=%s", installation_id, org_id)
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
    from ..github_client import list_installation_repos
    from ..store import github as gh_store

    row = await gh_store.get_installation(store.session, org_id=store.org_id or "local", installation_id=installation_id)
    if not row:
        raise HTTPException(status_code=404, detail="Installation not found")

    token = await gh_store.get_valid_token(store.session, row)
    repos = await list_installation_repos(token)

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


@router.post(
    "/api/github/repo-links",
    status_code=201,
    response_model=GitHubRepoLinkInfo,
    dependencies=[RequireScope("write")],
)
async def create_repo_link(body: GitHubRepoLinkCreate, store: StoreD):
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

    from ..git.repos import clone_from_remote, materialize_local_branches
    try:
        clone_from_remote(body.project_id, remote_url)
        # The bare repo is usually pre-created at project creation, so the line
        # above does a `git fetch` that only populates refs/remotes/github/*.
        # Materialize local refs/heads/* (+ HEAD) so the pod's clone sees files.
        materialize_local_branches(body.project_id, body.default_branch or "main")
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
    await _import_workspace_revision(
        store.session,
        org_id=store.org_id or "local",
        project_id=body.project_id,
        branch=body.default_branch or None,
    )

    return link


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
    dependencies=[RequireScope("read")],
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


# GitHub Sync.


async def _import_workspace_revision(session, *, org_id: str, project_id: str, branch: str | None):
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
            session, storage, org_id=org_id, project_id=project_id, branch=branch
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
