"""Connectors: external MCP servers for the chat agent.

Five tables: the connector record (org or personal scope), per-member state
(switch, tool overrides, member-supplied secrets, OAuth tokens), short-lived
OAuth states, the per-org policy for personal connectors, and the proxy's
tool-call audit log. Secret material lives only in ``*_enc`` columns.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gateway_mcp_connectors",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("scope", sa.String(length=10), nullable=False),
        sa.Column("owner_user_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("transport", sa.String(length=10), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("args_json", sa.JSON(), nullable=False),
        sa.Column("env_json", sa.JSON(), nullable=False),
        sa.Column("header_names_json", sa.JSON(), nullable=False),
        sa.Column("auth", sa.String(length=10), server_default="none", nullable=False),
        sa.Column("oauth_json", sa.JSON(), nullable=True),
        sa.Column("oauth_client_secret_enc", sa.LargeBinary(), nullable=True),
        sa.Column("headers_enc", sa.LargeBinary(), nullable=True),
        sa.Column("tools_json", sa.JSON(), nullable=False),
        sa.Column("tools_hash", sa.String(length=64), nullable=True),
        sa.Column("protocol_version", sa.String(length=20), nullable=True),
        sa.Column("server_name", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gw_mcp_connectors_org", "gateway_mcp_connectors", ["org_id", "scope"])
    op.create_index(
        "uq_gw_mcp_connector_slug",
        "gateway_mcp_connectors",
        ["org_id", sa.text("coalesce(owner_user_id, '')"), "slug"],
        unique=True,
    )

    op.create_table(
        "gateway_mcp_member_state",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("connector_id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("disabled_tools_json", sa.JSON(), nullable=False),
        sa.Column("headers_enc", sa.LargeBinary(), nullable=True),
        sa.Column("env_enc", sa.LargeBinary(), nullable=True),
        sa.Column("oauth_tokens_enc", sa.LargeBinary(), nullable=True),
        sa.Column("signed_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connector_id", "user_id", name="uq_gw_mcp_member_state"),
    )
    op.create_index("ix_gw_mcp_member_state_user", "gateway_mcp_member_state", ["org_id", "user_id"])

    op.create_table(
        "gateway_mcp_oauth_states",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("connector_id", sa.String(), nullable=False),
        sa.Column("code_verifier", sa.String(length=256), nullable=False),
        sa.Column("redirect_after", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "gateway_mcp_org_policy",
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("allow_personal", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("allowed_hosts_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("org_id"),
    )

    op.create_table(
        "gateway_mcp_tool_calls",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("connector_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("tool", sa.String(length=128), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("called_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gw_mcp_tool_calls_org", "gateway_mcp_tool_calls", ["org_id", "called_at"])
    op.create_index("ix_gw_mcp_tool_calls_connector", "gateway_mcp_tool_calls", ["connector_id", "called_at"])


def downgrade() -> None:
    op.drop_index("ix_gw_mcp_tool_calls_connector", table_name="gateway_mcp_tool_calls")
    op.drop_index("ix_gw_mcp_tool_calls_org", table_name="gateway_mcp_tool_calls")
    op.drop_table("gateway_mcp_tool_calls")
    op.drop_table("gateway_mcp_org_policy")
    op.drop_table("gateway_mcp_oauth_states")
    op.drop_index("ix_gw_mcp_member_state_user", table_name="gateway_mcp_member_state")
    op.drop_table("gateway_mcp_member_state")
    op.drop_index("uq_gw_mcp_connector_slug", table_name="gateway_mcp_connectors")
    op.drop_index("ix_gw_mcp_connectors_org", table_name="gateway_mcp_connectors")
    op.drop_table("gateway_mcp_connectors")
