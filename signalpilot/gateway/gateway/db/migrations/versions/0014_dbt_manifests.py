"""dbt map index table

One row per (project, branch, workspace revision) compile job. Artifacts
(gzipped manifest.json + distilled graph) live in workspace S3 under the
project prefix; the unique constraint is the cross-process job-dedup claim.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gateway_dbt_manifests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("branch", sa.String(length=200), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("dbt_version", sa.String(length=40), nullable=True),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("manifest_key", sa.String(length=500), nullable=True),
        sa.Column("graph_key", sa.String(length=500), nullable=True),
        sa.Column("manifest_bytes", sa.BigInteger(), nullable=False),
        sa.Column("lease_expires_at", sa.Float(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "branch", "revision", name="uq_gw_dbtmanifest_proj_branch_rev"
        ),
    )
    op.create_index(
        "ix_gw_dbtmanifest_org_project", "gateway_dbt_manifests", ["org_id", "project_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_gw_dbtmanifest_org_project", table_name="gateway_dbt_manifests")
    op.drop_table("gateway_dbt_manifests")
