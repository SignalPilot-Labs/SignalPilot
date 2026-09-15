"""Minimal Clerk Backend API client: count an organization's members.

The gateway has no other Clerk server-side call; auth verifies JWTs with the
publishable key's JWKS. Seat metering needs the member count, which only the
Backend API exposes, so this module reads ``CLERK_SECRET_KEY`` (the same
variable the backend service uses) and calls
``GET /v1/organizations/{org_id}/memberships?limit=1`` for its
``total_count``. Pending invitations are not memberships and do not count.

Returns None when the key is unset or the call fails; the daily job then
skips the seat row and logs, rather than writing a wrong count.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

CLERK_API_BASE = "https://api.clerk.com/v1"
CLERK_SECRET_KEY_ENV = "CLERK_SECRET_KEY"
_TIMEOUT_SECONDS = 10.0


def clerk_secret_key() -> str | None:
    value = os.environ.get(CLERK_SECRET_KEY_ENV, "").strip()
    return value or None


def _count_from_payload(payload: object) -> int | None:
    if isinstance(payload, dict):
        total = payload.get("total_count")
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
            return total
        data = payload.get("data")
        if isinstance(data, list):
            return len(data)
    if isinstance(payload, list):
        return len(payload)
    return None


async def org_member_count(org_id: str, *, client: httpx.AsyncClient | None = None) -> int | None:
    """Return the number of accepted members of the Clerk org, or None when unavailable."""
    key = clerk_secret_key()
    if not key or not org_id:
        logger.debug("clerk member count skipped: no %s or org id", CLERK_SECRET_KEY_ENV)
        return None
    url = f"{CLERK_API_BASE}/organizations/{org_id}/memberships"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        if client is not None:
            response = await client.get(url, params={"limit": 1}, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as own:
                response = await own.get(url, params={"limit": 1}, headers=headers)
        response.raise_for_status()
        count = _count_from_payload(response.json())
    except Exception:
        logger.warning("clerk member count failed for org %s", org_id, exc_info=True)
        return None
    if count is None:
        logger.warning("clerk member count: unexpected payload for org %s", org_id)
    return count


__all__ = ["CLERK_API_BASE", "CLERK_SECRET_KEY_ENV", "clerk_secret_key", "org_member_count"]
