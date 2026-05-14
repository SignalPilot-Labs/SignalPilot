"""workspaces initial schema

Revision ID: 20260501_0001
Revises:
Create Date: 2026-05-01

Creates:
  - workspaces schema (idempotent)
  - workspaces.run
  - workspaces.run_event
  - workspaces.approval
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260501_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS workspaces")

    op.create_table(
        "run",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("inference_mode", sa.Text(), nullable=False),
        sa.Column("dbt_proxy_host_port", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="workspaces",
    )
    op.create_index(
        "run_workspace_idx",
        "run",
        ["workspace_id", sa.text("created_at DESC")],
        schema="workspaces",
    )
    op.create_index(
        "run_state_idx",
        "run",
        ["state"],
        schema="workspaces",
    )

    op.create_table(
        "run_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["workspaces.run.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="workspaces",
    )
    op.create_index(
        "run_event_run_idx",
        "run_event",
        ["run_id", "id"],
        schema="workspaces",
    )

    op.create_table(
        "approval",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column(
            "tool_input",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["workspaces.run.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="workspaces",
    )
    op.create_index(
        "approval_run_idx",
        "approval",
        ["run_id"],
        schema="workspaces",
    )


def downgrade() -> None:
    op.drop_table("approval", schema="workspaces")
    op.drop_table("run_event", schema="workspaces")
    op.drop_table("run", schema="workspaces")
    op.execute("DROP SCHEMA workspaces")
