"""Tableau integration: one org-scoped Tableau site + encrypted PAT.

One table, ``gateway_tableau_integrations``, at most one row per org. Chat
runs get the Tableau tools only when the row is enabled and verified.

Names here must match ``gateway/db/models/tableau.py`` exactly; the schema
parity test diffs this chain against ``create_all``. Idempotent like 0034:
the shared staging database may receive the table ahead of this revision.

Revision ID: 0038
Revises: 0037
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

_TABLE = "gateway_tableau_integrations"


def upgrade() -> None:
    if inspect(op.get_bind()).has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("server_url", sa.String(length=255), nullable=False),
        sa.Column("site_content_url", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("pat_name", sa.String(length=255), nullable=False),
        sa.Column("pat_secret_enc", sa.LargeBinary(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unknown"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("site_id", sa.String(length=64), nullable=True),
        sa.Column("user_name", sa.String(length=255), nullable=True),
        sa.Column("site_role", sa.String(length=64), nullable=True),
        sa.Column("verified_at", sa.Float(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", name="uq_gw_tableau_org"),
    )


def downgrade() -> None:
    if inspect(op.get_bind()).has_table(_TABLE):
        op.drop_table(_TABLE)
