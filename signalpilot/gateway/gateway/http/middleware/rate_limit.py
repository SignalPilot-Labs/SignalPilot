"""
Rate limiting middleware and per-principal rate limit helpers.
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from ...config import get_network_settings


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

    EXPENSIVE_PATHS = frozenset(
        {
            "/api/query",
            "/api/sandboxes",
        }
    )

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
                    content='{"detail":"Rate limit exceeded. Max '
                    + str(self.auth_rpm)
                    + ' auth requests per minute."}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": "60"},
                )

        # Tier 2: expensive endpoints — return early on 429
        if self._is_expensive(request):
            if not self._check_rate(self._expensive_hits[ip], self.expensive_rpm):
                return Response(
                    content='{"detail":"Rate limit exceeded. Max '
                    + str(self.expensive_rpm)
                    + ' expensive requests per minute."}',
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
_net = get_network_settings()
_PER_KEY_RPM = _net.sp_per_key_rpm
_PER_ORG_RPM = _net.sp_per_org_rpm


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
