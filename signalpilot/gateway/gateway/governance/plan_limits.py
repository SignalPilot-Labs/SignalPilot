"""Plan tier limits and enforcement.

Defines per-tier limits and provides helpers to check them.

In cloud mode, the org's plan_tier is read from the backend's `subscriptions`
table (Stripe source of truth). In local mode, it reads from `gateway_orgs`.
Both tables live in the same database.

Usage:
    limits = get_plan_limits(org_id, session)
    limits.check_connection_limit(current_count)  # raises 403 if exceeded
    limits.check_query_limit(org_id)               # raises 429 if exceeded
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

logger = logging.getLogger(__name__)

_is_cloud = os.environ.get("SP_DEPLOYMENT_MODE") == "cloud"

# ── Tier definitions ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PlanLimits:
    tier: str
    connections: int          # max DB connections (0 = unlimited)
    users: int                # max org members (0 = unlimited)
    api_keys: int             # max API keys (0 = unlimited)
    queries_per_day: int      # max governed queries per day (0 = unlimited)
    audit_retention_days: int # audit log retention (0 = unlimited)
    pii_redaction: bool       # full PII redaction (detect is always free)
    byok: bool                # BYOK encryption
    sso: bool                 # SSO (SAML/OIDC)
    budget_controls: bool     # per-session budget caps
    audit_export: bool        # CSV/JSON audit export
    schema_tools: bool        # advanced schema explorer MCP tools


PLAN_TIERS: dict[str, PlanLimits] = {
    "free": PlanLimits(
        tier="free",
        connections=2,
        users=1,
        api_keys=1,
        queries_per_day=200,
        audit_retention_days=7,
        pii_redaction=False,
        byok=False,
        sso=False,
        budget_controls=False,
        audit_export=False,
        schema_tools=True,
    ),
    "pro": PlanLimits(
        tier="pro",
        connections=10,
        users=3,
        api_keys=100,
        queries_per_day=10000,
        audit_retention_days=90,
        pii_redaction=True,
        byok=False,
        sso=False,
        budget_controls=True,
        audit_export=False,
        schema_tools=True,
    ),
    "team": PlanLimits(
        tier="team",
        connections=100,
        users=100,
        api_keys=100,
        queries_per_day=100000,
        audit_retention_days=365,
        pii_redaction=True,
        byok=True,
        sso=True,
        budget_controls=True,
        audit_export=True,
        schema_tools=True,
    ),
    "enterprise": PlanLimits(
        tier="enterprise",
        connections=100,
        users=100,
        api_keys=100,
        queries_per_day=100000,
        audit_retention_days=365,
        pii_redaction=True,
        byok=True,
        sso=True,
        budget_controls=True,
        audit_export=True,
        schema_tools=True,
    ),
}

DEFAULT_TIER = "free"


def get_limits(tier: str) -> PlanLimits:
    """Get limits for a tier, defaulting to free if unknown."""
    return PLAN_TIERS.get(tier, PLAN_TIERS[DEFAULT_TIER])


# ── Org tier resolution ──────────────────────────────────────────────────────

async def get_org_tier(org_id: str) -> str:
    """Look up the org's plan tier from the DB.

    In cloud mode, reads from the backend's `subscriptions` table (Stripe
    source of truth). In local mode, reads from `gateway_orgs`.
    Auto-creates the gateway_orgs row on first access regardless of mode
    (needed for BYOK and other gateway-specific settings).
    """
    import time
    from ..db.engine import get_session_factory
    from ..db.models import GatewayOrg
    from sqlalchemy import select, text

    if not org_id or org_id == "local":
        return DEFAULT_TIER

    try:
        factory = get_session_factory()
        async with factory() as session:
            # Ensure gateway_orgs row exists (needed for BYOK etc.)
            gw_result = await session.execute(
                select(GatewayOrg.plan_tier).where(GatewayOrg.org_id == org_id)
            )
            gw_tier = gw_result.scalar_one_or_none()

            if gw_tier is None:
                session.add(GatewayOrg(
                    org_id=org_id,
                    plan_tier=DEFAULT_TIER,
                    byok_enabled=False,
                    created_at=time.time(),
                ))
                await session.commit()
                logger.info("Auto-created gateway_orgs row for %s", org_id)

            # In cloud mode, subscriptions table is the source of truth
            if _is_cloud:
                result = await session.execute(
                    text("SELECT plan_tier FROM subscriptions WHERE org_id = :oid"),
                    {"oid": org_id},
                )
                row = result.scalar_one_or_none()
                if row:
                    return row
                # No subscription row yet — free tier
                return DEFAULT_TIER

            # Local mode: use gateway_orgs
            return gw_tier or DEFAULT_TIER
    except Exception:
        logger.warning("Failed to resolve plan tier for org %s, defaulting to free", org_id)
        return DEFAULT_TIER


async def get_org_limits(org_id: str) -> PlanLimits:
    """Resolve the org's plan tier and return its limits."""
    tier = await get_org_tier(org_id)
    return get_limits(tier)


