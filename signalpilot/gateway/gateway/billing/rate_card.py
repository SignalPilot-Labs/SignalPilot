"""The credit rate card, read from the shared database.

Pricing lives in Stripe. The backend loads the Stripe catalog and writes a
snapshot to the ``billing_rate_card`` table every few minutes; the gateway
prices its ledger entries from that row and carries no numbers of its own.
The row is cached in this process for CACHE_TTL_SECONDS, and a read failure
keeps the last good card, so metering keeps working through backend or
database hiccups. Without any card at all the emitters skip the ledger row
and log loudly: a guessed price is worse than a missing one, and the backend
reconciles from usage records.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300


class RateCardUnavailable(RuntimeError):
    """No rate card has been loaded and the database has none to offer."""


@dataclass(frozen=True)
class RateCard:
    thread_credits: int
    query_credits: int
    eval_run_credits: int
    model_month_credits: int
    token_credits_per_usd: int
    # Credits per added seat-month by tier; None when the tier has no public
    # seat price (Enterprise: seats are contracted, never metered here).
    seat_month_credits: Mapping[str, int | None]
    version: str | None = None
    loaded_at: float = 0.0

    def seat_rate(self, tier: str) -> int | None:
        return self.seat_month_credits.get(tier)


_current: RateCard | None = None
_expires_at: float = 0.0

_SQL = text("SELECT snapshot, rates_version FROM billing_rate_card WHERE id = 1")


def from_snapshot(snapshot: Mapping[str, Any], version: str | None = None) -> RateCard:
    """Build a card from the backend's ``catalog.snapshot()`` JSON."""
    rates = snapshot.get("rates") or {}
    plans = snapshot.get("plans") or {}
    required = ("thread_credits", "query_credits", "eval_run_credits", "model_month_credits", "token_credits_per_dollar")
    missing = [key for key in required if rates.get(key) is None]
    if missing:
        raise ValueError(f"rate card snapshot lacks {missing}")
    seats = {
        str(tier): (int(plan["seat_month_credits"]) if plan.get("seat_month_credits") is not None else None)
        for tier, plan in plans.items()
        if isinstance(plan, Mapping)
    }
    return RateCard(
        thread_credits=int(rates["thread_credits"]),
        query_credits=int(rates["query_credits"]),
        eval_run_credits=int(rates["eval_run_credits"]),
        model_month_credits=int(rates["model_month_credits"]),
        token_credits_per_usd=int(rates["token_credits_per_dollar"]),
        seat_month_credits=MappingProxyType(seats),
        version=version or (str(rates.get("version")) if rates.get("version") else None),
        loaded_at=float(snapshot.get("loaded_at") or 0.0),
    )


def install(card: RateCard | None, *, ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
    """Set the cached card (tests, or a caller that already has the row)."""
    global _current, _expires_at
    _current = card
    _expires_at = time.monotonic() + ttl_seconds if card is not None else 0.0


def current() -> RateCard:
    """The cached card. Raises RateCardUnavailable when nothing was ever loaded."""
    if _current is None:
        raise RateCardUnavailable("no billing rate card loaded; is the backend rate_card_sync job running?")
    return _current


def is_stale() -> bool:
    return _current is None or time.monotonic() >= _expires_at


async def refresh() -> RateCard | None:
    """Read the row from the shared database. Returns the card now in effect,
    or None when none is available. Never raises: a failed read keeps the
    previous card and logs."""
    from ..db.engine import get_session_factory

    try:
        async with get_session_factory()() as session:
            row = (await session.execute(_SQL)).mappings().first()
    except Exception as exc:
        logger.warning("billing rate card read failed (%s); keeping the cached card", exc.__class__.__name__)
        return _current
    if row is None:
        logger.warning("billing_rate_card is empty; the backend has not written a snapshot yet")
        return _current
    try:
        card = from_snapshot(row["snapshot"], row.get("rates_version"))
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning("billing rate card snapshot unusable (%s); keeping the cached card", exc)
        return _current
    install(card)
    return card


async def require() -> RateCard | None:
    """The card to price with: the cached one while fresh, else a refresh.
    None (with a warning) means "do not meter this event"."""
    if not is_stale():
        return _current
    card = await refresh()
    if card is None:
        logger.warning("no billing rate card available; usage will not be metered until one is loaded")
    return card


def seat_month_credits(tier: str) -> int | None:
    """Per-seat-month rate for a tier from the cached card; None when the
    tier has no public seat price."""
    return current().seat_rate(tier)


__all__ = [
    "CACHE_TTL_SECONDS",
    "RateCard",
    "RateCardUnavailable",
    "current",
    "from_snapshot",
    "install",
    "is_stale",
    "refresh",
    "require",
    "seat_month_credits",
]
