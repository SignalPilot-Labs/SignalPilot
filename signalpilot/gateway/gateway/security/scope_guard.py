"""Scope enforcement for API key and notebook-session authentication.

Provides require_scopes() and the RequireScope factory for FastAPI Depends usage.
Scope model is flat — no hierarchy, no inheritance.

Sanctioned bypass: routes under /notebook/* deliberately use resolve_proxy_session
instead of RequireScope. This is the ONLY approved bypass of this guard. Those routes
perform their own auth (Clerk/JWT + org-scope + cookie + ownership checks) inside
resolve_proxy_session. Any future route that bypasses RequireScope for a different
reason must be documented here and reviewed as a security exception.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request

from ..models import VALID_API_KEY_SCOPES  # noqa: F401 — imported for reference

# Scopes that notebook-session JWTs may ever be granted — admin is explicitly excluded.
# A pod callback may read and write data on behalf of its owning user, but it must
# never be able to perform org administration, billing changes, or user management.
# This allowlist is the gateway-side hard cap; the JWT's own scopes claim is
# intersected with it, so the token can only ask for less — never more.
_NOTEBOOK_SESSION_SCOPE_ALLOWLIST: frozenset[str] = frozenset({"read", "write"})


async def _resolve_user_id(request: Request) -> str:
    """Lazy wrapper around auth.resolve_user_id to avoid circular imports."""
    from ..auth import resolve_user_id

    return await resolve_user_id(request)


def require_scopes(request: Request, *required: str) -> None:
    """Check that the authenticated request has all required scopes.

    Four auth cases, checked in order:
    1. No auth attribute (or auth is None) — JWT/Clerk user. Grant all scopes.
    2. auth_method == "local_key" / "local_nokey" — local dev key. Grant all scopes.
    3. auth_method == "api_key" — stored API key. Check scopes explicitly.
    4. auth_method == "notebook_session" — pod callback JWT. Enforce a fixed
       allowlist (read + write only). The token's own scopes claim is intersected
       with the allowlist so the token can never escalate above it.

    WARNING: Case 1 grants all scopes when auth is None, which occurs for JWT
    and cookie-authenticated requests before resolve_user_id runs. This means
    every scope-protected endpoint MUST also include a `_: UserID` or
    `store: StoreD` parameter dependency to ensure JWT verification actually
    runs in cloud mode. Endpoints without those dependencies will pass scope
    checks with an unverified (or fake) Bearer token.

    Raises:
        HTTPException(403): if any required scope is missing.
    """
    auth = getattr(request.state, "auth", None)

    # Case 1: JWT/Clerk user — no auth dict set by middleware.
    if auth is None:
        return

    # Case 2: local mode — bypass all scope checks.
    if auth.get("auth_method") in ("local_key", "local_nokey"):
        return

    # Case 3: stored API key — enforce scopes explicitly.
    if auth.get("auth_method") == "api_key":
        key_scopes: list[str] = auth.get("scopes", [])
        missing = [s for s in required if s not in key_scopes]
        if missing:
            raise HTTPException(status_code=403, detail="Insufficient scope")
        return

    # Case 4: notebook-session JWT (pod callback).
    # Intersect the token's own scopes with the hard allowlist so the pod can never
    # ask for more than read/write regardless of what the JWT claims field contains.
    if auth.get("auth_method") == "notebook_session":
        token_scopes: list[str] = auth.get("scopes", [])
        effective_scopes = frozenset(token_scopes) & _NOTEBOOK_SESSION_SCOPE_ALLOWLIST
        missing_nb = [s for s in required if s not in effective_scopes]
        if missing_nb:
            raise HTTPException(status_code=403, detail="Insufficient scope")
        return

    # Unknown auth method — fail closed.
    raise HTTPException(status_code=403, detail="Unknown authentication method")


def RequireScope(*scopes: str) -> Any:
    """FastAPI dependency factory that enforces BOTH authentication AND scope.

    Depends on resolve_user_id so that JWT verification always runs before
    scope checking — preventing unauthenticated requests from passing through
    when an endpoint uses only RequireScope without an explicit UserID dependency.

    Usage:
        @router.post("/endpoint", dependencies=[RequireScope("write", "execute")])
        async def my_endpoint(...):
            ...

    Or as a parameter dependency:
        async def my_endpoint(_: None = RequireScope("admin")):
            ...
    """

    async def _check(request: Request, _user_id: str = Depends(_resolve_user_id)) -> None:
        require_scopes(request, *scopes)

    return Depends(_check)
