"""Notebook pointer on chat conversations.

A conversation has one analysis notebook. These columns record where that
notebook lives: the gateway notebook session, the kernel session inside the
runtime, and the notebook file path. The chat worker writes them when the
agent starts or recovers the notebook. The conversation notebook endpoint
reads them to attach the live view.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gateway_chat_conversations",
        sa.Column("notebook_session_id", sa.String(), nullable=True),
    )
    op.add_column(
        "gateway_chat_conversations",
        sa.Column("notebook_kernel_session_id", sa.String(), nullable=True),
    )
    op.add_column(
        "gateway_chat_conversations",
        sa.Column("notebook_path", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gateway_chat_conversations", "notebook_path")
    op.drop_column("gateway_chat_conversations", "notebook_kernel_session_id")
    op.drop_column("gateway_chat_conversations", "notebook_session_id")
