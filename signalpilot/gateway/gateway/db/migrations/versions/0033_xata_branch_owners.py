"""Xata branch owners: who created a branch through the gateway.

One table, ``gateway_xata_branch_owners``, one row per branch created by
``POST /api/connections/{name}/xata/projects/{project}/branches``. The
delete route reads it to apply the creator-or-admin rule.

Names here must match ``gateway/db/models/xata.py`` exactly; the schema
parity test diffs this chain against ``create_all``.

Revision ID: 0033
Revises: 0032
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

_TABLE = "gateway_xata_branch_owners"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("connection_name", sa.String(length=64), nullable=False),
        sa.Column("project", sa.String(length=64), nullable=False),
        sa.Column("branch", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "connection_name", "project", "branch", name="uq_gw_xata_branch_owner"),
    )
    op.create_index("ix_gw_xata_branch_owners_org", _TABLE, ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_gw_xata_branch_owners_org", table_name=_TABLE)
    op.drop_table(_TABLE)
