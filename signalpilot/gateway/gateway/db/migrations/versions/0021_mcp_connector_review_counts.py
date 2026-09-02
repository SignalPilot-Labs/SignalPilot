"""Connectors: review counters and the signed-in account label.

``gateway_mcp_connectors.tools_added`` / ``tools_removed`` count the tools a
refresh added or dropped since the inventory was last reviewed (PUT /tools
resets them). ``gateway_mcp_member_state.account_label`` is the best-effort
display identity of the signed-in account, taken from the provider's
``id_token``; it carries no authority and is cleared on sign-out.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gateway_mcp_connectors",
        sa.Column("tools_added", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "gateway_mcp_connectors",
        sa.Column("tools_removed", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "gateway_mcp_member_state",
        sa.Column("account_label", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gateway_mcp_member_state", "account_label")
    op.drop_column("gateway_mcp_connectors", "tools_removed")
    op.drop_column("gateway_mcp_connectors", "tools_added")
