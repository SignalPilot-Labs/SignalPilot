"""Published dashboards: team gallery, immutable versions, refreshes.

Revision ID: 0028
Revises: 0027

A chat writes ``artifacts/<name>.dashboard.json``. Publishing copies the spec
and dataset bytes into dashboard-owned object keys and creates a published
dashboard with version 1. Every refresh or restore adds a version;
``current_version_id`` names the live one. The FK from a dashboard to its
current version is added after both tables exist because the two reference
each other.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gateway_published_dashboards",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(length=10), server_default="private", nullable=False),
        sa.Column("share_token", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.String(), nullable=False),
        sa.Column("source_conversation_id", sa.String(), nullable=True),
        sa.Column("source_file_id", sa.String(), nullable=True),
        sa.Column("current_version_id", sa.String(), nullable=True),
        sa.Column("refresh_interval_minutes", sa.Integer(), nullable=True),
        sa.Column("refresh_anchor_time", sa.String(length=5), nullable=True),
        sa.Column("refresh_timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("refresh_mode", sa.String(length=10), server_default="sql", nullable=False),
        sa.Column("notify_on_failure", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("next_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_status", sa.String(length=10), nullable=True),
        sa.Column("chart_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "slug", name="uq_gw_pubdash_org_slug"),
        sa.UniqueConstraint("share_token", name="uq_gw_pubdash_share_token"),
    )
    op.create_index("ix_gw_pubdash_org", "gateway_published_dashboards", ["org_id"])
    op.create_index("ix_gw_pubdash_due", "gateway_published_dashboards", ["next_refresh_at"])

    op.create_table(
        "gateway_published_dashboard_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("dashboard_id", sa.String(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("spec_key", sa.Text(), nullable=False),
        sa.Column("dataset_keys", sa.JSON(), nullable=False),
        sa.Column("dataset_meta", sa.JSON(), nullable=False),
        sa.Column("chart_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("produced_by", sa.String(length=10), nullable=False),
        sa.Column("producer_ref", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["dashboard_id"],
            ["gateway_published_dashboards.id"],
            name="fk_gw_pubdash_version_dashboard",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("dashboard_id", "version_no", name="uq_gw_pubdash_version_no"),
    )

    op.create_foreign_key(
        "fk_gw_pubdash_current_version",
        "gateway_published_dashboards",
        "gateway_published_dashboard_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "gateway_dashboard_refreshes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("dashboard_id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("trigger", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="queued", nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["dashboard_id"],
            ["gateway_published_dashboards.id"],
            name="fk_gw_pubdash_refresh_dashboard",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_gw_pubdash_refresh_dashboard",
        "gateway_dashboard_refreshes",
        ["dashboard_id", "created_at"],
    )
    op.create_index("ix_gw_pubdash_refresh_org", "gateway_dashboard_refreshes", ["org_id"])
    op.create_index("ix_gw_pubdash_refresh_status", "gateway_dashboard_refreshes", ["mode", "status"])


def downgrade() -> None:
    op.drop_index("ix_gw_pubdash_refresh_status", table_name="gateway_dashboard_refreshes")
    op.drop_index("ix_gw_pubdash_refresh_org", table_name="gateway_dashboard_refreshes")
    op.drop_index("ix_gw_pubdash_refresh_dashboard", table_name="gateway_dashboard_refreshes")
    op.drop_table("gateway_dashboard_refreshes")
    op.drop_constraint("fk_gw_pubdash_current_version", "gateway_published_dashboards", type_="foreignkey")
    op.drop_table("gateway_published_dashboard_versions")
    op.drop_index("ix_gw_pubdash_due", table_name="gateway_published_dashboards")
    op.drop_index("ix_gw_pubdash_org", table_name="gateway_published_dashboards")
    op.drop_table("gateway_published_dashboards")
