"""
API key authentication middleware.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from ..log_redaction import redact_secret_path

logger = logging.getLogger(__name__)

# Paths that don't require authentication.
# /api/metrics is intentionally excluded: it streams live infrastructure data
# and must be protected by auth to prevent unauthenticated topology enumeration.
PUBLIC_PATHS = frozenset(
    {
        "/health",
        "/docs",
        "/openapi.json",
        "/api/integrations/notion/oauth/callback",
        "/api/integrations/slack/oauth/callback",
        # Connector sign-in: provider redirect and the public client-metadata document.
        "/api/mcp/oauth/callback",
        "/api/mcp/oauth/client-metadata.json",
        "/api/notion/webhooks/events",
        "/api/github/webhook",
        "/slack/events",
    }
)


def _eval_rest_path_allowed(method: str, path: str, connection: str) -> bool:
    """REST surface an eval credential may use, including MCP proxy calls."""
    if method == "GET" and path == "/api/connections":
        return True
    connection_path = f"/api/connections/{connection}"
    if method == "POST" and path in {
        f"{connection_path}/schema/explore",
        f"{connection_path}/schema/explore-columns",
    }:
        return True
    if path == connection_path or path.startswith(connection_path + "/"):
        return method == "GET"
    if method == "POST" and path in {"/api/query", "/api/query/explain"}:
        return True
    if method == "GET" and path == "/api/connectors/capabilities":
        return True
    return False


async def _eval_credentials_active() -> bool:
    """Whether a live eval key exists in the local workspace."""
    from ...db.engine import get_session_factory
    from ...store import Store

    factory = get_session_factory()
    async with factory() as session:
        keys = await Store(session, allow_unscoped=True).list_api_keys()
    return any(key.eval_run_id for key in keys)


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

        # MCP endpoints have their own auth (MCPAuthMiddleware): skip
        if request.url.path.startswith("/mcp"):
            return await call_next(request)

        # GitHub OAuth flow: browser redirects, no API key
        if request.url.path.startswith("/auth/github"):
            return await call_next(request)

        # Git smart HTTP: auth handled inside the git router via Basic Auth.
        if request.url.path.startswith("/git/"):
            return await call_next(request)

        # Notebook proxy: auth handled by resolve_proxy_session (session cookie).
        # The iframe doesn't have the Clerk __session cookie (different origin).
        if request.url.path.startswith("/notebook/"):
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

        # Local JWT/cookie passthrough normally resolves to the privileged
        # single-user identity. During an eval, require a real stored key or
        # the private local dev key before either passthrough can run.
        from ...runtime.mode import is_local_mode

        trusted_local_key = bool(
            provided_key and local_key and hmac.compare_digest(provided_key, local_key)
        )
        if (
            is_local_mode()
            and not trusted_local_key
            and not (provided_key or "").startswith("sp_")
        ):
            try:
                if await _eval_credentials_active():
                    return Response(
                        content='{"detail":"Authentication required while eval workloads are active."}',
                        status_code=401,
                        media_type="application/json",
                    )
            except Exception:
                logger.exception("Could not verify whether eval credentials are active")
                return Response(
                    content='{"detail":"Authentication service unavailable."}',
                    status_code=503,
                    media_type="application/json",
                )

        # Check for Clerk JWT (__session cookie): let it through for resolve_user_id
        session_cookie = request.cookies.get("__session")
        if session_cookie and not provided_key:
            # Clerk JWT present, no API key: let resolve_user_id handle auth
            return await call_next(request)

        # If Bearer token is a JWT (not sp_ prefixed), let resolve_user_id handle it
        if provided_key and not provided_key.startswith("sp_"):
            return await call_next(request)

        if not provided_key:
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
                redact_secret_path(request.url.path),
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
                    from ...runtime.mode import is_cloud_mode

                    if matched.eval_run_id and not matched.eval_connection:
                        logger.warning("REST auth: rejecting eval key %s without a connection pin", matched.id)
                        return Response(
                            content='{"detail":"Eval credential is missing its connection binding."}',
                            status_code=403,
                            media_type="application/json",
                        )
                    if matched.eval_run_id and not _eval_rest_path_allowed(
                        request.method,
                        request.url.path,
                        matched.eval_connection,
                    ):
                        return Response(
                            content='{"detail":"Eval credential is not permitted on this REST endpoint."}',
                            status_code=403,
                            media_type="application/json",
                        )
                    request.state.auth = {
                        "user_id": matched.user_id,
                        "org_id": (matched.org_id or "local") if is_cloud_mode() else "local",
                        "key_id": matched.id,
                        "key_name": matched.name,
                        "auth_method": "api_key",
                        "scopes": matched.scopes,
                        "eval_run_id": matched.eval_run_id,
                        "eval_task_id": matched.eval_task_id,
                        "eval_connection": matched.eval_connection,
                        "eval_doc_ids": matched.eval_doc_ids,
                    }
                    request_id = getattr(request.state, "request_id", "unknown")
                    logger.info(
                        "request %s %s user=%s request_id=%s",
                        request.method,
                        redact_secret_path(request.url.path),
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
