"""
SignalPilot Gateway Middleware — authentication, rate limiting, security headers.
"""

from __future__ import annotations

import hmac
import json
import logging
import time
from collections import defaultdict
from typing import Any

from fastapi import Request, Response
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


# Paths that don't require authentication
PUBLIC_PATHS = frozenset({
    "/health",
    "/docs",
    "/openapi.json",
    "/api/metrics",
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
            return Response(
                content='{"detail":"Authentication required. Provide API key via Authorization: Bearer <key> or X-API-Key header."}',
                status_code=401,
                media_type="application/json",
            )

        # Local dev key check (fast, no DB needed)
        if local_key and hmac.compare_digest(provided_key, local_key):
            request.state.auth = {"user_id": "local", "auth_method": "local_key"}
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
                        "user_id": matched.user_id if hasattr(matched, 'user_id') else "local",
                        "key_id": matched.id,
                        "key_name": matched.name,
                        "auth_method": "api_key",
                    }
                    return await call_next(request)
        except Exception as e:
            logger.warning("API key DB validation failed: %s", e)

        return Response(
            content='{"detail":"Invalid API key."}',
            status_code=403,
            media_type="application/json",
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory sliding window rate limiter."""

    def __init__(self, app, general_rpm: int = 120, expensive_rpm: int = 30):
        super().__init__(app)
        self.general_rpm = general_rpm
        self.expensive_rpm = expensive_rpm
        self._general_hits: dict[str, list[float]] = defaultdict(list)
        self._expensive_hits: dict[str, list[float]] = defaultdict(list)

    EXPENSIVE_PATHS = frozenset({
        "/api/query",
        "/api/sandboxes",
    })

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

    def _cleanup_stale_ips(self):
        now = time.monotonic()
        window = now - 120
        for store_dict in (self._general_hits, self._expensive_hits):
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

        return await call_next(request)


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
