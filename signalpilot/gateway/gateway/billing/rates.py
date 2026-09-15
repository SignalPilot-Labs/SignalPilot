"""Fixed credit rates, plan allowances, and billing-period helpers.

1 credit = $0.01, integers only. There are no volume brackets. Every rate
here is the single source for the gateway emitters; the landing page and the
backend Stripe catalog carry the same numbers and are checked against them.

Periods are UTC calendar months. ``billing_period`` on a ledger row is the
first day of the month the entry belongs to.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Final

# Per-use rates (credits).
THREAD_CREDITS: Final[int] = 50
QUERY_CREDITS: Final[int] = 1
EVAL_RUN_CREDITS: Final[int] = 50

# Allowance items beyond their allowance (credits per unit-month, metered daily).
MODEL_MONTH_CREDITS: Final[int] = 600
SEAT_MONTH_CREDITS: Final[int] = 1_000
ENTERPRISE_SEAT_MONTH_CREDITS: Final[int] = 1_500

# Model tokens on a platform-held key: provider cost in USD x 100, per run.
TOKEN_CREDITS_PER_USD: Final[int] = 100

# past_due orgs keep their entitlement for this long after the period end.
GRACE_DAYS: Final[int] = 14

RATES: Final = MappingProxyType(
    {
        "thread": THREAD_CREDITS,
        "query": QUERY_CREDITS,
        "eval_run": EVAL_RUN_CREDITS,
        "model_month": MODEL_MONTH_CREDITS,
        "seat_month": SEAT_MONTH_CREDITS,
        "enterprise_seat_month": ENTERPRISE_SEAT_MONTH_CREDITS,
        "token_credits_per_usd": TOKEN_CREDITS_PER_USD,
    }
)

# Included allowances per tier. ``credits`` is the monthly included credit
# block; the other three are their own per-period counters and never pool
# with credits. Enterprise rows may carry larger values on the entitlement
# row; these are the defaults a fresh enterprise subscription starts with.
PLAN_ALLOWANCES: Final = MappingProxyType(
    {
        "free": MappingProxyType({"seats": 0, "models": 0, "eval_runs": 0, "credits": 0}),
        "team": MappingProxyType({"seats": 10, "models": 30, "eval_runs": 30, "credits": 5_000}),
        "scale": MappingProxyType({"seats": 25, "models": 50, "eval_runs": 30, "credits": 12_500}),
        "enterprise": MappingProxyType({"seats": 100, "models": 100, "eval_runs": 30, "credits": 75_000}),
    }
)

BILLABLE_TIERS: Final[frozenset[str]] = frozenset({"team", "scale", "enterprise"})


def seat_month_credits(tier: str) -> int:
    """Return the per-seat-month rate for a tier (Enterprise is priced higher)."""
    return ENTERPRISE_SEAT_MONTH_CREDITS if tier == "enterprise" else SEAT_MONTH_CREDITS


def period_of(dt: datetime | date) -> date:
    """Return the billing period (first day of the UTC month) that ``dt`` falls in.

    Naive datetimes are treated as UTC. Aware datetimes are converted to UTC
    first, so a timestamp late on the last day of a month in a western zone
    still lands in the following period when it is already next month in UTC.
    """
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            dt = dt.astimezone(UTC)
        return date(dt.year, dt.month, 1)
    return date(dt.year, dt.month, 1)


def current_period(now: datetime | None = None) -> date:
    """Return the period for ``now`` (default: the current UTC time)."""
    return period_of(now or datetime.now(UTC))


def days_in_period(period: date) -> int:
    """Return the number of days in the month that ``period`` starts."""
    return calendar.monthrange(period.year, period.month)[1]


def period_end(period: date) -> date:
    """Return the first day of the period after ``period``."""
    if period.month == 12:
        return date(period.year + 1, 1, 1)
    return date(period.year, period.month + 1, 1)


def daily_credit_share(monthly_credits: int, day: date) -> int:
    """Return the credits to deduct on ``day`` for one unit-month rate.

    The month rate is spread over the days of the month with the rounding
    remainder carried forward, so the daily rows of a full month sum to
    exactly ``monthly_credits``. Day ``d`` gets
    ``round(rate * d / days) - round(rate * (d - 1) / days)``.
    """
    days = days_in_period(period_of(day))
    d = day.day
    return _cumulative(monthly_credits, d, days) - _cumulative(monthly_credits, d - 1, days)


def _cumulative(rate: int, day_index: int, days: int) -> int:
    # Integer round-half-up of rate * day_index / days.
    return (2 * rate * day_index + days) // (2 * days)


__all__ = [
    "BILLABLE_TIERS",
    "ENTERPRISE_SEAT_MONTH_CREDITS",
    "EVAL_RUN_CREDITS",
    "GRACE_DAYS",
    "MODEL_MONTH_CREDITS",
    "PLAN_ALLOWANCES",
    "QUERY_CREDITS",
    "RATES",
    "SEAT_MONTH_CREDITS",
    "THREAD_CREDITS",
    "TOKEN_CREDITS_PER_USD",
    "current_period",
    "daily_credit_share",
    "days_in_period",
    "period_end",
    "period_of",
    "seat_month_credits",
]
