"""OAuth 2.1 resource-server support for the gateway MCP endpoint.

The gateway never issues tokens. Clerk is the authorization server; the
gateway only (1) advertises RFC 9728 protected-resource metadata that points
at Clerk, (2) answers unauthenticated ``/mcp`` requests with a
``WWW-Authenticate`` challenge so MCP clients (Claude.ai, Claude Code,
Cursor, MCP Inspector) can discover the authorization server, and
(3) verifies the Clerk-issued access token on each request.

Token verification order:

* JWT access tokens (Clerk default): RS256 against the instance JWKS, issuer
  pinned to the Clerk Frontend API, ``exp``/``iat``/``sub`` required, and the
  ``aud`` claim checked against the canonical MCP resource URL (RFC 8707).
* Opaque access tokens: introspected through the Clerk Backend API with the
  instance secret key.

Organization context comes from the ``org_id`` claim (granted by the
``user:org:read`` scope, chosen on Clerk's consent screen). The caller's role
inside that organization is resolved through the Clerk Backend API and mapped
to gateway scopes, so an OAuth caller gets exactly what an API key minted by
the same person would get.

The inbound Clerk token is never forwarded anywhere (MCP token-passthrough
prohibition); tools keep minting their own internal credentials.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt

from ..config import get_mcp_settings
from ..config.gateway import get_gateway_settings
from ..models.api_keys import VALID_API_KEY_SCOPES
from ..runtime.mode import is_cloud_mode

logger = logging.getLogger(__name__)

CLERK_API_BASE = "https://api.clerk.com/v1"

# Scopes the gateway asks Clerk for. ``user:org:read`` is what makes Clerk show
# the organization selector on consent and stamp ``org_id`` into the token.
OAUTH_SCOPES: tuple[str, ...] = ("openid", "profile", "email", "user:org:read")

# Gateway scopes granted to an OAuth caller by organization role.
MEMBER_SCOPES: tuple[str, ...] = tuple(sorted(VALID_API_KEY_SCOPES - {"admin"}))
ADMIN_SCOPES: tuple[str, ...] = tuple(sorted(VALID_API_KEY_SCOPES))

_MEMBERSHIP_CACHE_TTL_SECONDS = 300.0
_INTROSPECTION_CACHE_TTL_SECONDS = 60.0


class OAuthTokenError(Exception):
    """A bearer token that must be answered with an RFC 6750 challenge."""

    def __init__(
        self,
        error: str,
        description: str,
        *,
        status: int = 401,
        scope: str | None = None,
    ) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status = status
        self.scope = scope


@dataclass
class OAuthPrincipal:
    """The identity a verified Clerk OAuth access token represents."""

    user_id: str
    org_id: str
    org_role: str
    scopes: list[str]
    client_id: str | None
    expires_at: int | None
    claims: dict[str, Any] = field(default_factory=dict)


# ─── Configuration ───────────────────────────────────────────────────────────


def clerk_frontend_api() -> str | None:
    """Return the Clerk Frontend API origin derived from the publishable key."""
    pk = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
    for prefix in ("pk_test_", "pk_live_"):
        if pk.startswith(prefix):
            encoded = pk[len(prefix):]
            padded = encoded + "=" * (-len(encoded) % 4)
            try:
                domain = base64.b64decode(padded).decode("utf-8").rstrip("$")
            except (ValueError, UnicodeDecodeError):
                return None
            return f"https://{domain}" if domain else None
    return None


def oauth_enabled() -> bool:
    """OAuth is on in cloud mode whenever Clerk is configured and not disabled."""
    if not is_cloud_mode():
        return False
    if get_mcp_settings().sp_mcp_oauth_disabled:
        return False
    return clerk_frontend_api() is not None


def resource_url() -> str:
    """Canonical MCP resource identifier (RFC 8707): the public ``/mcp`` URL."""
    override = get_mcp_settings().sp_mcp_oauth_resource_url.strip()
    if override:
        return override.rstrip("/")
    return get_gateway_settings().sp_public_gateway_url.rstrip("/") + "/mcp"


def _resource_origin_and_path() -> tuple[str, str]:
    url = resource_url()
    scheme, _, rest = url.partition("://")
    host, slash, path = rest.partition("/")
    return f"{scheme}://{host}", (slash + path if path else "")


def resource_metadata_url() -> str:
    """RFC 9728 §3.1 path-suffixed metadata URL for the MCP resource."""
    origin, path = _resource_origin_and_path()
    return f"{origin}/.well-known/oauth-protected-resource{path}"


def protected_resource_metadata() -> dict[str, Any]:
    """The RFC 9728 document served under ``/.well-known/oauth-protected-resource``."""
    issuer = clerk_frontend_api() or ""
    return {
        "resource": resource_url(),
        "authorization_servers": [issuer] if issuer else [],
        "scopes_supported": list(OAUTH_SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_name": "SignalPilot MCP",
    }


def www_authenticate(
    error: str = "invalid_token",
    description: str = "Authentication required",
    scope: str | None = None,
) -> str:
    """Build the RFC 6750 / RFC 9728 ``WWW-Authenticate`` challenge value."""
    parts = [f'error="{error}"', f'error_description="{_quote(description)}"']
    parts.append(f'resource_metadata="{resource_metadata_url()}"')
    parts.append(f'scope="{scope or " ".join(OAUTH_SCOPES)}"')
    return "Bearer " + ", ".join(parts)


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', "'")


# ─── Token classification ───────────────────────────────────────────────────


def is_oauth_candidate(token: str) -> bool:
    """Decide whether a non-``sp_`` bearer token should take the OAuth path.

    A JWT whose unverified ``iss`` is the Clerk Frontend API is a Clerk OAuth
    (or session) token. Anything that is not a JWT at all is treated as an
    opaque Clerk access token. Gateway-minted notebook session JWTs carry
    their own issuer and are left to the notebook verifier.
    """
    issuer = clerk_frontend_api()
    if not issuer:
        return False
    if token.count(".") != 2:
        return True
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.InvalidTokenError:
        return False
    return claims.get("iss") == issuer


# ─── Verification ────────────────────────────────────────────────────────────


def _audience_matches(aud: Any) -> bool:
    if aud is None:
        return False
    values = aud if isinstance(aud, list) else [aud]
    target = resource_url()
    return any(isinstance(v, str) and v.rstrip("/") == target for v in values)


def _org_id_from_claims(claims: dict[str, Any]) -> str | None:
    org_id = claims.get("org_id")
    if org_id:
        return str(org_id)
    o_claim = claims.get("o")
    if isinstance(o_claim, dict):
        return o_claim.get("id") or None
    if isinstance(o_claim, str):
        return o_claim or None
    return None


def _decode_jwt(token: str) -> dict[str, Any]:
    from .user import _get_jwks_client

    issuer = clerk_frontend_api()
    client = _get_jwks_client()
    if client is None or issuer is None:
        raise OAuthTokenError("invalid_token", "OAuth is not configured", status=503)
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            leeway=30,
            options={"require": ["exp", "iat", "sub"], "verify_aud": False},
        )
    except jwt.PyJWKClientError as exc:
        logger.error("MCP OAuth: JWKS unavailable: %s", exc)
        raise OAuthTokenError("invalid_token", "Authentication service unavailable", status=503)
    except jwt.ExpiredSignatureError:
        raise OAuthTokenError("invalid_token", "The access token has expired")
    except jwt.InvalidTokenError as exc:
        logger.warning("MCP OAuth: JWT rejected: %s", exc)
        raise OAuthTokenError("invalid_token", "The access token is invalid")


_introspection_cache: dict[str, tuple[dict[str, Any], float]] = {}


async def _introspect_opaque(token: str) -> dict[str, Any]:
    """Verify an opaque Clerk access token through the Backend API."""
    cached = _introspection_cache.get(token)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    secret = os.environ.get("CLERK_SECRET_KEY", "")
    if not secret:
        raise OAuthTokenError("invalid_token", "Opaque tokens are not supported", status=503)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{CLERK_API_BASE}/oauth_applications/access_tokens/verify",
                headers={"Authorization": f"Bearer {secret}"},
                json={"access_token": token},
            )
    except httpx.HTTPError as exc:
        logger.error("MCP OAuth: introspection failed: %s", exc)
        raise OAuthTokenError("invalid_token", "Authentication service unavailable", status=503)
    if resp.status_code != 200:
        raise OAuthTokenError("invalid_token", "The access token is invalid")
    data = resp.json()
    if data.get("active") is False or data.get("revoked") or not data.get("subject") and not data.get("sub"):
        raise OAuthTokenError("invalid_token", "The access token is invalid")
    claims = {
        "sub": data.get("subject") or data.get("sub"),
        "scope": " ".join(data.get("scopes") or []) if isinstance(data.get("scopes"), list) else data.get("scope", ""),
        "exp": data.get("expires_at") or data.get("exp"),
        "org_id": data.get("org_id") or data.get("organization_id"),
        "azp": data.get("client_id"),
        "iss": clerk_frontend_api(),
    }
    _introspection_cache[token] = (claims, time.monotonic() + _INTROSPECTION_CACHE_TTL_SECONDS)
    if len(_introspection_cache) > 512:
        _introspection_cache.pop(next(iter(_introspection_cache)))
    return claims


_membership_cache: dict[tuple[str, str], tuple[str, float]] = {}


async def resolve_org_role(user_id: str, org_id: str) -> str:
    """Look up the caller's role in ``org_id`` via the Clerk Backend API."""
    key = (user_id, org_id)
    cached = _membership_cache.get(key)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    secret = os.environ.get("CLERK_SECRET_KEY", "")
    if not secret:
        raise OAuthTokenError("invalid_token", "Organization lookup is not configured", status=503)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{CLERK_API_BASE}/organizations/{org_id}/memberships",
                headers={"Authorization": f"Bearer {secret}"},
                params={"user_id": user_id, "limit": 1},
            )
    except httpx.HTTPError as exc:
        logger.error("MCP OAuth: membership lookup failed: %s", exc)
        raise OAuthTokenError("invalid_token", "Authentication service unavailable", status=503)
    if resp.status_code != 200:
        logger.warning("MCP OAuth: membership lookup HTTP %s for org %s", resp.status_code, org_id)
        raise OAuthTokenError("insufficient_scope", "You are not a member of this organization", status=403)
    rows = resp.json().get("data") or []
    row = next((r for r in rows if (r.get("public_user_data") or {}).get("user_id") == user_id), None)
    if row is None:
        raise OAuthTokenError("insufficient_scope", "You are not a member of this organization", status=403)
    role = str(row.get("role") or "org:member")
    _membership_cache[key] = (role, time.monotonic() + _MEMBERSHIP_CACHE_TTL_SECONDS)
    if len(_membership_cache) > 4096:
        _membership_cache.pop(next(iter(_membership_cache)))
    return role


