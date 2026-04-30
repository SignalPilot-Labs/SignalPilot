"""
SignalPilot Gateway Middleware — authentication, rate limiting, security headers.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import time
from collections import defaultdict
from typing import Any

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

_MAX_BODY_BYTES_DEFAULT = 2_097_152  # 2MB


class RequestBodySizeLimitMiddleware:
    """Reject requests whose body exceeds max_body_bytes with HTTP 413.

    This is implemented as a raw ASGI middleware (not BaseHTTPMiddleware)
    because BaseHTTPMiddleware buffers the entire request body into memory
    when calling call_next(), which defeats the purpose of streaming byte
    counting for chunked transfers. Raw ASGI lets us wrap the receive callable
    to count bytes incrementally and abort before the app reads the body.

    For requests with Content-Length present: reject immediately with 413
    without reading any body bytes.
    For chunked/streaming bodies without Content-Length: wrap the receive
    callable and count cumulative body bytes, rejecting when the limit is hit.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int = _MAX_BODY_BYTES_DEFAULT) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        if method in ("GET", "OPTIONS", "HEAD"):
            await self.app(scope, receive, send)
            return

        # Check Content-Length header for early rejection
        headers: dict[bytes, bytes] = dict(scope.get("headers", []))
        content_length_raw = headers.get(b"content-length")
        if content_length_raw is not None:
            try:
                content_length = int(content_length_raw)
            except ValueError:
                # Unparseable Content-Length — reject as malformed
                await self._send_413(send)
                return
            if content_length > self.max_body_bytes:
                await self._send_413(send)
                return

        # Wrap receive to count bytes for chunked/streaming bodies.
        # Track whether the app has started sending a response — if it has,
        # we cannot send a 413 (ASGI protocol violation: duplicate response.start).
        bytes_received: list[int] = [0]
        response_started: list[bool] = [False]

        async def counting_receive() -> Any:
            message = await receive()
            if message.get("type") == "http.request":
                chunk = message.get("body", b"")
                bytes_received[0] += len(chunk)
                if bytes_received[0] > self.max_body_bytes and not response_started[0]:
                    await self._send_413(send)
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: dict) -> None:
            if message.get("type") == "http.response.start":
                response_started[0] = True
            await send(message)

        await self.app(scope, counting_receive, tracking_send)

    async def _send_413(self, send: Send) -> None:
        body = json.dumps({"detail": "Request body too large."}).encode()
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        })


