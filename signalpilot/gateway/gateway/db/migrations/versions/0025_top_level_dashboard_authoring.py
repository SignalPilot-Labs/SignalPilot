"""Persist top-level dashboard authoring revisions and tool provenance.

Revision ID: 0025
Revises: 0024
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gateway_dashboard_authoring_sessions",
        sa.Column(
            "authoring_contract_version",
            sa.String(length=40),
            server_default="2026-09-02.1",
            nullable=False,
        ),
    )
    op.add_column(
        "gateway_dashboard_authoring_sessions",
        sa.Column("plan_revision", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "gateway_dashboard_chart_drafts",
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "gateway_dashboard_chart_drafts",
        sa.Column("tool_call_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "gateway_dashboard_chart_drafts",
        sa.Column("validation_outcome_json", sa.JSON(), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("gateway_dashboard_chart_drafts", "validation_outcome_json")
    op.drop_column("gateway_dashboard_chart_drafts", "tool_call_id")
    op.drop_column("gateway_dashboard_chart_drafts", "payload_hash")
    op.drop_column("gateway_dashboard_authoring_sessions", "plan_revision")
    op.drop_column("gateway_dashboard_authoring_sessions", "authoring_contract_version")
