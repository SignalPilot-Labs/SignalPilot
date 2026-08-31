"""Conversation-scoped chat files.

The chat agent writes files (specs, scripts, html, images) during a run.
The gateway mirrors them to object storage and records one row per
conversation-relative path here. The newest write wins; the unique
constraint on (conversation_id, path) enforces that.

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
    op.create_table(
        "gateway_chat_files",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("origin_run_id", sa.String(), nullable=True),
        sa.Column("origin", sa.String(length=20), server_default="mirror", nullable=False),
        sa.Column("status", sa.String(length=10), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "path", name="uq_gw_chat_file_conv_path"),
    )
    op.create_index(
        "ix_gw_chat_file_owner",
        "gateway_chat_files",
        ["org_id", "user_id", "conversation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_gw_chat_file_owner", table_name="gateway_chat_files")
    op.drop_table("gateway_chat_files")
