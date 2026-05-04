"""dashboards schema: chart, chart_query, chart_cache

Revision ID: 20260501_0002
Revises: 20260501_0001
Create Date: 2026-05-01

Creates:
  - workspaces.chart
  - workspaces.chart_query
  - workspaces.chart_cache
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260501_0002"
down_revision = "20260501_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS workspaces")

    op.create_table(
        "chart",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("chart_type", sa.Text(), nullable=False),
        sa.Column(
            "echarts_option",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="workspaces",
    )
    op.create_index(
        "chart_workspace_idx",
        "chart",
        ["workspace_id", sa.text("created_at DESC")],
        schema="workspaces",
    )

    op.create_table(
        "chart_query",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chart_id", sa.UUID(), nullable=False),
        sa.Column("connector_name", sa.Text(), nullable=False),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column(
            "params",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("refresh_interval_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chart_id"], ["workspaces.chart.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="workspaces",
    )
    # 1:1 enforcement for R3 — R6 will drop this for multi-query charts
    op.create_index(
        "chart_query_chart_idx",
        "chart_query",
        ["chart_id"],
        unique=True,
        schema="workspaces",
    )

    op.create_table(
        "chart_cache",
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("query_id", sa.UUID(), nullable=False),
        sa.Column(
            "result_json",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["query_id"], ["workspaces.chart_query.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("cache_key"),
        schema="workspaces",
    )
    op.create_index(
        "chart_cache_expires_idx",
        "chart_cache",
        ["expires_at"],
        schema="workspaces",
    )


def downgrade() -> None:
    op.drop_table("chart_cache", schema="workspaces")
    op.drop_table("chart_query", schema="workspaces")
    op.drop_table("chart", schema="workspaces")
