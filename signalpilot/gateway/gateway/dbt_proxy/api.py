"""FastAPI router for dbt-proxy run-token management.

Routes:
  POST   /api/dbt-proxy/run-tokens               Mint a run-token.
  DELETE /api/dbt-proxy/run-tokens/{run_id}      Revoke a run-token.
  GET    /api/dbt-proxy/run-tokens/{run_id}       Inspect a run-token.

All routes require the "dbt_proxy" scope (registered in models/api_keys.py).
org_id and user_id are read from the auth context dependency — never from the
request body.

The token value is returned only at creation time (POST). GET returns metadata
only; the token hex is never re-exposed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import OrgID, UserID
from ..security.scope_guard import RequireScope
from .config import DbtProxyConfig
from .errors import ProxyDisabled, RunTokenAlreadyExists
from .tokens import RunTokenClaims, RunTokenStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dbt-proxy/run-tokens", tags=["dbt-proxy"])


# ─── Request / Response models ────────────────────────────────────────────────


class MintRequest(BaseModel):
    run_id: uuid.UUID
    connector_name: str = Field(..., min_length=1, max_length=64)
    ttl_seconds: int = Field(..., ge=60, le=86400)


class MintResponse(BaseModel):
    token: str
    host_port: int
    expires_at: str  # ISO 8601


class TokenInfoResponse(BaseModel):
    run_id: uuid.UUID
    expires_at: str
    host_port: int
    sessions_open: int  # R3: always 0 (session tracking deferred)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _get_token_store(request: Request) -> RunTokenStore:
    store = getattr(request.app.state, "dbt_proxy_token_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="dbt_proxy token store not initialized")
    return store


def _get_config(request: Request) -> DbtProxyConfig:
    config = getattr(request.app.state, "dbt_proxy_config", None)
    if config is None:
        raise HTTPException(status_code=503, detail="dbt_proxy config not initialized")
    return config


def _check_proxy_enabled(config: DbtProxyConfig) -> None:
    if not config.sp_dbt_proxy_enabled:
        raise HTTPException(
            status_code=503,
            detail={"error_code": ProxyDisabled.error_code, "message": "dbt proxy is disabled"},
        )


def _check_secret_configured(config: DbtProxyConfig) -> None:
    if not config.sp_gateway_run_token_secret:
        raise HTTPException(
            status_code=503,
            detail={"error_code": "proxy_disabled", "message": "sp_gateway_run_token_secret is not configured"},
        )


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.post("", status_code=201, response_model=MintResponse, dependencies=[RequireScope("dbt_proxy")])
async def mint_run_token(
    body: MintRequest,
    request: Request,
    org_id: OrgID,
    user_id: UserID,
) -> MintResponse:
    """Mint a short-lived run-token for a dbt-proxy session.

    org_id and user_id come from the auth context (not the request body).
    Duplicate run_id → 409. Missing secret or disabled proxy → 503.
    """
    config = _get_config(request)
    _check_proxy_enabled(config)
    _check_secret_configured(config)

    token_store = _get_token_store(request)

    try:
        token_hex, claims = await token_store.mint(
            run_id=body.run_id,
            org_id=org_id,
            user_id=user_id,
            connector_name=body.connector_name,
            ttl_seconds=body.ttl_seconds,
        )
    except RunTokenAlreadyExists as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": RunTokenAlreadyExists.error_code, "message": str(exc)},
        )

    expires_at_str = datetime.fromtimestamp(claims.expires_at, tz=UTC).isoformat()
    logger.info("dbt_proxy mint run_id=%s org=%s connector=%s", body.run_id, org_id, body.connector_name)
    return MintResponse(
        token=token_hex,
        host_port=config.sp_dbt_proxy_port,
        expires_at=expires_at_str,
    )


@router.delete("/{run_id}", status_code=204, dependencies=[RequireScope("dbt_proxy")])
async def revoke_run_token(run_id: uuid.UUID, request: Request) -> None:
    """Revoke a run-token. No-op if the token does not exist."""
    token_store = _get_token_store(request)
    await token_store.revoke(run_id)
    logger.info("dbt_proxy revoke run_id=%s", run_id)


@router.get("/{run_id}", response_model=TokenInfoResponse, dependencies=[RequireScope("dbt_proxy")])
async def get_run_token(run_id: uuid.UUID, request: Request) -> TokenInfoResponse:
    """Inspect a run-token by run_id. Returns 404 if not found."""
    config = _get_config(request)
    token_store = _get_token_store(request)
    claims: RunTokenClaims | None = await token_store.get(run_id)
    if claims is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "run_token_not_found", "message": f"No token for run_id={run_id}"},
        )
    expires_at_str = datetime.fromtimestamp(claims.expires_at, tz=UTC).isoformat()
    return TokenInfoResponse(
        run_id=claims.run_id,
        expires_at=expires_at_str,
        host_port=config.sp_dbt_proxy_port,
        sessions_open=0,  # R3: session tracking deferred
    )


__all__ = ["router"]
