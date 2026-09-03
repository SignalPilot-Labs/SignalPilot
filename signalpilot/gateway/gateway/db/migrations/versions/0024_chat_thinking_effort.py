"""Persist the Agent SDK thinking effort selected for a Data Chat.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gateway_chat_conversations",
        sa.Column("effort", sa.String(length=20), nullable=True),
    )
    op.execute(
        "UPDATE gateway_chat_conversations SET effort = 'medium' WHERE effort IS NULL"
    )


def downgrade() -> None:
    op.drop_column("gateway_chat_conversations", "effort")
