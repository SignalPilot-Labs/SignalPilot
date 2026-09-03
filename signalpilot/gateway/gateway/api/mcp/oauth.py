"""Sign-in (OAuth) routes: start, callback, sign-out, and the public CIMD document (R6)."""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.auth import OrgRole
from gateway.db.engine import get_db
from gateway.mcp_connectors import oauth as oauth_mod
from gateway.mcp_connectors.policy import proxy_base_url
from gateway.mcp_connectors.upstream import pool as upstream_pool
from gateway.security.scope_guard import RequireScope
from gateway.store.mcp import connectors as connector_store
from gateway.store.mcp import members as member_store
from gateway.store.mcp import oauth_states as state_store
from gateway.store.mcp import utcnow

from ..deps import StoreD
from .common import caller, is_admin, load_connector, member_state_to_dict, refresh_inventory, require_enabled

logger = logging.getLogger(__name__)
router = APIRouter()

_DEFAULT_RETURN_PATH = "/settings/connectors"


def gateway_public_url() -> str:
    return os.getenv("SP_MCP_OAUTH_PUBLIC_URL") or proxy_base_url()


def _web_base() -> str | None:
    web = os.getenv("SP_WEB_URL") or os.getenv("SIGNALPILOT_WEB_URL")
    return web.rstrip("/") if web else None


def safe_return_url(redirect_after: str | None, *, connector_id: str, signin: str) -> str:
    """Only web-app paths or the configured web origin may be redirect targets.

    The gateway and the web app are different origins, so a relative path is
    resolved against SP_WEB_URL when it is configured.
    """
    target = (redirect_after or "").strip()
    web = _web_base()
    fallback = f"{web}{_DEFAULT_RETURN_PATH}" if web else _DEFAULT_RETURN_PATH
    if target.startswith("/") and not target.startswith("//"):
        target = f"{web}{target}" if web else target
    elif not (web and target.startswith(web + "/")):
        target = fallback
    parts = urlsplit(target)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in {"connector", "signin"}]
    query.extend([("connector", connector_id), ("signin", signin)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


@router.get("/oauth/client-metadata.json")
async def client_metadata() -> JSONResponse:
    """Public Client ID Metadata Document (no auth)."""
    return JSONResponse(oauth_mod.cimd_document(gateway_public_url()))


@router.get("/connectors/{connector_id}/oauth/start", dependencies=[RequireScope("read")])
async def oauth_start(
    connector_id: str,
    store: StoreD,
    role: OrgRole,
    redirect_after: str | None = Query(default=None, max_length=2048),
) -> RedirectResponse:
    require_enabled()
    org_id, user_id = caller(store)
    connector = await load_connector(
        store.session, org_id=org_id, user_id=user_id, connector_id=connector_id, admin=is_admin(role)
    )
    if connector.auth != "oauth" or not connector.url:
        raise HTTPException(status_code=400, detail="This connector does not use sign-in")
    oauth = dict(connector.oauth_json or {})
    if not oauth.get("authorization_endpoint"):
        discovery = await oauth_mod.discover(connector.url)
        if discovery is None:
            raise HTTPException(status_code=400, detail="This provider does not offer sign-in")
        oauth = oauth_mod.oauth_config(discovery, server_url=connector.url, client_id=oauth.get("client_id"))
    gateway_url = gateway_public_url()
    try:
        oauth, new_secret = await oauth_mod.register_client(oauth, gateway_url=gateway_url)
    except oauth_mod.NeedsClientRegistration as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if new_secret:
        from gateway.store.mcp._common import encrypt_json

        connector.oauth_client_secret_enc = encrypt_json({"client_secret": new_secret})
    if oauth != connector.oauth_json:
        connector.oauth_json = oauth
        connector.updated_at = utcnow()
        await store.session.commit()
    verifier, challenge = oauth_mod.make_pkce()
    state = await state_store.create_state(
        store.session,
        org_id=org_id,
        user_id=user_id,
        connector_id=connector.id,
        code_verifier=verifier,
        redirect_after=redirect_after,
    )
    try:
        url = oauth_mod.build_authorize_url(oauth, state=state, code_challenge=challenge, gateway_url=gateway_url)
    except oauth_mod.OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url, status_code=302)


@router.get("/oauth/callback", name="mcp_oauth_callback")
async def oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Provider redirect. Tenant context comes only from the stored state row."""
    if not state:
        raise HTTPException(status_code=400, detail="This sign-in link has expired. Close this window and try again.")
    row = await state_store.consume_state(db, state)
    if row is None:
        raise HTTPException(status_code=400, detail="This sign-in link has expired. Close this window and try again.")
    connector = await connector_store.get_connector(db, org_id=row.org_id, connector_id=row.connector_id)
    if connector is None:
        return RedirectResponse(safe_return_url(row.redirect_after, connector_id=row.connector_id, signin="error"))
    if error or not code:
        logger.info("Connector %s sign-in refused for %s: %s", connector.id, row.user_id, error or "no code")
        return RedirectResponse(safe_return_url(row.redirect_after, connector_id=connector.id, signin="error"))
    try:
        tokens = await oauth_mod.exchange_code(
            dict(connector.oauth_json or {}),
            connector_store.oauth_client_secret(connector),
            code=code,
            code_verifier=row.code_verifier,
            gateway_url=gateway_public_url(),
        )
    except oauth_mod.OAuthError as exc:
        logger.info("Connector %s token exchange failed: %s", connector.id, exc)
        return RedirectResponse(safe_return_url(row.redirect_after, connector_id=connector.id, signin="error"))
    member = await member_store.ensure_member_state(db, org_id=row.org_id, connector_id=connector.id, user_id=row.user_id)
    member_store.set_oauth_tokens(member, tokens, account_label=oauth_mod.account_label_from_tokens(tokens))
    await db.commit()
    await upstream_pool.evict(f"{connector.id}:{row.user_id}")
    try:
        await refresh_inventory(db, connector, member=member)
    except Exception:
        logger.exception("Connector %s tools refresh after sign-in failed", connector.id)
    return RedirectResponse(safe_return_url(row.redirect_after, connector_id=connector.id, signin="ok"))


@router.post("/connectors/{connector_id}/oauth/sign-out", dependencies=[RequireScope("write")])
async def oauth_sign_out(
    connector_id: str,
    store: StoreD,
    role: OrgRole,
    everyone: int = Query(default=0),
) -> dict[str, Any]:
    require_enabled()
    org_id, user_id = caller(store)
    admin = is_admin(role)
    connector = await load_connector(store.session, org_id=org_id, user_id=user_id, connector_id=connector_id, admin=admin)
    if everyone:
        if connector.scope == "org" and not admin:
            raise HTTPException(status_code=403, detail="Organization admin role required")
        await member_store.sign_out(store.session, connector_id=connector.id, user_id=None)
        await upstream_pool.evict_prefix(f"{connector.id}:")
    else:
        await member_store.sign_out(store.session, connector_id=connector.id, user_id=user_id)
        await upstream_pool.evict(f"{connector.id}:{user_id}")
    if connector.auth == "oauth" and connector.scope == "personal":
        connector.status = "needs_sign_in"
        connector.status_detail = None
        connector.updated_at = utcnow()
        await store.session.commit()
    member = await member_store.get_member_state(store.session, connector_id=connector.id, user_id=user_id)
    return member_state_to_dict(member)
