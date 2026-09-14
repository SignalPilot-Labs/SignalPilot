"""Write and summarise credit ledger rows.

``write_entry`` takes the caller's async session so the ledger row lands in
the same transaction as the domain row it describes. It is idempotent: a
second write with the same ``idempotency_key`` returns None and changes
nothing. ``period_summary`` is one SQL aggregate over an org's period.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ENTRY_TYPES, SOURCES, UNITS, GatewayCreditLedger
from .rates import period_of

logger = logging.getLogger(__name__)

_NON_NEGATIVE_TYPES = frozenset({"grant", "purchase", "return"})
_NON_POSITIVE_TYPES = frozenset({"consume", "expire"})


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One row to append. ``occurred_at`` defaults to now (UTC); ``billing_period`` to its month."""

    org_id: str
    entry_type: str
    credits: int
    unit: str
    reason: str
    source: str
    idempotency_key: str
    quantity: Decimal | int | float = 0
    occurred_at: datetime | None = None
    billing_period: date | None = None
    ref_type: str | None = None
    ref_id: str | None = None
    user_id: str | None = None
    payload: dict[str, Any] | None = field(default=None)
    reverses: int | None = None

    def validate(self) -> None:
        """Raise ValueError when the row would violate a CHECK constraint."""
        if self.entry_type not in ENTRY_TYPES:
            raise ValueError(f"invalid entry_type {self.entry_type!r}")
        if self.unit not in UNITS:
            raise ValueError(f"invalid unit {self.unit!r}")
        if self.source not in SOURCES:
            raise ValueError(f"invalid source {self.source!r}")
        if not isinstance(self.credits, int) or isinstance(self.credits, bool):
            raise ValueError("credits must be an integer")
        if self.entry_type in _NON_NEGATIVE_TYPES and self.credits < 0:
            raise ValueError(f"{self.entry_type} rows must have credits >= 0")
        if self.entry_type in _NON_POSITIVE_TYPES and self.credits > 0:
            raise ValueError(f"{self.entry_type} rows must have credits <= 0")
        if not self.org_id or not self.idempotency_key or not self.reason:
            raise ValueError("org_id, idempotency_key and reason are required")

    def to_row(self) -> dict[str, Any]:
        """Return the column values, filling the time defaults."""
        occurred_at = self.occurred_at or datetime.now(UTC)
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        return {
            "org_id": self.org_id,
            "entry_type": self.entry_type,
            "credits": self.credits,
            "unit": self.unit,
            "quantity": Decimal(str(self.quantity)),
            "occurred_at": occurred_at,
            "billing_period": self.billing_period or period_of(occurred_at),
            "source": self.source,
            "ref_type": self.ref_type,
            "ref_id": self.ref_id,
            "user_id": self.user_id,
            "reason": self.reason,
            "payload": self.payload,
            "reverses": self.reverses,
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True, slots=True)
class CreditSummary:
    """Credit position of one org in one period. All values are non-negative except ``adjusted``."""

    org_id: str
    period: date
    granted: int
    purchased: int
    consumed: int
    returned: int
    expired: int
    adjusted: int
    available: int
    overage: int

    @property
    def credited(self) -> int:
        """Credits put in: grants + purchases + returns + signed adjustments."""
        return self.granted + self.purchased + self.returned + self.adjusted


def _insert_factory(session: AsyncSession):
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert

        return insert
    from sqlalchemy.dialects.postgresql import insert

    return insert


async def write_entry(session: AsyncSession, entry: LedgerEntry) -> int | None:
    """Append ``entry`` in the caller's transaction; return its id, or None on a duplicate key.

    Uses ``INSERT ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING id``
    so a replayed emission is a no-op without an exception. The caller owns
    commit and rollback.
    """
    entry.validate()
    insert = _insert_factory(session)
    stmt = (
        insert(GatewayCreditLedger)
        .values(**entry.to_row())
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(GatewayCreditLedger.id)
    )
    result = await session.execute(stmt)
    new_id = result.scalar_one_or_none()
    if new_id is None:
        logger.debug("credit ledger duplicate ignored: %s", entry.idempotency_key)
    return new_id


def _sum_where(entry_type: str, sign: int = 1):
    column = GatewayCreditLedger.credits * sign if sign != 1 else GatewayCreditLedger.credits
    return func.coalesce(func.sum(case((GatewayCreditLedger.entry_type == entry_type, column), else_=0)), 0)


async def period_summary(session: AsyncSession, org_id: str, period: date) -> CreditSummary:
    """Return the org's credit position for ``period`` from one aggregate query.

    available = granted + purchased + returned + adjusted - consumed - expired
    overage   = max(0, consumed - (granted + purchased + returned + adjusted))

    Expiry is excluded from overage: an ``expire`` row zeroes the unused
    included block at period close and never creates a charge.
    """
    period = period_of(period)
    stmt = select(
        _sum_where("grant").label("granted"),
        _sum_where("purchase").label("purchased"),
        _sum_where("consume", -1).label("consumed"),
        _sum_where("return").label("returned"),
        _sum_where("expire", -1).label("expired"),
        _sum_where("adjust").label("adjusted"),
    ).where(GatewayCreditLedger.org_id == org_id, GatewayCreditLedger.billing_period == period)
    row = (await session.execute(stmt)).one()
    granted, purchased, consumed, returned, expired, adjusted = (int(value) for value in row)
    credited = granted + purchased + returned + adjusted
    return CreditSummary(
        org_id=org_id,
        period=period,
        granted=granted,
        purchased=purchased,
        consumed=consumed,
        returned=returned,
        expired=expired,
        adjusted=adjusted,
        available=credited - consumed - expired,
        overage=max(0, consumed - credited),
    )


async def unit_quantity(session: AsyncSession, org_id: str, period: date, unit: str) -> Decimal:
    """Return the summed ``quantity`` of one unit in a period (allowance position, e.g. eval runs so far)."""
    stmt = select(func.coalesce(func.sum(GatewayCreditLedger.quantity), 0)).where(
        GatewayCreditLedger.org_id == org_id,
        GatewayCreditLedger.billing_period == period_of(period),
        GatewayCreditLedger.unit == unit,
        GatewayCreditLedger.entry_type == "consume",
    )
    value = (await session.execute(stmt)).scalar_one()
    return Decimal(str(value))


async def has_entry(session: AsyncSession, idempotency_key: str) -> bool:
    """Return True when a row with ``idempotency_key`` already exists."""
    stmt = select(GatewayCreditLedger.id).where(GatewayCreditLedger.idempotency_key == idempotency_key)
    return (await session.execute(stmt)).scalar_one_or_none() is not None


__all__ = [
    "CreditSummary",
    "LedgerEntry",
    "has_entry",
    "period_summary",
    "unit_quantity",
    "write_entry",
]
