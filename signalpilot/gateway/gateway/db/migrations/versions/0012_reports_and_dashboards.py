"""saved reports and governed dashboards

Adds the Data Chat report and dashboard tables introduced on the reports
branch after the initial Alembic baseline was cut.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "gateway_audit_logs",
        "event_type",
        existing_type=sa.String(length=20),
        type_=sa.String(length=64),
        existing_nullable=False,
    )

    op.create_table(
        "gateway_saved_reports",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("original_conversation_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("current_version_id", sa.String(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_gw_saved_reports_owner",
        "gateway_saved_reports",
        ["org_id", "owner_user_id", "updated_at"],
    )
    op.create_index(
        "ix_gw_saved_reports_conversation",
        "gateway_saved_reports",
        ["org_id", "owner_user_id", "original_conversation_id"],
    )
    op.create_index(
        "ix_gw_saved_reports_project",
        "gateway_saved_reports",
        ["org_id", "owner_user_id", "project_id"],
    )

    op.create_table(
        "gateway_saved_report_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("report_id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_artifact_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("freshness_state", sa.String(length=30), server_default="unknown", nullable=False),
        sa.Column("freshness_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "freshness_checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("dbt_commit_sha", sa.String(length=40), nullable=True),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("retention_pinned", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_artifact_id", name="uq_gw_saved_report_version_artifact"),
        sa.UniqueConstraint(
            "org_id",
            "owner_user_id",
            "kind",
            "content_hash",
            name="uq_gw_saved_report_version_owner_content",
        ),
        sa.UniqueConstraint("report_id", "ordinal", name="uq_gw_saved_report_version_ordinal"),
    )
    op.create_index(
        "ix_gw_saved_report_versions_report",
        "gateway_saved_report_versions",
        ["report_id", "ordinal"],
    )
    op.create_index(
        "ix_gw_saved_report_versions_owner",
        "gateway_saved_report_versions",
        ["org_id", "owner_user_id", "published_at"],
    )

    op.create_table(
        "gateway_report_refreshes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("report_id", sa.String(), nullable=False),
        sa.Column("base_version_id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.String(), nullable=False),
        sa.Column("original_conversation_id", sa.String(), nullable=False),
        sa.Column("drift_state", sa.String(length=20), nullable=False),
        sa.Column("drift_json", sa.JSON(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("candidate_artifact_ids_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_gw_report_refresh_run"),
    )
    op.create_index(
        "ix_gw_report_refresh_owner",
        "gateway_report_refreshes",
        ["org_id", "owner_user_id", "report_id", "created_at"],
    )
    op.create_index(
        "ix_gw_report_refresh_status",
        "gateway_report_refreshes",
        ["status", "updated_at"],
    )

    op.create_table(
        "gateway_report_share_grants",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("report_id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "uq_gw_report_share_active_version",
        "gateway_report_share_grants",
        ["version_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_index(
        "ix_gw_report_share_lookup",
        "gateway_report_share_grants",
        ["org_id", "token_hash", "state"],
    )
    op.create_index(
        "ix_gw_report_share_owner",
        "gateway_report_share_grants",
        ["org_id", "owner_user_id", "report_id", "state"],
    )

    op.create_table(
        "gateway_report_share_access",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("grant_id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("recipient_user_id", sa.String(), nullable=False),
        sa.Column("first_opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grant_id", "recipient_user_id", name="uq_gw_report_share_access_recipient"),
    )
    op.create_index(
        "ix_gw_report_share_access_recipient",
        "gateway_report_share_access",
        ["org_id", "recipient_user_id", "last_opened_at"],
    )

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
        sa.Column("definition_json", sa.JSON(), nullable=False),
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


def downgrade() -> None:
    for table in (
        "gateway_dashboard_results",
        "gateway_dashboard_authoring_sessions",
        "gateway_dashboard_versions",
        "gateway_dashboards",
        "gateway_report_share_access",
        "gateway_report_share_grants",
        "gateway_report_refreshes",
        "gateway_saved_report_versions",
        "gateway_saved_reports",
    ):
        op.drop_table(table)
    op.alter_column(
        "gateway_audit_logs",
        "event_type",
        existing_type=sa.String(length=64),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
