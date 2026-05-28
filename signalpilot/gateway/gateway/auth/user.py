"""User identity resolution for the gateway.

Resolves every request to a user_id and org_id:
- Cloud mode (CLERK_PUBLISHABLE_KEY set): Clerk JWT → real user ID and org_id
- Local mode: user_id = "local", org_id = "local" (constants)
- MCP requests: API key validation (handled by auth/mcp_api_key.py, sets scope state)
"""

from __future__ import annotations

import base64
import datetime
import logging
import os
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from ..auth.notebook_jwt import NOTEBOOK_SESSION_ISS, NotebookSessionJWTError, verify_session_jwt
from ..config import get_auth_settings
from ..db.engine import get_db
from ..runtime.mode import is_cloud_mode

logger = logging.getLogger(__name__)

if is_cloud_mode() and not os.environ.get("CLERK_PUBLISHABLE_KEY"):
    raise RuntimeError(
        "Cloud mode is enabled (SP_DEPLOYMENT_MODE=cloud) but CLERK_PUBLISHABLE_KEY is not set. "
        "JWT authentication cannot function without this key. "
        "Set CLERK_PUBLISHABLE_KEY or switch to local mode."
    )

_auth_cfg = get_auth_settings()
EXPECTED_AUDIENCE = _auth_cfg.clerk_jwt_audience
JWT_LEEWAY_SECONDS = _auth_cfg.sp_jwt_leeway

if is_cloud_mode() and not EXPECTED_AUDIENCE:
    logger.warning("CLERK_JWT_AUDIENCE not set — audience verification disabled. Set this for production security.")

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
            encoded = pk[len(prefix) :]
            padded = encoded + "=" * (-len(encoded) % 4)
            domain = base64.b64decode(padded).decode("utf-8").rstrip("$")
            jwks_url = f"https://{domain}/.well-known/jwks.json"
            _expected_issuer = f"https://{domain}"
            _jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True)
            logger.info("Clerk JWKS client initialized: %s", jwks_url)
            return _jwks_client

    raise ValueError(f"Cannot derive JWKS URL from publishable key: {pk[:12]}...")


# Eagerly initialize JWKS client at import time so a malformed
# CLERK_PUBLISHABLE_KEY crashes the process at startup, not at first request.
if is_cloud_mode():
    try:
        _get_jwks_client()
    except Exception as e:
        raise RuntimeError(
            f"Failed to initialize Clerk JWKS client at startup: {e}. Check CLERK_PUBLISHABLE_KEY format."
        ) from e


def _extract_bearer_token(connection: HTTPConnection) -> str | None:
    """Extract the raw bearer token from Authorization header (no filtering)."""
    auth = connection.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def _extract_jwt_token(connection: HTTPConnection) -> str | None:
    """Extract JWT from Authorization header or __session cookie.

    Returns None for sp_-prefixed tokens (handled separately as local API keys).
    """
    token = _extract_bearer_token(connection)
    if token is not None:
        if token.startswith("sp_"):
            return None
        return token
    # Clerk stores session token in __session cookie
    return connection.cookies.get("__session")


async def _resolve_via_notebook_jwt(connection: HTTPConnection, token: str) -> str:
    """Verify a notebook session JWT and set auth state. Returns user_id."""
    try:
        claims = verify_session_jwt(token)
    except NotebookSessionJWTError as e:
        logger.warning("Notebook session JWT verification failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid notebook session token")

    user_id = claims["sub"]
    org_id = claims["org_id"]
    session_id = claims["session_id"]
    # Read scopes from the verified JWT claims — never hard-code them here.
    # The scope_guard will intersect these against its own allowlist.
    token_scopes: list[str] = claims.get("scopes", [])

    connection.state.auth = {
        "auth_method": "notebook_session",
        "user_id": user_id,
        "org_id": org_id,
        "session_id": session_id,
        "scopes": token_scopes,
    }
    connection.state._jwt_claims = {
        "sub": user_id,
        "org_id": org_id,
        "session_id": session_id,
    }
    return user_id


