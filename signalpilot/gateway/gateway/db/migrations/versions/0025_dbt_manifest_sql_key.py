"""Store the per-compile SQL artifact key on dbt map rows.

Revision ID: 0025
Revises: 0024
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gateway_dbt_manifests",
        sa.Column("sql_key", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gateway_dbt_manifests", "sql_key")
