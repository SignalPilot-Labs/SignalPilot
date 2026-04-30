"""
Security headers middleware.
"""

from __future__ import annotations

import os

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
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
        csp_policy = os.environ.get("SP_GATEWAY_CSP_POLICY") or _CSP_DEFAULT_POLICY
        response.headers["Content-Security-Policy"] = csp_policy
        return response
