"""User identity resolution for the gateway.

Resolves every request to a user_id:
- Cloud mode (CLERK_PUBLISHABLE_KEY set): Clerk JWT → real user ID
- Local mode: user_id = "local" (constant)
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

logger = logging.getLogger(__name__)

LOCAL_USER_ID = "local"

# Cached JWKS client
_jwks_client = None
_expected_issuer: str | None = None


def _is_cloud_mode() -> bool:
    return bool(os.environ.get("CLERK_PUBLISHABLE_KEY"))


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
    """
    # Check if MCP auth already resolved user_id
    auth_state = getattr(request.state, "auth", None)
    if auth_state and isinstance(auth_state, dict) and "user_id" in auth_state:
        return auth_state["user_id"]

    if not _is_cloud_mode():
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
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


# FastAPI dependency aliases
UserID = Annotated[str, Depends(resolve_user_id)]
DBSession = Annotated[AsyncSession, Depends(get_db)]
