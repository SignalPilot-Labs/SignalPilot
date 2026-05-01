"""FastAPI auth dependency for Clerk JWT verification.

Local mode: returns None (no token lookup, no header read).
Cloud mode: validates Bearer JWT; raises on missing/invalid token.

Dependency direction: auth.dependency → auth.clerk, config, errors.
Does NOT import from routes, models, or db.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from workspaces_api.auth.clerk import JwksClient, verify_clerk_jwt
from workspaces_api.config import Settings, get_settings
from workspaces_api.errors import AuthMissingToken


def _get_jwks_client(request: Request) -> JwksClient:
    return request.app.state.jwks_client


async def current_user_id(
    request: Request,
    settings: Settings = Depends(get_settings),
    jwks_client: JwksClient = Depends(_get_jwks_client),
) -> str | None:
    """Return the authenticated user ID, or None in local mode.

    Local mode: always returns None; sets request.state.user_id = None.
    Cloud mode: reads Authorization header, verifies JWT, returns sub claim.

    Raises:
        AuthMissingToken: Header absent or not "Bearer <token>" (cloud mode only).
        AuthInvalidToken: JWT verification fails (cloud mode only).
        ClerkJWKSUnavailable: JWKS upstream unreachable (cloud mode only, 503).
    """
    if settings.sp_deployment_mode == "local":
        request.state.user_id = None
        return None

    # Cloud mode — extract and verify JWT
    auth_header = request.headers.get("authorization", "")
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise AuthMissingToken("Authorization header missing or malformed")

    token = parts[1]
    assert settings.clerk_issuer, "clerk_issuer must be set in cloud mode (lifespan fail-fast)"
    sub = await verify_clerk_jwt(
        token,
        jwks_client,
        issuer=settings.clerk_issuer,
        audience=settings.clerk_audience,
    )
    request.state.user_id = sub
    return sub


CurrentUserId = Annotated[str | None, Depends(current_user_id)]
