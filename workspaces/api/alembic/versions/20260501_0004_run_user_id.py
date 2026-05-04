"""run.user_id column + composite index for keyset pagination

Revision ID: 20260501_0004
Revises: 20260501_0003
Create Date: 2026-05-01

Adds:
  - workspaces.run.user_id text NULL
  - Index run_user_id_idx ON workspaces.run (user_id, created_at, id)
    Covers full keyset pagination on (created_at DESC, id DESC) filtered by user_id.

No backfill. NULL rows are local-mode by policy; cloud-mode queries always
filter on a non-NULL user_id (SQL NULL semantics: NULL == 'user_xyz' is NULL/false,
so NULL rows are invisible to cloud callers without explicit IS NULL).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260501_0004"
down_revision = "20260501_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "run",
        sa.Column("user_id", sa.Text(), nullable=True),
        schema="workspaces",
    )
    op.create_index(
        "run_user_id_idx",
        "run",
        ["user_id", "created_at", "id"],
        schema="workspaces",
    )


def downgrade() -> None:
    op.drop_index("run_user_id_idx", table_name="run", schema="workspaces")
    op.drop_column("run", "user_id", schema="workspaces")
