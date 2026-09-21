"""Credit billing core: ledger, entitlements, the rate card, and service identity.

See ``sp-local/writeups/credit-billing-implementation-brief.md`` for the
contracts. Emitters (one module per metered unit) live in ``emitters/``.
"""

from __future__ import annotations

from .entitlements import (
    OrgEntitlement,
    entitlement_from_row,
    free_entitlement,
    get_entitlement,
    invalidate,
    is_cloud_mode,
    local_entitlement,
    normalize_tier,
)
from .identity import is_service_identity, is_service_user_id, service_identity
from .ledger import CreditSummary, LedgerEntry, has_entry, period_summary, unit_quantity, write_entry
from .models import ENTRY_TYPES, SOURCES, UNITS, GatewayCreditLedger
from .rate_card import RateCard, RateCardUnavailable
from .rates import (
    BILLABLE_TIERS,
    GRACE_DAYS,
    current_period,
    daily_credit_share,
    days_in_period,
    period_end,
    period_of,
)

__all__ = [
    "BILLABLE_TIERS",
    "ENTRY_TYPES",
    "GRACE_DAYS",
    "SOURCES",
    "UNITS",
    "CreditSummary",
    "GatewayCreditLedger",
    "LedgerEntry",
    "OrgEntitlement",
    "RateCard",
    "RateCardUnavailable",
    "current_period",
    "daily_credit_share",
    "days_in_period",
    "entitlement_from_row",
    "free_entitlement",
    "get_entitlement",
    "has_entry",
    "invalidate",
    "is_cloud_mode",
    "is_service_identity",
    "is_service_user_id",
    "local_entitlement",
    "normalize_tier",
    "period_end",
    "period_of",
    "period_summary",
    "service_identity",
    "unit_quantity",
    "write_entry",
]
