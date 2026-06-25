"""Slack OAuth integration endpoints."""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api.deps import StoreD
from gateway.auth import OrgAdmin
from gateway.db.engine import get_db
from gateway.models.slack import (
    SlackOAuthInstallationInfo,
    SlackOAuthStartResponse,
    SlackProvisionRequest,
    SlackProvisionResponse,
)
from gateway.security.scope_guard import RequireScope
from gateway.store import slack as slack_store

router = APIRouter(prefix="/api/integrations/slack")

SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
SLACK_OAUTH_ACCESS_URL = "https://slack.com/api/oauth.v2.access"
DEFAULT_SLACK_SCOPES = ",".join(
    [
        "app_mentions:read",
        "channels:history",
        "chat:write",
        "files:write",
        "groups:history",
        "im:history",
        "mpim:history",
        "reactions:write",
    ]
)


def _slack_oauth_client_id() -> str:
    value = os.getenv("SLACK_OAUTH_CLIENT_ID") or os.getenv("SLACK_CLIENT_ID")
    if not value:
        raise HTTPException(status_code=503, detail="SLACK_OAUTH_CLIENT_ID is not configured")
    return value


def _slack_oauth_client_secret() -> str:
    value = os.getenv("SLACK_OAUTH_CLIENT_SECRET") or os.getenv("SLACK_CLIENT_SECRET")
    if not value:
        raise HTTPException(status_code=503, detail="SLACK_OAUTH_CLIENT_SECRET is not configured")
    return value


def _slack_redirect_uri(request: Request) -> str:
    return os.getenv("SLACK_OAUTH_REDIRECT_URI") or str(request.url_for("slack_oauth_callback"))


def _slack_oauth_scopes() -> str:
    return os.getenv("SLACK_OAUTH_SCOPES") or DEFAULT_SLACK_SCOPES


def build_slack_authorize_url(client_id: str, redirect_uri: str, state: str, scopes: str | None = None) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "scope": scopes or DEFAULT_SLACK_SCOPES,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{SLACK_AUTHORIZE_URL}?{query}"


async def exchange_slack_oauth_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            SLACK_OAUTH_ACCESS_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        detail = data.get("error") or "Slack OAuth failed"
        raise HTTPException(status_code=400, detail=f"Slack OAuth failed: {detail}")
    return data


def _redirect_fallback_url() -> str:
    web_url = os.getenv("SIGNALPILOT_WEB_URL") or os.getenv("SP_WEB_URL")
    if web_url:
        return f"{web_url.rstrip('/')}/integrations"
    return "/integrations"


def _origin_for_url(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _allowed_redirect_origins() -> set[str]:
    origins: set[str] = set()
    for value in (os.getenv("SIGNALPILOT_WEB_URL"), os.getenv("SP_WEB_URL")):
        if value and (origin := _origin_for_url(value)):
            origins.add(origin)
    for value in (os.getenv("SP_ALLOWED_ORIGINS") or "").split(","):
        if value and (origin := _origin_for_url(value.strip())):
            origins.add(origin)
    if not origins:
        origins.update(
            {
                "http://localhost:3000",
                "http://localhost:3200",
                "http://localhost:3210",
                "http://127.0.0.1:3000",
                "http://127.0.0.1:3200",
                "http://127.0.0.1:3210",
            }
        )
    return origins


def _is_safe_redirect_target(target: str) -> bool:
    if not target or target.startswith(("//", "\\")):
        return False
    parsed = urlparse(target)
    if not parsed.scheme and not parsed.netloc:
        return target.startswith("/")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    return _origin_for_url(target) in _allowed_redirect_origins()


def _safe_redirect_url(value: str | None, installation_id: str | None = None, status: str = "connected") -> str:
    fallback = _redirect_fallback_url()
    target = value or fallback
    if not _is_safe_redirect_target(target):
        target = fallback if _is_safe_redirect_target(fallback) else "/integrations"

    parsed = urlparse(target)
    params = {"slack": status}
    if installation_id:
        params["slack_installation_id"] = installation_id
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend(params.items())
    return urlunparse(parsed._replace(query=urlencode(query)))


@router.get("/oauth/start", dependencies=[RequireScope("write")])
async def start_slack_oauth(
    request: Request,
    store: StoreD,
    _role: OrgAdmin,
    redirect_after: str | None = Query(default=None),
) -> SlackOAuthStartResponse:
    """Create OAuth state and return the Slack authorization URL."""
    redirect_uri = _slack_redirect_uri(request)
    state = await store.create_slack_oauth_state(redirect_after=redirect_after)
    return SlackOAuthStartResponse(
        authorize_url=build_slack_authorize_url(
            _slack_oauth_client_id(),
            redirect_uri,
            state,
            _slack_oauth_scopes(),
        ),
        state=state,
    )


@router.get("/oauth/callback", name="slack_oauth_callback")
async def slack_oauth_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """OAuth callback from Slack. Tenant context comes from the stored state row."""
    if error:
        raise HTTPException(status_code=400, detail=f"Slack OAuth failed: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing Slack OAuth code or state")

    state_row = await slack_store.consume_oauth_state(db, state)
    if state_row is None:
        raise HTTPException(status_code=400, detail="Invalid or expired Slack OAuth state")

    token_response = await exchange_slack_oauth_code(
        _slack_oauth_client_id(),
        _slack_oauth_client_secret(),
        code,
        _slack_redirect_uri(request),
    )
    try:
        installation = await slack_store.upsert_oauth_installation(
            db,
            org_id=state_row.org_id,
            user_id=state_row.user_id,
            token_response=token_response,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(_safe_redirect_url(state_row.redirect_after, installation.id, "connected"))


@router.get("/oauth/installations", dependencies=[RequireScope("read")])
async def list_slack_oauth_installations(store: StoreD) -> list[SlackOAuthInstallationInfo]:
    """List Slack OAuth installations for the current org."""
    return await store.list_slack_oauth_installations()


@router.post("/oauth/{installation_id}/provision", dependencies=[RequireScope("write")])
async def provision_slack_oauth_installation(
    installation_id: str,
    body: SlackProvisionRequest,
    store: StoreD,
    _role: OrgAdmin,
) -> SlackProvisionResponse:
    """Configure default project routing for a Slack installation."""
    if await store.get_workspace_project(body.default_project_id) is None:
        raise HTTPException(status_code=404, detail="Default project not found")

    installation = await store.save_slack_oauth_installation_config(
        installation_id,
        enabled=True,
        default_project_id=body.default_project_id,
        default_branch=body.default_branch,
        analysis_branch_mode=body.analysis_branch_mode,
        allowed_channel_ids=body.allowed_channel_ids,
    )
    if installation is None:
        raise HTTPException(status_code=404, detail="Slack installation not found")
    return SlackProvisionResponse(installation=installation)


@router.delete("/oauth/{installation_id}", status_code=204, dependencies=[RequireScope("write")])
async def delete_slack_oauth_installation(
    installation_id: str,
    store: StoreD,
    _role: OrgAdmin,
) -> None:
    """Disable a Slack OAuth installation without deleting historical analysis trails."""
    if not await store.disable_slack_oauth_installation(installation_id):
        raise HTTPException(status_code=404, detail="Slack installation not found")
