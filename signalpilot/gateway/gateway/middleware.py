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

import hmac
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

# Paths that don't require authentication
PUBLIC_PATHS = frozenset({
    "/health",
    "/docs",
    "/openapi.json",
})


def _is_public_path(path: str) -> bool:
    """Return True if the path is a public (unauthenticated) path."""
    normalized = path.rstrip("/")
    if normalized in PUBLIC_PATHS:
        return True
    for public in PUBLIC_PATHS:
        if normalized.startswith(public + "/"):
            return True
    return False


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generates a UUID4 request ID for every request.

    Stores the ID in ``request.state.request_id`` and echoes it back as the
    ``X-Request-ID`` response header to allow log correlation.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


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
        if _is_public_path(request.url.path):
            return await call_next(request)

        # Load the configured API key
        from .store import load_settings
        settings = load_settings()
        expected_key = settings.api_key

        # If no API key configured, allow all (dev mode) but flag it
        if not expected_key:
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
            client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
                request.client.host if request.client else "unknown"
            )
            logger.warning("Auth required but no key provided — ip=%s path=%s", client_ip, request.url.path)
            return Response(
                content='{"detail":"Authentication required. Provide API key via Authorization: Bearer <key> or X-API-Key header."}',
                status_code=401,
                media_type="application/json",
            )

        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(provided_key, expected_key):
            client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
                request.client.host if request.client else "unknown"
            )
            logger.warning("Invalid API key supplied — ip=%s path=%s", client_ip, request.url.path)
            return Response(
                content='{"detail":"Invalid API key."}',
                status_code=403,
                media_type="application/json",
            )

        response = await call_next(request)
        return response


class AuthBruteForceMiddleware(BaseHTTPMiddleware):
    """Blocks IPs that repeatedly fail authentication.

    Tracks 401/403 responses on write methods (POST, PUT, DELETE) using a
    5-minute sliding window. After 10 failures the IP is blocked for 15 minutes.
    """

    _WINDOW_SECONDS = 300       # 5-minute sliding window
    _MAX_FAILURES = 10          # failures before block
    _BLOCK_SECONDS = 900        # 15-minute block

    def __init__(self, app):
        super().__init__(app)
        # {ip: deque of failure timestamps}
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        # {ip: block-expiry timestamp}
        self._blocked: dict[str, float] = {}

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Only track mutating methods
        if request.method not in ("POST", "PUT", "DELETE"):
            return await call_next(request)

        ip = self._client_ip(request)
        now = time.monotonic()

        # Check if IP is currently blocked
        block_expiry = self._blocked.get(ip)
        if block_expiry is not None:
            if now < block_expiry:
                return Response(
                    content='{"detail":"Too many failed authentication attempts. Try again later."}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": str(int(block_expiry - now))},
                )
            # Block expired — clean up
            del self._blocked[ip]
            self._failures[ip].clear()

        response = await call_next(request)

        # Record failure on 401/403
        if response.status_code in (401, 403):
            hits = self._failures[ip]
            window_start = now - self._WINDOW_SECONDS
            while hits and hits[0] < window_start:
                hits.popleft()
            hits.append(now)
            if len(hits) >= self._MAX_FAILURES:
                self._blocked[ip] = now + self._BLOCK_SECONDS
                logger.warning(
                    "Brute-force block applied — ip=%s failures=%d", ip, len(hits)
                )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory sliding window rate limiter.

    Limits requests per IP address. Separate limits for
    expensive endpoints (query, execute) vs general API calls.
    """

    def __init__(self, app, general_rpm: int = 120, expensive_rpm: int = 30):
        super().__init__(app)
        self.general_rpm = general_rpm
        self.expensive_rpm = expensive_rpm
        # {ip: deque of timestamps}
        self._general_hits: dict[str, deque[float]] = defaultdict(deque)
        self._expensive_hits: dict[str, deque[float]] = defaultdict(deque)

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

    def _check_rate(self, hits: deque[float], limit: int) -> tuple[bool, int]:
        """Return (allowed, remaining) after recording the current request."""
        now = time.monotonic()
        window = now - 60  # 1-minute window
        # Prune old entries — O(1) per pop
        while hits and hits[0] < window:
            hits.popleft()
        if len(hits) >= limit:
            return False, 0
        hits.append(now)
        return True, limit - len(hits)

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

        expensive_remaining: int | None = None
        expensive_limit: int | None = None

        if self._is_expensive(request):
            allowed, remaining = self._check_rate(self._expensive_hits[ip], self.expensive_rpm)
            if not allowed:
                return Response(
                    content='{"detail":"Rate limit exceeded. Max ' + str(self.expensive_rpm) + ' expensive requests per minute."}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": "60"},
                )
            expensive_remaining = remaining
            expensive_limit = self.expensive_rpm

        allowed, general_remaining = self._check_rate(self._general_hits[ip], self.general_rpm)
        if not allowed:
            return Response(
                content='{"detail":"Rate limit exceeded. Max ' + str(self.general_rpm) + ' requests per minute."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )

        response = await call_next(request)

        # Add rate limit headers — prefer expensive limits when applicable
        if expensive_limit is not None and expensive_remaining is not None:
            response.headers["X-RateLimit-Limit"] = str(expensive_limit)
            response.headers["X-RateLimit-Remaining"] = str(expensive_remaining)
        else:
            response.headers["X-RateLimit-Limit"] = str(self.general_rpm)
            response.headers["X-RateLimit-Remaining"] = str(general_remaining)

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
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        return response
