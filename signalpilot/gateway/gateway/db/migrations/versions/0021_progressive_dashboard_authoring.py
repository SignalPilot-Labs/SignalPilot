"""Persist progressive dashboard plans and independently validated charts.

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
    op.alter_column(
        "gateway_dashboard_authoring_sessions",
        "definition_json",
        existing_type=sa.JSON(),
        nullable=True,
    )
    op.add_column(
        "gateway_dashboard_authoring_sessions",
        sa.Column("plan_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "gateway_dashboard_authoring_sessions",
        sa.Column("expected_chart_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "gateway_dashboard_chart_drafts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("chart_id", sa.String(length=200), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("intent_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=True),
        sa.Column("safe_error", sa.Text(), nullable=True),
        sa.Column("model_usage_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["gateway_dashboard_authoring_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("session_id", "chart_id", name="uq_gw_dashboard_chart_draft"),
        sa.UniqueConstraint("session_id", "ordinal", name="uq_gw_dashboard_chart_ordinal"),
    )
    op.create_index(
        "ix_gw_dashboard_chart_drafts_session",
        "gateway_dashboard_chart_drafts",
        ["session_id", "ordinal"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gw_dashboard_chart_drafts_session",
        table_name="gateway_dashboard_chart_drafts",
    )
    op.drop_table("gateway_dashboard_chart_drafts")
    op.drop_column("gateway_dashboard_authoring_sessions", "expected_chart_count")
    op.drop_column("gateway_dashboard_authoring_sessions", "plan_json")
    op.execute(
        sa.text(
            "UPDATE gateway_dashboard_authoring_sessions SET definition_json = '{}'::json WHERE definition_json IS NULL"
        )
    )
    op.alter_column(
        "gateway_dashboard_authoring_sessions",
        "definition_json",
        existing_type=sa.JSON(),
        nullable=False,
    )