# ── In-memory daily query counter ────────────────────────────────────────────

class DailyQueryCounter:
    """Tracks daily query counts per org in memory.

    Resets automatically when the date changes. Not persisted across restarts
    (which is fine — a restart mid-day gives users a fresh count, not a problem).
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._date: str = ""

    def _check_reset(self) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if today != self._date:
            self._counts.clear()
            self._date = today

    def increment(self, org_id: str) -> int:
        """Increment and return the new count for today."""
        self._check_reset()
        self._counts[org_id] = self._counts.get(org_id, 0) + 1
        return self._counts[org_id]

    def get_count(self, org_id: str) -> int:
        """Get current count for today."""
        self._check_reset()
        return self._counts.get(org_id, 0)

    def remaining(self, org_id: str, limit: int) -> int:
        """Get remaining queries. Returns -1 if unlimited."""
        if limit <= 0:
            return -1
        self._check_reset()
        used = self._counts.get(org_id, 0)
        return max(0, limit - used)


# Singleton
daily_query_counter = DailyQueryCounter()


# ── Enforcement helpers ──────────────────────────────────────────────────────

def check_query_limit(org_id: str, limits: PlanLimits) -> None:
    """Check if the org has exceeded its daily query limit. Raises 429 if so."""
    if limits.queries_per_day <= 0:
        return  # unlimited
    count = daily_query_counter.get_count(org_id)
    if count >= limits.queries_per_day:
        raise HTTPException(
            status_code=429,
            detail=f"Daily query limit reached ({limits.queries_per_day} queries/day on {limits.tier} plan). "
                   f"Upgrade to Pro for unlimited queries.",
        )


def record_query(org_id: str) -> None:
    """Record a query execution for rate limiting."""
    daily_query_counter.increment(org_id)


def check_connection_limit(current_count: int, limits: PlanLimits) -> None:
    """Check if org can create another connection. Raises 403 if at limit."""
    if limits.connections <= 0:
        return  # unlimited
    if current_count >= limits.connections:
        raise HTTPException(
            status_code=403,
            detail=f"Connection limit reached ({limits.connections} on {limits.tier} plan). "
                   f"Upgrade to {'Pro' if limits.tier == 'free' else 'Team'} for more connections.",
        )


def check_api_key_limit(current_count: int, limits: PlanLimits) -> None:
    """Check if org can create another API key. Raises 403 if at limit."""
    if limits.api_keys <= 0:
        return  # unlimited
    if current_count >= limits.api_keys:
        raise HTTPException(
            status_code=403,
            detail=f"API key limit reached ({limits.api_keys} on {limits.tier} plan). "
                   f"Upgrade to Pro for unlimited API keys.",
        )


def check_feature(feature_name: str, limits: PlanLimits) -> None:
    """Check if a feature is available on this plan. Raises 403 if not."""
    feature_map: dict[str, bool] = {
        "pii_redaction": limits.pii_redaction,
        "byok": limits.byok,
        "sso": limits.sso,
        "budget_controls": limits.budget_controls,
        "audit_export": limits.audit_export,
    }
    enabled = feature_map.get(feature_name)
    if enabled is None:
        return  # unknown feature, allow
    if not enabled:
        raise HTTPException(
            status_code=403,
            detail=f"{feature_name} is not available on the {limits.tier} plan. "
                   f"Upgrade to {'Pro' if limits.tier == 'free' else 'Team'} to access this feature.",
        )
