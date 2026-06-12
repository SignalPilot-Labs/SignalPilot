"""
Cookie-auth CSRF protection middleware.

Blocks cross-site mutation requests (non-safe methods) that are authenticated
solely via the __session cookie in cloud mode.  Bearer / API-key clients and
webhook prefixes are explicitly exempted.
"""

from __future__ import annotations

import logging
import urllib.parse

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

# Exempt path prefixes — these paths have their own auth / CSRF model and
# must not be blocked by this middleware.
_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/health",
    "/docs",
    "/openapi.json",
    "/mcp",             # Bearer-only MCP auth
    "/auth/github",     # Browser redirect; M-4 HMAC+nonce covers CSRF for install/link
    "/git/",            # Basic Auth, no cookie
    "/notebook/",       # sp_nb_<sid> cookie, not __session
    "/api/webhooks/",   # Reserved for future signed-body webhooks (Stripe/Clerk etc.)
)

_FORBIDDEN_BODY = '{"detail":"Forbidden."}'


def _is_exempt_path(path: str) -> bool:
    for prefix in _EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _recompose_origin(referer: str) -> str:
    """Parse Referer and recompose as scheme://netloc for allow-list comparison."""
    parsed = urllib.parse.urlsplit(referer)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


class CookieAuthCsrfMiddleware(BaseHTTPMiddleware):
    """Enforce Origin/Sec-Fetch-Site on cookie-only mutation requests in cloud mode.

    - Safe methods (GET, HEAD, OPTIONS) always pass through.
    - Exempt path prefixes always pass through.
    - Requests without a __session cookie pass through (auth middleware decides).
    - Requests with both __session and a Bearer/API-key header pass through
      (treat the non-cookie credential as primary, matching auth.py semantics).
    - For cookie-only mutations: accept if Sec-Fetch-Site indicates same-origin/site/none,
      or if Origin is in the allow-list, or if Referer's origin is in the allow-list.
    - Anything else is rejected with 403.
    """

    SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})
    SAME_SITE_TOKENS: frozenset[str] = frozenset({"same-origin", "same-site", "none"})

    def __init__(self, app: object, allowed_origins: list[str], enabled: bool) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._enabled = enabled
        self._allowed_origins: frozenset[str] = frozenset(
            o.rstrip("/") for o in allowed_origins
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._enabled:
            return await call_next(request)

        # Step 1 — safe methods always pass
        if request.method in self.SAFE_METHODS:
            return await call_next(request)

        # Step 2 — exempt path prefixes
        if _is_exempt_path(request.url.path):
            return await call_next(request)

        # Step 3 — cookie-only auth detection
        has_session_cookie = bool(request.cookies.get("__session"))
        auth_header = request.headers.get("authorization", "")
        has_bearer = auth_header.lower().startswith("bearer ")
        has_api_key_header = bool(request.headers.get("x-api-key", "").strip())

        if not has_session_cookie:
            # Bearer / API-key / unauthenticated — not our concern
            return await call_next(request)

        if has_bearer or has_api_key_header:
            # Dual-presented; treat non-cookie credential as primary
            return await call_next(request)

        # Step 4 — Sec-Fetch-Site fast accept
        sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
        if sec_fetch_site in self.SAME_SITE_TOKENS:
            return await call_next(request)

        # Step 5 — Origin allow-list check
        origin = request.headers.get("origin", "").rstrip("/")
        if origin and origin in self._allowed_origins:
            return await call_next(request)

        # Step 6 — Referer fallback (legacy browsers that strip Origin on same-origin POSTs)
        referer_host = ""
        if not origin:
            referer = request.headers.get("referer", "")
            if referer:
                referer_host = _recompose_origin(referer)
                if referer_host and referer_host in self._allowed_origins:
                    return await call_next(request)

        # Step 7 — reject
        request_id = getattr(request.state, "request_id", "unknown")
        logger.warning(
            "csrf_block path=%s method=%s origin=%r sec_fetch_site=%r referer_host=%r request_id=%s",
            request.url.path,
            request.method,
            origin,
            sec_fetch_site,
            referer_host,
            request_id,
        )
        return Response(
            content=_FORBIDDEN_BODY,
            status_code=403,
            media_type="application/json",
        )
