"""Agent pull requests + installation repository display list.

Idempotent on purpose: the shared staging database received these objects
ahead of this revision, so each step checks the catalog before creating.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


def _inspector():
    return inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _inspector().has_table(name)


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in _inspector().get_columns(table))

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade():
    if not _has_column("gateway_github_installations", "authorized_repositories"):
        op.add_column(
            "gateway_github_installations",
            sa.Column("authorized_repositories", sa.JSON(), nullable=True),
        )
    if _has_table("gateway_agent_pull_requests"):
        return
    op.create_table(
        "gateway_agent_pull_requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("repo_full_name", sa.String(500), nullable=False),
        sa.Column("source_branch", sa.String(200), nullable=False),
        sa.Column("github_branch", sa.String(200), nullable=False),
        sa.Column("base_branch", sa.String(200), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("pr_url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("export_commit_sha", sa.String(64), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("org_id", "project_id", "github_branch", name="uq_gw_agentpr_org_project_branch"),
    )
    op.create_index("ix_gw_agentpr_org_project", "gateway_agent_pull_requests", ["org_id", "project_id"])


def downgrade():
    op.drop_index("ix_gw_agentpr_org_project", table_name="gateway_agent_pull_requests")
    op.drop_table("gateway_agent_pull_requests")
    op.drop_column("gateway_github_installations", "authorized_repositories")
