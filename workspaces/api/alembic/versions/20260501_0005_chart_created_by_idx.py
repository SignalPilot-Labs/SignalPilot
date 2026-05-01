"""chart.created_by composite index for cloud-mode ownership queries

Revision ID: 20260501_0005
Revises: 20260501_0004
Create Date: 2026-05-01

Adds:
  - Index chart_created_by_idx ON workspaces.chart (created_by, workspace_id, created_at, id)
    Covers the cloud-mode list query:
      WHERE created_by = $1 AND workspace_id = $2 ORDER BY created_at DESC, id DESC

The `chart.created_by` column already exists (added in migration 0002).
This migration adds only the composite index; no column change.

No backfill. NULL rows are local-mode by policy (NULL sentinel); cloud-mode
queries filter on Chart.created_by == user_id which naturally excludes NULLs
via SQL NULL comparison semantics.
"""

from __future__ import annotations

from alembic import op


revision = "20260501_0005"
down_revision = "20260501_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "chart_created_by_idx",
        "chart",
        ["created_by", "workspace_id", "created_at", "id"],
        schema="workspaces",
    )


def downgrade() -> None:
    op.drop_index("chart_created_by_idx", table_name="chart", schema="workspaces")
