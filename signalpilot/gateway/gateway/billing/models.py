"""SQLAlchemy model for the append-only credit ledger.

The ledger is the source of truth for every credit. The gateway writes
consumption rows in the same transaction as the domain row they describe;
the backend writes grant, purchase, expire, and adjust rows. Balance is a
sum over rows, never a stored number. Rows are never updated or deleted;
corrections are ``adjust`` rows and reversals are ``return`` rows.

The constraint and index names here must match migration 0027 exactly: the
schema parity test builds this model through ``create_all`` and diffs it
against the migration chain.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models.base import GatewayBase, TZDateTime

ENTRY_TYPES: tuple[str, ...] = ("grant", "consume", "return", "purchase", "expire", "adjust")
UNITS: tuple[str, ...] = (
    "thread",
    "query",
    "model_day",
    "eval_run",
    "seat_day",
    "tokens",
    "included",
    "enterprise",
    "manual",
)
SOURCES: tuple[str, ...] = (
    "chat",
    "mcp",
    "notebook",
    "schedule",
    "eval",
    "dashboard",
    "backend",
    "staff",
    "system",
)

TABLE_COMMENT = (
    "Append-only credit ledger. 1 credit = $0.01. Balance is a sum over rows for a "
    "billing_period; rows are never updated or deleted. Gateway writes consume/return "
    "rows, backend writes grant/purchase/expire/adjust rows."
)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


ENTRY_TYPE_CHECK = f"entry_type IN ({_in_list(ENTRY_TYPES)})"
UNIT_CHECK = f"unit IN ({_in_list(UNITS)})"
SOURCE_CHECK = f"source IN ({_in_list(SOURCES)})"
CREDITS_SIGN_CHECK = (
    "(entry_type IN ('grant', 'purchase', 'return') AND credits >= 0) "
    "OR (entry_type IN ('consume', 'expire') AND credits <= 0) "
    "OR entry_type = 'adjust'"
)


class GatewayCreditLedger(GatewayBase):
    """One credit movement for an org inside one billing period."""

    __tablename__ = "gateway_credit_ledger"

    # SQLite only autoincrements INTEGER PRIMARY KEY; Postgres still gets BIGSERIAL.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    entry_type: Mapped[str] = mapped_column(Text, nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, server_default=text("0"))
    occurred_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    billing_period: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    ref_type: Mapped[str | None] = mapped_column(Text)
    ref_id: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    reverses: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("gateway_credit_ledger.id", name="fk_gw_credit_ledger_reverses"),
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    reported_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    stripe_event_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(ENTRY_TYPE_CHECK, name="ck_gw_credit_ledger_entry_type"),
        CheckConstraint(CREDITS_SIGN_CHECK, name="ck_gw_credit_ledger_credits_sign"),
        CheckConstraint(UNIT_CHECK, name="ck_gw_credit_ledger_unit"),
        CheckConstraint(SOURCE_CHECK, name="ck_gw_credit_ledger_source"),
        UniqueConstraint("idempotency_key", name="uq_gw_credit_ledger_idempotency_key"),
        Index("ix_gw_credit_ledger_org_period", "org_id", "billing_period"),
        Index("ix_gw_credit_ledger_org_period_type", "org_id", "billing_period", "entry_type"),
        Index(
            "ix_gw_credit_ledger_unreported",
            "billing_period",
            postgresql_where=text("reported_at IS NULL"),
        ),
        Index("ix_gw_credit_ledger_ref", "ref_type", "ref_id"),
        {"comment": TABLE_COMMENT},
    )


__all__ = [
    "CREDITS_SIGN_CHECK",
    "ENTRY_TYPES",
    "ENTRY_TYPE_CHECK",
    "SOURCES",
    "SOURCE_CHECK",
    "TABLE_COMMENT",
    "UNITS",
    "UNIT_CHECK",
    "GatewayCreditLedger",
]