def scopes_for_role(role: str) -> list[str]:
    return list(ADMIN_SCOPES if role in ("admin", "org:admin") else MEMBER_SCOPES)


async def verify_oauth_token(token: str) -> OAuthPrincipal:
    """Verify a Clerk OAuth access token and resolve its organization principal."""
    claims = _decode_jwt(token) if token.count(".") == 2 else await _introspect_opaque(token)

    user_id = claims.get("sub")
    if not user_id:
        raise OAuthTokenError("invalid_token", "The access token has no subject")

    aud = claims.get("aud")
    if aud is not None and not _audience_matches(aud):
        logger.warning("MCP OAuth: audience %r does not match %s", aud, resource_url())
        raise OAuthTokenError("invalid_token", "The access token was issued for another resource")
    if aud is None and get_mcp_settings().sp_mcp_oauth_require_audience:
        raise OAuthTokenError("invalid_token", "The access token has no audience")

    org_id = _org_id_from_claims(claims)
    if not org_id:
        raise OAuthTokenError(
            "insufficient_scope",
            "Select an organization when you authorize SignalPilot",
            status=403,
            scope="user:org:read",
        )

    role = await resolve_org_role(str(user_id), org_id)
    exp = claims.get("exp")
    return OAuthPrincipal(
        user_id=str(user_id),
        org_id=org_id,
        org_role=role,
        scopes=scopes_for_role(role),
        client_id=claims.get("azp") or claims.get("client_id"),
        expires_at=int(exp) if isinstance(exp, (int, float)) else None,
        claims=dict(claims),
    )


