"""Quantitative abuse ceilings, read from the org's entitlement.

These are not plan features. Seats, models, eval runs and queries are metered
and billed; the numbers here exist only so a runaway client cannot create an
unbounded number of connections or API keys, or fill the knowledge store.
They sit well above anything a plan meters.

    billable (team / scale / enterprise): 100 connections, 100 keys,
                                          500 MiB knowledge, 50 history versions
    free:                                 3 connections, 1 key,
                                          25 MiB knowledge, 5 history versions
    unlimited (local mode):               no ceilings (0 = unlimited)
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from gateway.billing.entitlements import LOCAL_TIER, OrgEntitlement, get_entitlement


@dataclass(frozen=True, slots=True)
class OrgLimits:
    """Ceilings for one org. Zero means unlimited."""

    tier: str
    is_billable: bool
    connections: int
    api_keys: int
    knowledge_storage_mb: int
    knowledge_history_versions: int


def limits_for(entitlement: OrgEntitlement) -> OrgLimits:
    """Map an entitlement onto its ceilings."""
    if entitlement.tier == LOCAL_TIER:
        return OrgLimits(
            tier=entitlement.tier,
            is_billable=True,
            connections=0,
            api_keys=0,
            knowledge_storage_mb=0,
            knowledge_history_versions=0,
        )
    if entitlement.is_billable:
        return OrgLimits(
            tier=entitlement.tier,
            is_billable=True,
            connections=100,
            api_keys=100,
            knowledge_storage_mb=500,
            knowledge_history_versions=50,
        )
    return OrgLimits(
        tier=entitlement.tier,
        is_billable=False,
        connections=3,
        api_keys=1,
        knowledge_storage_mb=25,
        knowledge_history_versions=5,
    )


async def get_org_limits(org_id: str) -> OrgLimits:
    """Resolve the org's entitlement and return its ceilings."""
    from gateway.store.orgs import ensure_gateway_org

    entitlement = await get_entitlement(org_id)
    await ensure_gateway_org(org_id)
    return limits_for(entitlement)


def _limit_detail(what: str, limit: int, limits: OrgLimits) -> dict[str, object]:
    return {
        "error": "limit_reached",
        "resource": what,
        "limit": limit,
        "tier": limits.tier,
        "message": (
            f"{what.replace('_', ' ').capitalize()} limit reached ({limit} on the {limits.tier} plan)."
            + ("" if limits.is_billable else " Choose a plan to raise this limit.")
        ),
    }


def check_connection_limit(current_count: int, limits: OrgLimits) -> None:
    """Raise 403 when the org cannot create another connection."""
    if limits.connections > 0 and current_count >= limits.connections:
        raise HTTPException(status_code=403, detail=_limit_detail("connections", limits.connections, limits))


def check_api_key_limit(current_count: int, limits: OrgLimits) -> None:
    """Raise 403 when the org cannot create another API key."""
    if limits.api_keys > 0 and current_count >= limits.api_keys:
        raise HTTPException(status_code=403, detail=_limit_detail("api_keys", limits.api_keys, limits))


__all__ = [
    "OrgLimits",
    "check_api_key_limit",
    "check_connection_limit",
    "get_org_limits",
    "limits_for",
]