async def _resolve_via_clerk(connection: HTTPConnection, token: str) -> str:
    """Verify a Clerk JWT and set _jwt_claims. Returns user_id."""
    client = _get_jwks_client()
    if client is None:
        raise HTTPException(status_code=500, detail="JWKS client not configured")

    try:
        signing_key = client.get_signing_key_from_jwt(token)
        decode_kwargs: dict = {
            "algorithms": ["RS256"],
            "issuer": _expected_issuer,
            "leeway": datetime.timedelta(seconds=JWT_LEEWAY_SECONDS),
        }
        options: dict = {"require": ["exp", "iat", "sub"]}
        if EXPECTED_AUDIENCE:
            decode_kwargs["audience"] = EXPECTED_AUDIENCE
        else:
            options["verify_aud"] = False
        decode_kwargs["options"] = options
        claims = jwt.decode(token, signing_key.key, **decode_kwargs)
        user_id = claims.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing sub claim")
        connection.state._jwt_claims = claims
        return user_id
    except jwt.PyJWKClientConnectionError as e:
        logger.error("JWKS endpoint unreachable: %s", e)
        raise HTTPException(status_code=503, detail="Authentication service temporarily unavailable")
    except jwt.PyJWKClientError as e:
        logger.error("JWKS client error: %s", e)
        raise HTTPException(status_code=503, detail="Authentication service error")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid authentication token")


async def resolve_user_id(connection: HTTPConnection) -> str:
    """Resolve the current user_id from the request.

    Accepts HTTPConnection so this works for both HTTP (Request) and WebSocket
    endpoints. WebSocket is a subclass of HTTPConnection but NOT of Request —
    FastAPI cannot inject a Request into a WS dependency.

    Dispatch order:
    1. If auth state already set (MCP/API-key middleware) → short-circuit.
    2. If Bearer token starts with sp_ → local API key path (NO JWT decode).
    3. Else decode token payload unverified, read iss:
       - iss == "signalpilot-notebook-session" → notebook_jwt.verify_session_jwt only.
       - else → Clerk verify only.
    4. Local mode without a Bearer token → return LOCAL_USER_ID.
    5. Any failure → 401.

    Side effect: caches decoded JWT claims on connection.state._jwt_claims for
    resolve_org_id. Both functions must share this state to avoid decoding the
    JWT twice.
    """
    # 1. Check if auth middleware already resolved user_id (MCP / API-key)
    auth_state = getattr(connection.state, "auth", None)
    if auth_state and isinstance(auth_state, dict) and "user_id" in auth_state:
        connection.state._jwt_claims = {
            "sub": auth_state["user_id"],
            "org_id": auth_state.get("org_id"),
        }
        return auth_state["user_id"]

    # 2. Check for sp_-prefixed local API key (short-circuit, no JWT decode)
    bearer = _extract_bearer_token(connection)
    if bearer is not None and bearer.startswith("sp_"):
        if not is_cloud_mode():
            # Local mode: API key auth handled by APIKeyAuthMiddleware which sets auth state.
            # If we reach here without auth state set, the key wasn't recognized.
            raise HTTPException(status_code=401, detail="Invalid local API key")
        # Cloud mode: sp_ keys are not supported
        raise HTTPException(status_code=401, detail="Authentication required")

    if not is_cloud_mode():
        # Local mode without a sp_ bearer: synthetic local identity
        connection.state._jwt_claims = {"sub": LOCAL_USER_ID, "org_id": LOCAL_ORG_ID}
        return LOCAL_USER_ID

    # Cloud mode: must have a JWT
    token = _extract_jwt_token(connection)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    # 3. Decode unverified to inspect iss — one token → one verifier.
    # Pin algorithm first: reject alg=none and any unexpected algorithm before
    # reading payload claims, to guard against PyJWT regressions.
    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError:
        raise HTTPException(status_code=401, detail="Malformed authentication token")

    alg = header.get("alg", "")
    if alg not in {"HS256", "RS256"}:
        raise HTTPException(status_code=401, detail="Malformed authentication token")

    try:
        unverified = jwt.decode(
            token,
            options={"verify_signature": False},
            algorithms=["HS256", "RS256"],
        )
    except jwt.DecodeError:
        raise HTTPException(status_code=401, detail="Malformed authentication token")

    iss = unverified.get("iss", "")
    if iss == NOTEBOOK_SESSION_ISS:
        return await _resolve_via_notebook_jwt(connection, token)

    # Default: Clerk path
    return await _resolve_via_clerk(connection, token)