# ─── ASGI helpers used by MCPAuthMiddleware ──────────────────────────────────


def apply_principal(scope: dict[str, Any], principal: OAuthPrincipal, raw_token: str) -> None:
    """Populate ``scope["state"]["auth"]`` and the MCP context variables."""
    from ..mcp import context as ctx

    if "state" not in scope:
        scope["state"] = {}
    scope["state"]["auth"] = {
        "auth_method": "oauth",
        "user_id": principal.user_id,
        "org_id": principal.org_id,
        "org_role": principal.org_role,
        "client_id": principal.client_id,
        "scopes": list(principal.scopes),
    }
    ctx.mcp_user_id_var.set(principal.user_id)
    ctx.mcp_org_id_var.set(principal.org_id)
    ctx.mcp_raw_key_var.set(raw_token)
    ctx.mcp_scopes_var.set(list(principal.scopes))
    for var in (
        ctx.mcp_allowed_connection_var,
        ctx.mcp_capabilities_var,
        ctx.mcp_execution_identity_var,
        ctx.mcp_project_id_var,
        ctx.mcp_branch_var,
        ctx.mcp_eval_doc_ids_var,
        ctx.mcp_eval_connection_var,
        ctx.mcp_eval_run_var,
        ctx.mcp_eval_task_var,
    ):
        var.set(None)


async def send_oauth_error(send: Callable, exc: OAuthTokenError) -> None:
    """Send an RFC 6750 error response with the discovery challenge attached."""
    body = json.dumps({"error": exc.error, "error_description": exc.description, "detail": exc.description}).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    if exc.status in (401, 403):
        headers.append((b"www-authenticate", www_authenticate(exc.error, exc.description, exc.scope).encode()))
    await send({"type": "http.response.start", "status": exc.status, "headers": headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})
