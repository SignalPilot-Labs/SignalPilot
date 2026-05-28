"""
Security headers middleware.

For /notebook/* proxy paths the following headers behave differently:
- X-Frame-Options: SAMEORIGIN (not DENY) — the notebook runs in an iframe.
- Content-Security-Policy: frame-ancestors 'self' only (not the default CSP).
  The notebook server's own HTML/JS sets its own internal CSP. We do not layer one on top
  because doing so risks blocking its inline event handlers and wasm.
  `frame-ancestors 'self'` is the only CSP directive we keep on proxy responses,
  and `Cache-Control` is left for upstream to manage.
- Cache-Control: NOT forced to no-store — let the notebook server's own caching headers pass
  through. Forcing no-store re-fetches every JS/wasm chunk on every navigation
  and breaks WS resume of cacheable subresources.
- Set-Cookie: NOT stripped by this middleware. The _init and delete-clear responses
  intentionally set sp_nb_<sid> cookies — that is the entire point of the design.
  Distinct from proxy.py stripping UPSTREAM Set-Cookie inside forward_http.
"""

from __future__ import annotations

import os
import re

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# M-5: Exact path-shape gate for notebook proxy paths.
# Matches /notebook/{non-empty-segment}/... — requires a non-empty session_id
# segment so that accidental future paths like /notebook-other/... or /notebook/
# (bare) do not inherit the relaxed CSP.
# The session_id segment may be any non-slash character (charset-validation happens
# inside resolve_proxy_session; this pattern just confirms the shape is correct).
_NOTEBOOK_PROXY_PATH_RE = re.compile(r"^/notebook/[^/]+/")

_CSP_DEFAULT_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

def _build_proxy_csp() -> str:
    allowed_origins = os.environ.get("SP_ALLOWED_ORIGINS", "")
    ancestors = ["'self'"]
    for origin in allowed_origins.split(","):
        origin = origin.strip()
        if origin:
            ancestors.append(origin)
    return f"frame-ancestors {' '.join(ancestors)}"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        # Notebook proxy paths get relaxed framing and caching headers so the notebook server works.
        # M-5: Use an exact shape match (/notebook/{segment}/...) so accidental future
        # routes like /notebook-other/... or /notebook/ (bare) do NOT inherit the
        # relaxed CSP. Only requests that go through the proxy router qualify.
        is_proxy = bool(_NOTEBOOK_PROXY_PATH_RE.match(request.url.path))
        response.headers["X-Content-Type-Options"] = "nosniff"
        if not is_proxy:
            response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Cache-Control: only set on non-proxy paths. For /notebook/* let upstream's
        # own headers pass through (or leave absent if upstream sets nothing).
        if not is_proxy:
            response.headers["Cache-Control"] = "no-store"
        # interest-cohort=() is kept for older browser coverage; FLoC is deprecated
        # in modern browsers but the directive is harmless.
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        # HSTS is only sent over HTTPS to avoid locking browsers into HTTPS on
        # local HTTP dev setups. `preload` is intentionally omitted — it requires
        # explicit opt-in via hstspreload.org and is a domain-level commitment that
        # cannot be easily rolled back.
        is_https = request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https"
        if is_https:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        # CSP: SP_GATEWAY_CSP_POLICY overrides the default entirely when set.
        # The deployer owns the full policy — no merging or layering.
        # Proxy paths get a minimal policy: frame-ancestors 'self' only.
        if is_proxy:
            response.headers["Content-Security-Policy"] = _build_proxy_csp()
        else:
            csp_policy = os.environ.get("SP_GATEWAY_CSP_POLICY") or _CSP_DEFAULT_POLICY
            response.headers["Content-Security-Policy"] = csp_policy
        return response
