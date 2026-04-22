"""
SignalPilot Gateway Middleware — authentication, rate limiting, security headers.

Addresses:
  CRIT-01: Zero authentication on all endpoints
  CRIT-02: CORS allow-all enabling cross-origin attacks
  CRIT-03: Unauthenticated settings tampering
  HIGH-05: No rate limiting
  HIGH-06: Error message information leakage
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# Paths that don't require authentication
PUBLIC_PATHS = frozenset({
    "/health",
    "/docs",
    "/openapi.json",
    "/api/metrics",
})


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Validates API key from Authorization header or X-API-Key header.

    When the gateway has an api_key configured in settings, all non-public
    endpoints require a valid key. When no key is configured (dev mode),
    all requests are allowed with a warning header.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Always allow preflight CORS requests
        if request.method == "OPTIONS":
            return await call_next(request)

        # Public paths don't require auth
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Load the configured static API key, local key, and stored keys
        from .store import load_settings, validate_stored_api_key, list_api_keys, get_local_api_key
        settings = load_settings()
        expected_key = settings.api_key
        local_key = get_local_api_key()
        has_stored_keys = len(list_api_keys()) > 0

        # If no static key AND no stored keys AND no local key, allow all
        if not expected_key and not has_stored_keys and not local_key:
            response = await call_next(request)
            response.headers["X-SignalPilot-Auth"] = "none"
            return response

        # Extract key from Authorization: Bearer <key> or X-API-Key: <key>
        provided_key = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            provided_key = auth_header[7:].strip()
        if not provided_key:
            provided_key = request.headers.get("x-api-key", "").strip()

        if not provided_key:
            return Response(
                content='{"detail":"Authentication required. Provide API key via Authorization: Bearer <key> or X-API-Key header."}',
                status_code=401,
                media_type="application/json",
            )

        # Try stored API keys first
        matched = validate_stored_api_key(provided_key)
        if matched:
            response = await call_next(request)
            return response

        # Fall back to static settings.api_key
        if expected_key and hmac.compare_digest(provided_key, expected_key):
            response = await call_next(request)
            return response

        # Fall back to local dev key
        if local_key and hmac.compare_digest(provided_key, local_key):
            response = await call_next(request)
            return response

        return Response(
            content='{"detail":"Invalid API key."}',
            status_code=403,
            media_type="application/json",
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory sliding window rate limiter.

    Limits requests per IP address. Separate limits for
    expensive endpoints (query, execute) vs general API calls.
    """

    def __init__(self, app, general_rpm: int = 120, expensive_rpm: int = 30):
        super().__init__(app)
        self.general_rpm = general_rpm
        self.expensive_rpm = expensive_rpm
        # {ip: [timestamp, ...]}
        self._general_hits: dict[str, list[float]] = defaultdict(list)
        self._expensive_hits: dict[str, list[float]] = defaultdict(list)

    # Paths that count as "expensive" (DB queries, code execution)
    EXPENSIVE_PATHS = frozenset({
        "/api/query",
        "/api/sandboxes",  # POST creates a sandbox
    })

    def _is_expensive(self, request: Request) -> bool:
        path = request.url.path
        if path in self.EXPENSIVE_PATHS and request.method == "POST":
            return True
        # Sandbox execute endpoints
        if "/execute" in path and request.method == "POST":
            return True
        return False

    def _check_rate(self, hits: list[float], limit: int) -> bool:
        now = time.monotonic()
        window = now - 60  # 1-minute window
        # Prune old entries
        while hits and hits[0] < window:
            hits.pop(0)
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def _cleanup_stale_ips(self):
        """Remove IP entries with no recent hits to prevent memory leaks."""
        now = time.monotonic()
        window = now - 120  # 2-minute stale threshold
        for store in (self._general_hits, self._expensive_hits):
            stale_ips = [ip for ip, hits in store.items() if not hits or hits[-1] < window]
            for ip in stale_ips:
                del store[ip]

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        # Periodic cleanup of stale IP tracking (every ~100 requests)
        total_tracked = len(self._general_hits) + len(self._expensive_hits)
        if total_tracked > 100:
            self._cleanup_stale_ips()

        ip = self._client_ip(request)

        if self._is_expensive(request):
            if not self._check_rate(self._expensive_hits[ip], self.expensive_rpm):
                return Response(
                    content='{"detail":"Rate limit exceeded. Max ' + str(self.expensive_rpm) + ' expensive requests per minute."}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": "60"},
                )

        if not self._check_rate(self._general_hits[ip], self.general_rpm):
            return Response(
                content='{"detail":"Rate limit exceeded. Max ' + str(self.general_rpm) + ' requests per minute."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )

        response = await call_next(request)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"
        return response