async def resolve_org_id(connection: HTTPConnection, _user_id: UserID) -> str:
    """Resolve the current org_id from the request.

    Accepts HTTPConnection so this works for both HTTP (Request) and WebSocket
    endpoints. See resolve_user_id docstring for rationale.

    Depends on UserID (resolve_user_id) to guarantee JWT is decoded exactly once.
    Reads cached claims from connection.state._jwt_claims set by resolve_user_id.

    - Local mode: returns LOCAL_ORG_ID ("local").
    - Cloud mode: extracts org_id claim from JWT. Raises 403 if missing.
    - MCP requests: uses org_id from auth_state. Raises 403 in cloud mode if absent.

    Also sets current_org_id_var so governance singletons (health monitor, budget,
    caches) can read the org scope without requiring Store instantiation.
    """
    from ..governance.context import current_org_id_var

    claims = getattr(connection.state, "_jwt_claims", None)
    if claims is None:
        # Should never happen since _user_id dependency ran first
        raise HTTPException(status_code=500, detail="JWT claims not available")

    # Clerk dev uses "org_id" (string), Clerk prod uses short claim "o" (dict with "id" key)
    org_id = claims.get("org_id")
    if not org_id:
        o_claim = claims.get("o")
        if isinstance(o_claim, dict):
            org_id = o_claim.get("id")
        elif isinstance(o_claim, str):
            org_id = o_claim
    logger.info("resolve_org_id: org_id=%s claims_keys=%s", org_id, list(claims.keys()))

    if not is_cloud_mode():
        # Local mode: always returns LOCAL_ORG_ID regardless of claims
        current_org_id_var.set(LOCAL_ORG_ID)
        return LOCAL_ORG_ID

    # MCP / API-key auth state: require org_id in cloud mode
    auth_state = getattr(connection.state, "auth", None)
    if auth_state and isinstance(auth_state, dict):
        if org_id:
            current_org_id_var.set(org_id)
            return org_id
        raise HTTPException(status_code=403, detail="Organization context required")

    # Cloud mode: org_id claim is required
    if not org_id:
        raise HTTPException(status_code=403, detail="Organization context required")
    current_org_id_var.set(org_id)
    return org_id


async def resolve_org_role(request: Request, _user_id: UserID) -> str:
    """Extract org role from JWT claims. Returns 'admin' or 'basic_member'.

    - MCP / API key auth: treat as admin (key holder has full access).
    - Local mode: always admin.
    - Cloud JWT: reads 'org_role' claim or Clerk prod short claim 'o.rol'.
    """
    claims = getattr(request.state, "_jwt_claims", {})

    # Clerk dev uses "org_role" directly; Clerk prod uses short claim "o" with "rol"
    role = claims.get("org_role")
    if not role:
        o_claim = claims.get("o")
        if isinstance(o_claim, dict):
            role = o_claim.get("rol")

    # MCP / API key auth — treat as admin (key holder has full access)
    auth = getattr(request.state, "auth", None)
    if auth and auth.get("auth_method") in ("api_key", "local_key", "local_nokey"):
        return "admin"

    # Local mode — always admin
    if not is_cloud_mode():
        return "admin"

    return role or "basic_member"


OrgRole = Annotated[str, Depends(resolve_org_role)]


async def require_org_admin(role: OrgRole) -> str:
    """Require org:admin role. Raises 403 for non-admin members."""
    if role not in ("admin", "org:admin"):
        raise HTTPException(status_code=403, detail="Organization admin role required")
    return role


OrgAdmin = Annotated[str, Depends(require_org_admin)]


# FastAPI dependency aliases
UserID = Annotated[str, Depends(resolve_user_id)]
OrgID = Annotated[str, Depends(resolve_org_id)]
DBSession = Annotated[AsyncSession, Depends(get_db)]
