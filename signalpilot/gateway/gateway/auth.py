"""User identity resolution for the gateway.

Resolves every request to a user_id and org_id:
- Cloud mode (CLERK_PUBLISHABLE_KEY set): Clerk JWT → real user ID and org_id
- Local mode: user_id = "local", org_id = "local" (constants)
- MCP requests: API key validation (handled by mcp_auth.py, sets scope state)
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .db.engine import get_db
from .deployment import is_cloud_mode

logger = logging.getLogger(__name__)

if is_cloud_mode() and not os.environ.get("CLERK_PUBLISHABLE_KEY"):
    logger.error(
        "Cloud mode is enabled (SP_DEPLOYMENT_MODE=cloud) but CLERK_PUBLISHABLE_KEY is not set. "
        "JWT authentication will fail."
    )

LOCAL_USER_ID = "local"
LOCAL_ORG_ID = "local"

# Cached JWKS client
_jwks_client = None
_expected_issuer: str | None = None


def _get_jwks_client():
    global _jwks_client, _expected_issuer
    if _jwks_client is not None:
        return _jwks_client

    pk = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
    if not pk:
        return None

    # Derive JWKS URL from publishable key
    for prefix in ("pk_test_", "pk_live_"):
        if pk.startswith(prefix):
            encoded = pk[len(prefix):]
            padded = encoded + "=" * (-len(encoded) % 4)
            domain = base64.b64decode(padded).decode("utf-8").rstrip("$")
            jwks_url = f"https://{domain}/.well-known/jwks.json"
            _expected_issuer = f"https://{domain}"
            _jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True)
            logger.info("Clerk JWKS client initialized: %s", jwks_url)
            return _jwks_client

    raise ValueError(f"Cannot derive JWKS URL from publishable key: {pk[:12]}...")


def _extract_jwt_token(request: Request) -> str | None:
    """Extract JWT from Authorization header or __session cookie."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer ") and not auth[7:].startswith("sp_"):
        return auth[7:]
    # Clerk stores session token in __session cookie
    return request.cookies.get("__session")


async def resolve_user_id(request: Request) -> str:
    """Resolve the current user_id from the request.

    - MCP requests: user_id is set by MCPAuthMiddleware in scope state.
    - Cloud browser requests: verify Clerk JWT.
    - Local mode: return "local".

    Side effect: caches decoded JWT claims on request.state._jwt_claims for
    resolve_org_id. Both functions must share this state to avoid decoding the
    JWT twice. resolve_org_id depends on UserID (which triggers this function)
    and then reads request.state._jwt_claims.
    """
    # Check if MCP auth already resolved user_id
    auth_state = getattr(request.state, "auth", None)
    if auth_state and isinstance(auth_state, dict) and "user_id" in auth_state:
        # Cache minimal claims for resolve_org_id
        request.state._jwt_claims = {
            "sub": auth_state["user_id"],
            "org_id": auth_state.get("org_id"),
        }
        return auth_state["user_id"]

    if not is_cloud_mode():
        # Local mode: set synthetic claims so resolve_org_id can read them
        request.state._jwt_claims = {"sub": LOCAL_USER_ID, "org_id": LOCAL_ORG_ID}
        return LOCAL_USER_ID

    # Cloud mode: verify Clerk JWT
    token = _extract_jwt_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    client = _get_jwks_client()
    if client is None:
        raise HTTPException(status_code=500, detail="JWKS client not configured")

    try:
        signing_key = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=_expected_issuer,
            options={"verify_aud": False},
        )
        user_id = claims.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing sub claim")
        # Cache full claims for resolve_org_id
        request.state._jwt_claims = claims
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid authentication token")


async def resolve_org_id(request: Request, _user_id: UserID) -> str:
    """Resolve the current org_id from the request.

    Depends on UserID (resolve_user_id) to guarantee JWT is decoded exactly once.
    Reads cached claims from request.state._jwt_claims set by resolve_user_id.

    - Local mode: returns LOCAL_ORG_ID ("local").
    - Cloud mode: extracts org_id claim from JWT. Raises 403 if missing.
    - MCP requests: uses org_id from auth_state. Raises 403 in cloud mode if absent.

    Also sets current_org_id_var so governance singletons (health monitor, budget,
    caches) can read the org scope without requiring Store instantiation.
    """
    from .governance.context import current_org_id_var

    claims = getattr(request.state, "_jwt_claims", None)
    if claims is None:
        # Should never happen since _user_id dependency ran first
        raise HTTPException(status_code=500, detail="JWT claims not available")

    # Clerk dev uses "org_id", Clerk prod uses short claim "o"
    org_id = claims.get("org_id") or claims.get("o")
    logger.info("resolve_org_id: org_id=%s claims_keys=%s", org_id, list(claims.keys()))

    if not is_cloud_mode():
        # Local mode: always returns LOCAL_ORG_ID regardless of claims
        current_org_id_var.set(LOCAL_ORG_ID)
        return LOCAL_ORG_ID

    # MCP / API-key auth state: require org_id in cloud mode
    auth_state = getattr(request.state, "auth", None)
    if auth_state and isinstance(auth_state, dict):
        if org_id:
            current_org_id_var.set(org_id)
            return org_id
        raise HTTPException(
            status_code=403, detail="Organization context required"
        )

    # Cloud mode: org_id claim is required
    if not org_id:
        raise HTTPException(status_code=403, detail="Organization context required")
    current_org_id_var.set(org_id)
    return org_id


# FastAPI dependency aliases
UserID = Annotated[str, Depends(resolve_user_id)]
OrgID = Annotated[str, Depends(resolve_org_id)]
DBSession = Annotated[AsyncSession, Depends(get_db)]