# Paths that don't require authentication.
# /api/metrics is intentionally excluded — it streams live infrastructure data
# and must be protected by auth to prevent unauthenticated topology enumeration.
PUBLIC_PATHS = frozenset({
    "/health",
    "/docs",
    "/openapi.json",
})


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

        from .store import get_local_api_key

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
            from .deployment import is_local_mode
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
            from .db.engine import get_session_factory
            from .store import Store
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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory sliding window rate limiter.

    Three tiers (checked in order):
      1. Auth (10 rpm)     — POST /api/keys
      2. Expensive (30 rpm) — POST /api/query, /api/sandboxes, *execute*
      3. General (120 rpm)  — all other requests

    A 429 on any tier returns early without incrementing lower-tier buckets.
    Auth requests that pass tier 1 still fall through to the general tier.
    """

    AUTH_PATHS = frozenset({"/api/keys"})

    EXPENSIVE_PATHS = frozenset({
        "/api/query",
        "/api/sandboxes",
    })

    def __init__(self, app: ASGIApp, general_rpm: int = 120, expensive_rpm: int = 30, auth_rpm: int = 10) -> None:
        super().__init__(app)
        self.general_rpm = general_rpm
        self.expensive_rpm = expensive_rpm
        self.auth_rpm = auth_rpm
        self._general_hits: dict[str, list[float]] = defaultdict(list)
        self._expensive_hits: dict[str, list[float]] = defaultdict(list)
        self._auth_hits: dict[str, list[float]] = defaultdict(list)

    def _is_auth(self, request: Request) -> bool:
        return request.url.path in self.AUTH_PATHS and request.method == "POST"

    def _is_expensive(self, request: Request) -> bool:
        path = request.url.path
        if path in self.EXPENSIVE_PATHS and request.method == "POST":
            return True
        if "/execute" in path and request.method == "POST":
            return True
        return False

    def _check_rate(self, hits: list[float], limit: int) -> bool:
        now = time.monotonic()
        window = now - 60
        while hits and hits[0] < window:
            hits.pop(0)
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def _cleanup_stale_ips(self) -> None:
        now = time.monotonic()
        window = now - 120
        for store_dict in (self._general_hits, self._expensive_hits, self._auth_hits):
            stale_ips = [ip for ip, hits in store_dict.items() if not hits or hits[-1] < window]
            for ip in stale_ips:
                del store_dict[ip]

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Use rightmost IP (added by the closest trusted proxy) to prevent
            # spoofing via attacker-controlled leftmost values.
            return forwarded.split(",")[-1].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        total_tracked = len(self._general_hits) + len(self._expensive_hits) + len(self._auth_hits)
        if total_tracked > 100:
            self._cleanup_stale_ips()

        ip = self._client_ip(request)

        # Tier 1: auth endpoints — check first, return early on 429
        if self._is_auth(request):
            if not self._check_rate(self._auth_hits[ip], self.auth_rpm):
                return Response(
                    content='{"detail":"Rate limit exceeded. Max ' + str(self.auth_rpm) + ' auth requests per minute."}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": "60"},
                )

        # Tier 2: expensive endpoints — return early on 429
        if self._is_expensive(request):
            if not self._check_rate(self._expensive_hits[ip], self.expensive_rpm):
                return Response(
                    content='{"detail":"Rate limit exceeded. Max ' + str(self.expensive_rpm) + ' expensive requests per minute."}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": "60"},
                )

        # Tier 3: general bucket — all requests that pass the above tiers
        if not self._check_rate(self._general_hits[ip], self.general_rpm):
            return Response(
                content='{"detail":"Rate limit exceeded. Max ' + str(self.general_rpm) + ' requests per minute."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )

        return await call_next(request)


# ─── Per-key / per-org rate limiting (runs AFTER auth resolves) ────────────

_key_hits: dict[str, list[float]] = defaultdict(list)
_org_hits: dict[str, list[float]] = defaultdict(list)
_PER_KEY_RPM = int(os.environ.get("SP_PER_KEY_RPM", "1000"))
_PER_ORG_RPM = int(os.environ.get("SP_PER_ORG_RPM", "5000"))


def check_principal_rate_limit(key_id: str | None, org_id: str | None) -> str | None:
    """Check per-key and per-org rate limits. Returns error message or None."""
    now = time.monotonic()
    cutoff = now - 60.0

    if key_id:
        hits = _key_hits[key_id]
        _key_hits[key_id] = [t for t in hits if t > cutoff]
        if len(_key_hits[key_id]) >= _PER_KEY_RPM:
            return "Per-key rate limit exceeded"
        _key_hits[key_id].append(now)

    if org_id and org_id != "local":
        hits = _org_hits[org_id]
        _org_hits[org_id] = [t for t in hits if t > cutoff]
        if len(_org_hits[org_id]) >= _PER_ORG_RPM:
            return "Per-org rate limit exceeded"
        _org_hits[org_id].append(now)

    return None


async def enforce_principal_rate_limit(request: Request) -> None:
    """FastAPI dependency — runs after auth middleware has set request.state.auth."""
    auth = getattr(request.state, "auth", None) or {}
    key_id = auth.get("key_id")
    org_id = auth.get("org_id")
    error = check_principal_rate_limit(key_id, org_id)
    if error:
        raise HTTPException(status_code=429, detail=error)


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
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        )
        # HSTS is only sent over HTTPS to avoid locking browsers into HTTPS on
        # local HTTP dev setups. `preload` is intentionally omitted — it requires
        # explicit opt-in via hstspreload.org and is a domain-level commitment that
        # cannot be easily rolled back.
        is_https = (
            request.headers.get("x-forwarded-proto") == "https"
            or request.url.scheme == "https"
        )
        if is_https:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )
        # CSP: SP_GATEWAY_CSP_POLICY overrides the default entirely when set.
        # The deployer owns the full policy — no merging or layering.
        csp_policy = os.environ.get("SP_GATEWAY_CSP_POLICY") or _CSP_DEFAULT_POLICY
        response.headers["Content-Security-Policy"] = csp_policy
        return response
