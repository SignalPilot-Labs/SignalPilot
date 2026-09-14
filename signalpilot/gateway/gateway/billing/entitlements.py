"""Org entitlements: the one place the gateway asks "is this org on a billable plan".

Cloud mode (``SP_BACKEND_URL`` set) reads the backend-owned ``subscriptions``
row on the shared database. Local mode returns the ``unlimited`` tier.
Results are cached in-process for five minutes; ``invalidate(org_id)``
drops one org after a subscription change.

The gateway has no staff concept and no per-feature flag map: callers use
``is_billable`` and the allowance counters, nothing else.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from .rates import BILLABLE_TIERS, GRACE_DAYS

logger = logging.getLogger(__name__)

TIERS: tuple[str, ...] = ("free", "team", "scale", "enterprise", "unlimited")
LOCAL_TIER = "unlimited"
DEFAULT_TIER = "free"

# Legacy rows still carry these until the backend migration renames them.
_LEGACY_TIER_MAP = {"pro": "team", "team": "team"}

CACHE_TTL_SECONDS = 5 * 60
_MAX_CACHE_ENTRIES = 10_000
_cache: dict[str, tuple[OrgEntitlement, float]] = {}
_legacy_schema_logged = False


@dataclass(frozen=True, slots=True)
class OrgEntitlement:
    """What an org is entitled to this period, read from the subscriptions row."""

    org_id: str
    tier: str = DEFAULT_TIER
    status: str = "none"
    included_seats: int = 0
    included_models: int = 0
    included_eval_runs: int = 0
    included_credits: int = 0
    managed: bool = False
    billing_interval: str = "month"
    enterprise_flags: dict[str, Any] = field(default_factory=dict)
    grace_until: datetime | None = None
    current_period_end: datetime | None = None

    @property
    def is_billable(self) -> bool:
        """The one gating rule: active or trialing, or past_due inside the grace window; never free."""
        return self.billable_at(datetime.now(UTC))

    @property
    def is_metered(self) -> bool:
        """Local mode is billable (every feature on) but never writes credits."""
        return self.tier != LOCAL_TIER

    def billable_at(self, now: datetime) -> bool:
        """``is_billable`` evaluated at ``now`` (aware UTC)."""
        if self.tier not in BILLABLE_TIERS and self.tier != LOCAL_TIER:
            return False
        if self.status in ("active", "trialing"):
            return True
        if self.status == "past_due" and self.grace_until is not None:
            return now < _aware(self.grace_until)
        return False

    def to_dict(self) -> dict[str, Any]:
        """Serialise for the bootstrap payload (includes the computed ``is_billable``)."""
        return {
            "org_id": self.org_id,
            "tier": self.tier,
            "status": self.status,
            "is_billable": self.is_billable,
            "included_seats": self.included_seats,
            "included_models": self.included_models,
            "included_eval_runs": self.included_eval_runs,
            "included_credits": self.included_credits,
            "managed": self.managed,
            "billing_interval": self.billing_interval,
            "enterprise_flags": dict(self.enterprise_flags),
            "grace_until": self.grace_until.isoformat() if self.grace_until else None,
        }


def local_entitlement(org_id: str) -> OrgEntitlement:
    """Entitlement for a deployment without a backend: everything on, nothing metered."""
    return OrgEntitlement(org_id=org_id, tier=LOCAL_TIER, status="active")


def free_entitlement(org_id: str) -> OrgEntitlement:
    """Entitlement for an org with no subscription row."""
    return OrgEntitlement(org_id=org_id, tier=DEFAULT_TIER, status="none")


def is_cloud_mode() -> bool:
    """Cloud mode is any deployment with a backend to read subscriptions from."""
    return bool(os.environ.get("SP_BACKEND_URL"))


def normalize_tier(raw: str | None) -> str:
    """Map a subscriptions.plan_tier value onto the current tier set."""
    value = (raw or "").strip().lower()
    if value in BILLABLE_TIERS:
        return value
    return _LEGACY_TIER_MAP.get(value, DEFAULT_TIER)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _parse_flags(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


def entitlement_from_row(org_id: str, row: Mapping[str, Any]) -> OrgEntitlement:
    """Build an entitlement from a subscriptions row mapping (full or legacy columns).

    A past_due row without ``grace_until`` gets ``current_period_end + GRACE_DAYS``
    so the grace window still applies before the backend has written the column.
    """
    grace_until = row.get("grace_until")
    period_end = row.get("current_period_end")
    status = str(row.get("status") or "none")
    if grace_until is None and status == "past_due" and period_end is not None:
        grace_until = _aware(period_end) + timedelta(days=GRACE_DAYS)
    return OrgEntitlement(
        org_id=org_id,
        tier=normalize_tier(row.get("plan_tier")),
        status=status,
        included_seats=int(row.get("included_seats") or 0),
        included_models=int(row.get("included_models") or 0),
        included_eval_runs=int(row.get("included_eval_runs") or 0),
        included_credits=int(row.get("included_credits") or 0),
        managed=bool(row.get("managed") or False),
        billing_interval=str(row.get("billing_interval") or "month"),
        enterprise_flags=_parse_flags(row.get("enterprise_flags")),
        grace_until=_aware(grace_until) if grace_until is not None else None,
        current_period_end=_aware(period_end) if period_end is not None else None,
    )


_FULL_SQL = text(
    "SELECT plan_tier, status, current_period_end, included_seats, included_models, "
    "included_eval_runs, included_credits, managed, billing_interval, enterprise_flags, "
    "grace_until FROM subscriptions WHERE org_id = :oid"
)
_LEGACY_SQL = text("SELECT plan_tier, status, current_period_end FROM subscriptions WHERE org_id = :oid")


async def _load_entitlement(org_id: str) -> OrgEntitlement:
    """Uncached read of the subscriptions row. Raises on a lookup failure."""
    global _legacy_schema_logged

    from ..db.engine import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        try:
            row = (await session.execute(_FULL_SQL, {"oid": org_id})).mappings().first()
        except Exception as exc:  # backend migration 004 not applied yet
            await session.rollback()
            if not _legacy_schema_logged:
                _legacy_schema_logged = True
                logger.warning(
                    "subscriptions lacks the entitlement columns; using plan_tier only with zero allowances (%s)",
                    exc.__class__.__name__,
                )
            row = (await session.execute(_LEGACY_SQL, {"oid": org_id})).mappings().first()
    if row is None:
        return free_entitlement(org_id)
    return entitlement_from_row(org_id, row)


async def get_entitlement(org_id: str) -> OrgEntitlement:
    """Return the org's entitlement, cached for CACHE_TTL_SECONDS.

    A transient lookup failure returns a free entitlement for this call only
    and is never cached, so a paying org is not paywalled for the TTL.
    """
    if not is_cloud_mode():
        return local_entitlement(org_id)
    if not org_id or org_id == "local":
        return free_entitlement(org_id)
    cached = _cache.get(org_id)
    if cached is not None and cached[1] > time.monotonic():
        return cached[0]
    try:
        entitlement = await _load_entitlement(org_id)
    except Exception:
        logger.warning("failed to resolve entitlement for org %s; treating as free for this request", org_id)
        return free_entitlement(org_id)
    _cache[org_id] = (entitlement, time.monotonic() + CACHE_TTL_SECONDS)
    while len(_cache) > _MAX_CACHE_ENTRIES:
        _cache.pop(next(iter(_cache)))
    return entitlement


def invalidate(org_id: str | None = None) -> None:
    """Drop the cached entitlement for one org, or every org when ``org_id`` is None."""
    if org_id is None:
        _cache.clear()
    else:
        _cache.pop(org_id, None)


__all__ = [
    "CACHE_TTL_SECONDS",
    "DEFAULT_TIER",
    "LOCAL_TIER",
    "TIERS",
    "OrgEntitlement",
    "entitlement_from_row",
    "free_entitlement",
    "get_entitlement",
    "invalidate",
    "is_cloud_mode",
    "local_entitlement",
    "normalize_tier",
]
