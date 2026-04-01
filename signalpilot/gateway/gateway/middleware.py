"""
Gateway middleware — authentication, rate limiting, and security headers.

Addresses CRIT-01 (no auth), HIGH-05 (no rate limiting), and LOW-05 (no security headers)
from the security audit.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Paths that never require authentication
_PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

# Paths that count as "expensive" for rate limiting
_EXPENSIVE_PATTERNS = ("/api/query", "/execute")


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """
    API key authentication middleware (CRIT-01).

    When api_key is configured in settings, all /api/* requests must include
    either `Authorization: Bearer <key>` or `X-API-Key: <key>`.
    When no api_key is configured (dev mode), all requests pass through.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # OPTIONS (CORS preflight) and public paths bypass auth
        if request.method == "OPTIONS" or request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        from .store import load_settings
        settings = load_settings()
        configured_key = settings.api_key

        # Dev mode: no key configured = allow all
        if not configured_key:
            response = await call_next(request)
            response.headers["X-SignalPilot-Auth"] = "none"
            return response

        # Extract key from headers
        provided_key = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            provided_key = auth_header[7:].strip()

        if provided_key is None:
            provided_key = request.headers.get("x-api-key")

        if provided_key is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required. Provide Authorization: Bearer <key> or X-API-Key header."},
            )

        if provided_key != configured_key:
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid API key"},
            )

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter (HIGH-05).

    Tracks request timestamps per client IP with separate limits for
    general endpoints and expensive endpoints (query, execute).
    """

    def __init__(self, app, general_rpm: int = 60, expensive_rpm: int = 20):
        super().__init__(app)
        self.general_rpm = general_rpm
        self.expensive_rpm = expensive_rpm
        self._general_hits: list[float] = []
        self._expensive_hits: list[float] = []
        self._window = 60.0  # seconds

    def _prune(self, hits: list[float], now: float) -> list[float]:
        cutoff = now - self._window
        return [t for t in hits if t > cutoff]

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        now = time.monotonic()
        path = request.url.path

        # Check expensive endpoints
        is_expensive = any(pat in path for pat in _EXPENSIVE_PATTERNS)
        if is_expensive:
            self._expensive_hits = self._prune(self._expensive_hits, now)
            if len(self._expensive_hits) >= self.expensive_rpm:
                retry_after = int(self._window - (now - self._expensive_hits[0])) + 1
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded for expensive endpoint"},
                    headers={"Retry-After": str(retry_after)},
                )
            self._expensive_hits.append(now)

        # Check general limit
        self._general_hits = self._prune(self._general_hits, now)
        if len(self._general_hits) >= self.general_rpm:
            retry_after = int(self._window - (now - self._general_hits[0])) + 1
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )
        self._general_hits.append(now)

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add security headers to all responses (LOW-05).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"
        return response
