"""Attach dashboard authoring drafts to standalone Data Chat conversations.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gateway_dashboard_authoring_sessions",
        sa.Column("conversation_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_gw_dashboard_authoring_conversation",
        "gateway_dashboard_authoring_sessions",
        ["org_id", "owner_user_id", "conversation_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gw_dashboard_authoring_conversation",
        table_name="gateway_dashboard_authoring_sessions",
    )
    op.drop_column("gateway_dashboard_authoring_sessions", "conversation_id")
