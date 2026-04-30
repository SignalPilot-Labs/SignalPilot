"""
API key authentication middleware.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

# Paths that don't require authentication.
# /api/metrics is intentionally excluded — it streams live infrastructure data
# and must be protected by auth to prevent unauthenticated topology enumeration.
PUBLIC_PATHS = frozenset(
    {
        "/health",
        "/docs",
        "/openapi.json",
    }
)


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Validates API key from Authorization header or X-API-Key header.

    In local mode (no SP_BACKEND_URL), uses the local dev key for browser auth.
    MCP auth is handled separately by MCPAuthMiddleware.
    API key validation against DB is done by MCPAuthMiddleware or auth dependency.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # MCP endpoints have their own auth (MCPAuthMiddleware) — skip
        if request.url.path.startswith("/mcp"):
            return await call_next(request)

        from ...store import get_local_api_key

        local_key = get_local_api_key()

        # Extract key from headers
        provided_key = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            provided_key = auth_header[7:].strip()
        if not provided_key:
            provided_key = request.headers.get("x-api-key", "").strip()

        # Check for Clerk JWT (__session cookie) — let it through for resolve_user_id
        session_cookie = request.cookies.get("__session")
        if session_cookie and not provided_key:
            # Clerk JWT present, no API key — let resolve_user_id handle auth
            return await call_next(request)

        # If Bearer token is a JWT (not sp_ prefixed), let resolve_user_id handle it
        if provided_key and not provided_key.startswith("sp_"):
            return await call_next(request)

        if not provided_key:
            # Local mode: allow unauthenticated access (key is optional)
            from ...runtime.mode import is_local_mode

            if is_local_mode():
                request.state.auth = {"user_id": "local", "org_id": "local", "auth_method": "local_nokey"}
                return await call_next(request)
            return Response(
                content='{"detail":"Authentication required. Provide API key via Authorization: Bearer <key> or X-API-Key header."}',
                status_code=401,
                media_type="application/json",
            )

        # Local dev key check (fast, no DB needed)
        if local_key and hmac.compare_digest(provided_key, local_key):
            request.state.auth = {"user_id": "local", "org_id": "local", "auth_method": "local_key"}
            request_id = getattr(request.state, "request_id", "unknown")
            logger.info(
                "request %s %s user=%s request_id=%s",
                request.method,
                request.url.path,
                "local",
                request_id,
            )
            return await call_next(request)

        # For stored API keys, validate against DB
        try:
            from ...db.engine import get_session_factory
            from ...store import Store

            factory = get_session_factory()
            async with factory() as session:
                store = Store(session)  # No user_id filter for validation
                matched = await store.validate_stored_api_key(provided_key)
                if matched:
                    request.state.auth = {
                        "user_id": matched.user_id,
                        "org_id": matched.org_id or "local",
                        "key_id": matched.id,
                        "key_name": matched.name,
                        "auth_method": "api_key",
                        "scopes": matched.scopes,
                    }
                    request_id = getattr(request.state, "request_id", "unknown")
                    logger.info(
                        "request %s %s user=%s request_id=%s",
                        request.method,
                        request.url.path,
                        matched.user_id,
                        request_id,
                    )
                    return await call_next(request)
        except Exception as e:
            logger.warning("API key DB validation failed: %s", e)

        return Response(
            content='{"detail":"Invalid API key."}',
            status_code=403,
            media_type="application/json",
        )
