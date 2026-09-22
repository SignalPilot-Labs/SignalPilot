"""Billing-period helpers and the daily share carry.

Credit rates and plan allowances are not here. Pricing lives in Stripe; the
backend writes a snapshot of it to the shared ``billing_rate_card`` table and
``gateway.billing.rate_card`` reads it. Plan allowances arrive on each org's
``subscriptions`` row (``gateway.billing.entitlements``). This module keeps
only what a pricing change never touches: the tier set, the grace window and
the calendar arithmetic. Periods are UTC calendar months; ``billing_period``
on a ledger row is the first day of the month the entry belongs to.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime
from typing import Final

GRACE_DAYS: Final[int] = 14

BILLABLE_TIERS: Final[frozenset[str]] = frozenset({"team", "scale", "enterprise"})


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
    "GRACE_DAYS",
    "current_period",
    "daily_credit_share",
    "days_in_period",
    "period_end",
    "period_of",
]
