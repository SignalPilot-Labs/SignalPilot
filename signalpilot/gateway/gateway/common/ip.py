"""Client IP derivation for audit metadata.

This module provides a single canonical way to extract the trusted client IP
from an incoming HTTP request.  It intentionally mirrors
``RateLimitMiddleware._client_ip`` so that the IP logged in audit entries and
the IP used as the rate-limit bucket key are always the same value.

# TODO(security): Add SP_TRUSTED_PROXY_HOPS support for multi-proxy chains.
# Today's deployments terminate at a single trusted proxy so the rightmost XFF
# hop is always correct.  When configurable hop counts land, this module is the
# only place that needs to change.
"""

from __future__ import annotations

from fastapi import Request

_XFF = "x-forwarded-for"


def client_ip(request: Request) -> str | None:
    """Return the rightmost-trusted-hop client IP for audit metadata.

    Order (matches RateLimitMiddleware._client_ip exactly):
      1. Last non-empty, stripped entry of X-Forwarded-For, if present.
      2. request.client.host, if available.
      3. None.

    Never consults X-Real-IP (would diverge from rate-limit bucket key).
    Never returns the leftmost XFF value (spoofable by the client).
    Never raises.
    """
    forwarded = request.headers.get(_XFF)
    if forwarded is not None:
        parts = [p.strip() for p in forwarded.split(",")]
        non_empty = [p for p in parts if p]
        if non_empty:
            return non_empty[-1]
    if request.client is not None:
        return request.client.host
    return None


def request_meta(request: Request) -> tuple[str | None, str | None]:
    """Return ``(client_ip, user_agent)`` for ``AuditEntry`` construction.

    ``user_agent`` is ``request.headers.get("user-agent")``; no normalization.
    """
    return client_ip(request), request.headers.get("user-agent")
