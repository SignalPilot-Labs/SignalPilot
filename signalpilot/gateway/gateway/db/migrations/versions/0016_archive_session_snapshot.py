"""Structured outputs snapshot on chat runtime archives.

Adds nullable session_object_key/session_hash so the chat live notebook
panel can rehydrate the real notebook view (code + outputs) kernel-free
after the run's sandbox is gone.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gateway_chat_runtime_archives",
        sa.Column("session_object_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "gateway_chat_runtime_archives",
        sa.Column("session_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gateway_chat_runtime_archives", "session_hash")
    op.drop_column("gateway_chat_runtime_archives", "session_object_key")
