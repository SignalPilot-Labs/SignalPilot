"""GitHub App OAuth flow + REST endpoints."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from ..config.github import get_github_settings
from ..models.github import (
    GitCredentialsResponse,
    GitHubInstallationInfo,
    GitHubRepoInfo,
    GitHubRepoLinkCreate,
    GitHubRepoLinkInfo,
)
from ..security.scope_guard import RequireScope
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter()

# ─── OAuth State ──────────────────────────────────────────────────────────

_HMAC_KEY: bytes | None = None


def _get_hmac_key() -> bytes:
    global _HMAC_KEY
    if _HMAC_KEY is None:
        import os
        raw = os.getenv("SP_ENCRYPTION_KEY", "github-oauth-state-key")
        _HMAC_KEY = hashlib.sha256(raw.encode()).digest()
    return _HMAC_KEY


def _make_state(org_id: str) -> str:
    nonce = secrets.token_hex(16)
    payload = f"{org_id}:{nonce}"
    sig = hmac.new(_get_hmac_key(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}.{sig}"


def _verify_state(state: str) -> str | None:
    parts = state.rsplit(".", 1)
    if len(parts) != 2:
        return None
    payload, sig = parts
    expected = hmac.new(_get_hmac_key(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected):
        return None
    org_id = payload.split(":", 1)[0]
    return org_id


# ─── OAuth Flow ──────────────────────────────────────────────────────────


@router.get("/auth/github")
async def github_oauth_start(request: Request):
    settings = get_github_settings()
    if not settings.is_configured:
        raise HTTPException(status_code=503, detail="GitHub App not configured")

    auth = getattr(request.state, "auth", None) or {}
    org_id = auth.get("org_id", "local")
    state = _make_state(org_id)

    install_url = f"https://github.com/apps/{settings.sp_github_app_slug}/installations/new?state={state}"
    return RedirectResponse(url=install_url, status_code=302)


@router.get("/auth/github/callback")
async def github_oauth_callback(
    installation_id: int = Query(...),
    code: str = Query(None),
    state: str = Query(""),
    setup_action: str = Query("install"),
):
    settings = get_github_settings()
    if not settings.is_configured:
        raise HTTPException(status_code=503, detail="GitHub App not configured")

    org_id = _verify_state(state) if state else "local"
    if org_id is None:
        org_id = "local"

    from ..github_client import (
        create_installation_token,
        generate_app_jwt,
        get_installation_details,
    )
    from ..store.crypto import _encrypt
    from ..db.engine import get_session_factory
    from ..store import github as gh_store

    app_jwt = generate_app_jwt(settings.sp_github_app_id, settings.sp_github_app_private_key)
    details = await get_installation_details(app_jwt, installation_id)
    token_data = await create_installation_token(app_jwt, installation_id)

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
        )

    redirect_url = f"{settings.sp_web_url}/connections/github?installed=true"
    logger.info("GitHub App installed: installation_id=%s org=%s", installation_id, org_id)
    return RedirectResponse(url=redirect_url, status_code=302)


# ─── Installation CRUD ──────────────────────────────────────────────────


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


# ─── Repo Listing ────────────────────────────────────────────────────────


@router.get(
    "/api/github/installations/{installation_id}/repos",
    response_model=list[GitHubRepoInfo],
    dependencies=[RequireScope("read")],
)
async def list_repos(installation_id: str, store: StoreD):
    from ..store import github as gh_store
    from ..github_client import list_installation_repos

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


# ─── Repo Links ──────────────────────────────────────────────────────────


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
    # This must succeed — without it, the bare repo doesn't exist and clone-url is a lie.
    installation = await gh_store.get_installation(
        store.session, org_id=store.org_id or "local", installation_id=body.installation_id,
    )
    if not installation:
        raise HTTPException(status_code=400, detail="GitHub installation not found")

    token = await gh_store.get_valid_token(store.session, installation)
    remote_url = f"https://x-access-token:{token}@github.com/{body.repo_full_name}.git"

    from ..git.repos import clone_from_remote, repo_exists
    try:
        clone_from_remote(body.project_id, remote_url)
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


# ─── Git Credentials ─────────────────────────────────────────────────────


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


# ─── GitHub Sync ─────────────────────────────────────────────────────


@router.post("/api/github/sync/{project_id}", dependencies=[RequireScope("write")])
async def sync_with_github(project_id: str, store: StoreD):
    """Bidirectional sync: fetch from GitHub, push local changes back.

    GitHub wins on conflicts — local branches are force-updated to match.
    Agent branches (signalpilot-agent/*) are never synced.
    If push can't fast-forward, creates a PR branch on GitHub.
    """
    from ..git.sync import sync_project_with_github

    org_id = store.org_id or "local"
    result = await sync_project_with_github(project_id, org_id)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/api/github/fetch/{project_id}", dependencies=[RequireScope("read")])
async def fetch_from_github(project_id: str, store: StoreD):
    """Fetch latest from GitHub into the bare repo (one-way pull)."""
    from ..git.sync import fetch_from_github as _fetch, configure_github_remote
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

    result = _fetch(project_id, remote_url)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
