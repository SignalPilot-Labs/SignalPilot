"""Drop the governed dashboard tables.

Revision ID: 0027
Revises: 0026

Dashboards are now plain ``artifacts/<name>.dashboard.json`` chat files
rendered client-side. The server-side authoring sessions, chart drafts,
versions, and result caches introduced by 0012, 0020, 0021, and 0025 have no
readers left, so their tables go. ``downgrade`` recreates them in their final
shape (the 0012 definitions plus the 0020, 0021, and 0025 columns).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in (
        "gateway_dashboard_results",
        "gateway_dashboard_chart_drafts",
        "gateway_dashboard_authoring_sessions",
        "gateway_dashboard_versions",
        "gateway_dashboards",
    ):
        op.drop_table(table)


def downgrade() -> None:
    op.create_table(
        "gateway_dashboards",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("connection_name", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        sa.Column("current_version_id", sa.String(), nullable=True),
        sa.Column("visibility", sa.String(length=20), server_default="private", nullable=False),
        sa.Column("parent_dashboard_id", sa.String(), nullable=True),
        sa.Column("parent_version_id", sa.String(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_gw_dashboards_private",
        "gateway_dashboards",
        ["org_id", "owner_user_id", "updated_at"],
    )
    op.create_index(
        "ix_gw_dashboards_visibility",
        "gateway_dashboards",
        ["org_id", "visibility", "updated_at"],
    )
    op.create_index(
        "ix_gw_dashboards_project",
        "gateway_dashboards",
        ["org_id", "project_id"],
    )

    op.create_table(
        "gateway_dashboard_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("dashboard_id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("semantic_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("connection_name", sa.String(length=100), nullable=False),
        sa.Column("authoring_provenance_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dashboard_id", "ordinal", name="uq_gw_dashboard_version_ordinal"),
        sa.UniqueConstraint("dashboard_id", "content_hash", name="uq_gw_dashboard_version_content"),
    )
    op.create_index(
        "ix_gw_dashboard_versions_dashboard",
        "gateway_dashboard_versions",
        ["org_id", "dashboard_id", "ordinal"],
    )

    op.create_table(
        "gateway_dashboard_authoring_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("dashboard_id", sa.String(), nullable=True),
        sa.Column("base_version_id", sa.String(), nullable=True),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("connection_name", sa.String(length=100), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("semantic_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        # 0021 relaxed definition_json to nullable.
        sa.Column("definition_json", sa.JSON(), nullable=True),
        sa.Column("operations_json", sa.JSON(), nullable=False),
        sa.Column("events_json", sa.JSON(), nullable=False),
        sa.Column("agent_runs_json", sa.JSON(), nullable=False),
        sa.Column("confirmations_json", sa.JSON(), nullable=False),
        sa.Column("pending_custom_sql_chart_ids_json", sa.JSON(), nullable=False),
        sa.Column("draft_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("agent_run_id", sa.String(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="preview", nullable=False),
        sa.Column("requires_custom_sql_confirmation", sa.Boolean(), nullable=False),
        sa.Column("custom_sql_confirmed", sa.Boolean(), nullable=False),
        sa.Column("applied_version_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
        # 0020
        sa.Column("conversation_id", sa.String(), nullable=True),
        # 0021
        sa.Column("plan_json", sa.JSON(), nullable=True),
        sa.Column("expected_chart_count", sa.Integer(), server_default="0", nullable=False),
        # 0025
        sa.Column(
            "authoring_contract_version",
            sa.String(length=40),
            server_default="2026-09-02.1",
            nullable=False,
        ),
        sa.Column("plan_revision", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_gw_dashboard_authoring_owner",
        "gateway_dashboard_authoring_sessions",
        ["org_id", "owner_user_id", "created_at"],
    )
    op.create_index(
        "ix_gw_dashboard_authoring_dashboard",
        "gateway_dashboard_authoring_sessions",
        ["org_id", "dashboard_id", "created_at"],
    )
    op.create_index(
        "ix_gw_dashboard_authoring_thread",
        "gateway_dashboard_authoring_sessions",
        ["org_id", "owner_user_id", "thread_id", "created_at"],
    )
    op.create_index(
        "ix_gw_dashboard_authoring_conversation",
        "gateway_dashboard_authoring_sessions",
        ["org_id", "owner_user_id", "conversation_id", "updated_at"],
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
        # 0025
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("tool_call_id", sa.String(length=200), nullable=True),
        sa.Column("validation_outcome_json", sa.JSON(), server_default="{}", nullable=False),
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

    op.create_table(
        "gateway_dashboard_results",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("dashboard_id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("chart_id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("execution_id", sa.String(), nullable=False),
        sa.Column("structured_result_id", sa.String(), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("sql_hash", sa.String(length=64), nullable=False),
        sa.Column("parameter_hash", sa.String(length=64), nullable=False),
        sa.Column("tables_json", sa.JSON(), nullable=False),
        sa.Column("semantic_definition_json", sa.JSON(), nullable=False),
        sa.Column("completeness", sa.String(length=20), nullable=False),
        sa.Column("freshness_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_gw_dashboard_result_cache",
        "gateway_dashboard_results",
        ["org_id", "dashboard_id", "version_id", "cache_key"],
    )
    op.create_index(
        "ix_gw_dashboard_result_access",
        "gateway_dashboard_results",
        ["org_id", "dashboard_id", "id"],
    )
