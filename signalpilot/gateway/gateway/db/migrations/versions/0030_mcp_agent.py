"""Durable cloud MCP agent threads and safe events."""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "gateway_mcp_agent_threads",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("runtime_env", sa.String(50), nullable=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("lease_expires_at", sa.Float(), nullable=False, server_default="0"),
        sa.Column("enqueued_at", sa.Float(), nullable=False, server_default="0"),
        sa.Column("event_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retained_until", sa.Float(), nullable=False),
        sa.Column("client_request_id", sa.String(128), nullable=True),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("snapshot_key", sa.String(), nullable=False),
        sa.UniqueConstraint("org_id", "user_id", "client_request_id", name="uq_mcp_agent_request"),
    )
    op.create_index("ix_mcp_agent_owner", "gateway_mcp_agent_threads", ["org_id", "user_id"])
    op.create_table(
        "gateway_mcp_agent_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_mcp_agent_events_run", "gateway_mcp_agent_events", ["org_id", "run_id", "sequence"], unique=True
    )


def downgrade():
    op.drop_table("gateway_mcp_agent_events")
    op.drop_table("gateway_mcp_agent_threads")
