"""Store the per-compile SQL artifact key on dbt map rows.

Revision ID: 0026
Revises: 0025

Idempotent on purpose. This revision was first written as 0025 in parallel
with the dashboard authoring 0025, and the shared staging database received
the column under that number. Both paths converge here.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

_TABLE = "gateway_dbt_manifests"
_COLUMN = "sql_key"


def _column_exists() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == _COLUMN for column in inspector.get_columns(_TABLE))


def upgrade() -> None:
    if _column_exists():
        return
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=500), nullable=True))


def downgrade() -> None:
    if not _column_exists():
        return
    op.drop_column(_TABLE, _COLUMN)
