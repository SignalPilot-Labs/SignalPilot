"""Scope enforcement for API key authentication.

Provides require_scopes() and the RequireScope factory for FastAPI Depends usage.
Scope model is flat — no hierarchy, no inheritance.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request

from .models import VALID_API_KEY_SCOPES  # noqa: F401 — imported for reference


def require_scopes(request: Request, *required: str) -> None:
    """Check that the authenticated request has all required scopes.

    Three auth cases, checked in order:
    1. No auth attribute (or auth is None) — JWT/Clerk user. Grant all scopes.
    2. auth_method == "local_key" — local dev key. Grant all scopes.
    3. auth_method == "api_key" — stored API key. Check scopes explicitly.

    Raises:
        HTTPException(403): if any required scope is missing for an api_key auth.
    """
    auth = getattr(request.state, "auth", None)

    # Case 1: JWT/Clerk user — no auth dict set by middleware.
    if auth is None:
        return

    # Case 2: local dev key — bypass all scope checks.
    if auth.get("auth_method") == "local_key":
        return

    # Case 3: stored API key — enforce scopes explicitly.
    if auth.get("auth_method") == "api_key":
        key_scopes: list[str] = auth.get("scopes", [])
        missing = [s for s in required if s not in key_scopes]
        if missing:
            raise HTTPException(status_code=403, detail="Insufficient scope")
        return

    # Unknown auth method — fail closed.
    raise HTTPException(status_code=403, detail="Unknown authentication method")


def RequireScope(*scopes: str) -> Any:
    """FastAPI dependency factory for scope enforcement.

    Usage:
        @router.post("/endpoint", dependencies=[RequireScope("write", "execute")])
        async def my_endpoint(...):
            ...

    Or as a parameter dependency:
        async def my_endpoint(_: None = RequireScope("admin")):
            ...
    """
    return Depends(lambda request: require_scopes(request, *scopes))
