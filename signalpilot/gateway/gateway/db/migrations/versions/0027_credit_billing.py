"""Credit billing: the append-only credit ledger.

One table, ``gateway_credit_ledger``. 1 credit = $0.01. The gateway writes
consume and return rows in the same transaction as the domain row; the
backend writes grant, purchase, expire and adjust rows. Balance is a sum
over rows per billing period, never a stored column.

Names here must match ``gateway/billing/models.py`` exactly; the schema
parity test diffs this chain against ``create_all``.

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

_TABLE = "gateway_credit_ledger"

_ENTRY_TYPE_CHECK = "entry_type IN ('grant', 'consume', 'return', 'purchase', 'expire', 'adjust')"
_CREDITS_SIGN_CHECK = (
    "(entry_type IN ('grant', 'purchase', 'return') AND credits >= 0) "
    "OR (entry_type IN ('consume', 'expire') AND credits <= 0) "
    "OR entry_type = 'adjust'"
)
_UNIT_CHECK = (
    "unit IN ('thread', 'query', 'model_day', 'eval_run', 'seat_day', 'tokens', 'included', 'enterprise', 'manual')"
)
_SOURCE_CHECK = "source IN ('chat', 'mcp', 'notebook', 'schedule', 'eval', 'dashboard', 'backend', 'staff', 'system')"
_COMMENT = (
    "Append-only credit ledger. 1 credit = $0.01. Balance is a sum over rows for a "
    "billing_period; rows are never updated or deleted. Gateway writes consume/return "
    "rows, backend writes grant/purchase/expire/adjust rows."
)


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("entry_type", sa.Text(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), server_default=sa.text("0"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("billing_period", sa.Date(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("ref_type", sa.Text(), nullable=True),
        sa.Column("ref_id", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("reverses", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stripe_event_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(_ENTRY_TYPE_CHECK, name="ck_gw_credit_ledger_entry_type"),
        sa.CheckConstraint(_CREDITS_SIGN_CHECK, name="ck_gw_credit_ledger_credits_sign"),
        sa.CheckConstraint(_UNIT_CHECK, name="ck_gw_credit_ledger_unit"),
        sa.CheckConstraint(_SOURCE_CHECK, name="ck_gw_credit_ledger_source"),
        sa.ForeignKeyConstraint(["reverses"], [f"{_TABLE}.id"], name="fk_gw_credit_ledger_reverses"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_gw_credit_ledger_idempotency_key"),
        comment=_COMMENT,
    )
    op.create_index("ix_gw_credit_ledger_org_period", _TABLE, ["org_id", "billing_period"])
    op.create_index("ix_gw_credit_ledger_org_period_type", _TABLE, ["org_id", "billing_period", "entry_type"])
    op.create_index(
        "ix_gw_credit_ledger_unreported",
        _TABLE,
        ["billing_period"],
        postgresql_where=sa.text("reported_at IS NULL"),
    )
    op.create_index("ix_gw_credit_ledger_ref", _TABLE, ["ref_type", "ref_id"])


def downgrade() -> None:
    op.drop_index("ix_gw_credit_ledger_ref", table_name=_TABLE)
    op.drop_index("ix_gw_credit_ledger_unreported", table_name=_TABLE)
    op.drop_index("ix_gw_credit_ledger_org_period_type", table_name=_TABLE)
    op.drop_index("ix_gw_credit_ledger_org_period", table_name=_TABLE)
    op.drop_table(_TABLE)
