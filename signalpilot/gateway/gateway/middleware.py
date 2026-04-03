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
import os
import time
import uuid
from collections import defaultdict, deque

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

# Paths that don't require authentication (exact matches only)
PUBLIC_PATHS = frozenset({
    "/health",
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
})

# Number of trusted reverse proxies. When > 0, X-Forwarded-For is trusted
# and the Nth-from-right entry is used as the real client IP. When 0,
# X-Forwarded-For is ignored entirely and request.client.host is used.
_TRUSTED_PROXY_COUNT = int(os.getenv("SP_TRUSTED_PROXY_COUNT", "0"))


def _is_public_path(path: str) -> bool:
    """Return True if the path is a public (unauthenticated) path.

    Uses exact match only to prevent path traversal attacks.
    """
    normalized = path.rstrip("/")
    return normalized in PUBLIC_PATHS


def _client_ip(request: Request) -> str:
    """Extract client IP from request, respecting trusted proxy configuration.

    When SP_TRUSTED_PROXY_COUNT > 0, uses the Nth-from-right entry in
    X-Forwarded-For (the entry added by the outermost trusted proxy).
    Otherwise ignores X-Forwarded-For entirely to prevent spoofing.
    """
    if _TRUSTED_PROXY_COUNT > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",")]
            # Take the entry added by the trusted proxy (Nth from right)
            idx = max(0, len(parts) - _TRUSTED_PROXY_COUNT)
            return parts[idx]
    return request.client.host if request.client else "unknown"


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

        # If no API key configured, allow all (dev mode) — log warning server-side
        # (don't advertise auth state in response headers)
        if not expected_key:
            logger.warning("No API key configured — running in dev mode (unauthenticated)")
            return await call_next(request)

        # Extract key from Authorization: Bearer <key> or X-API-Key: <key>
        provided_key = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            provided_key = auth_header[7:].strip()
        if not provided_key:
            provided_key = request.headers.get("x-api-key", "").strip()

        if not provided_key:
            client_ip = _client_ip(request)
            logger.warning("Auth required but no key provided — ip=%s path=%s", client_ip, request.url.path)
            return Response(
                content='{"detail":"Authentication required. Provide API key via Authorization: Bearer <key> or X-API-Key header."}',
                status_code=401,
                media_type="application/json",
            )

        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(provided_key, expected_key):
            client_ip = _client_ip(request)
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

    _MAX_TRACKED_IPS = 10_000  # cap to prevent memory exhaustion

    def __init__(self, app):
        super().__init__(app)
        # {ip: deque of failure timestamps}
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        # {ip: block-expiry timestamp}
        self._blocked: dict[str, float] = {}
        self._cleanup_counter = 0

    def _cleanup_stale(self):
        """Remove expired blocks and stale failure entries."""
        now = time.monotonic()
        # Clean expired blocks
        expired = [ip for ip, exp in self._blocked.items() if now >= exp]
        for ip in expired:
            del self._blocked[ip]
            self._failures.pop(ip, None)
        # Clean stale failure entries (no hits in 2x window)
        stale_cutoff = now - self._WINDOW_SECONDS * 2
        stale = [ip for ip, hits in self._failures.items()
                 if not hits or hits[-1] < stale_cutoff]
        for ip in stale:
            del self._failures[ip]

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        ip = _client_ip(request)
        now = time.monotonic()

        # Periodic cleanup to prevent unbounded memory growth
        self._cleanup_counter += 1
        if self._cleanup_counter >= 100 or len(self._failures) > self._MAX_TRACKED_IPS:
            self._cleanup_counter = 0
            self._cleanup_stale()

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
            self._failures.pop(ip, None)

        response = await call_next(request)

        # Record failure on 401/403
        if response.status_code in (401, 403):
            # Hard cap: skip recording new IPs when at capacity to prevent
            # memory exhaustion from distributed brute-force attacks
            if ip not in self._failures and len(self._failures) >= self._MAX_TRACKED_IPS:
                return response
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

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        # Periodic cleanup of stale IP tracking (every ~100 requests)
        total_tracked = len(self._general_hits) + len(self._expensive_hits)
        if total_tracked > 100:
            self._cleanup_stale_ips()

        ip = _client_ip(request)

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
