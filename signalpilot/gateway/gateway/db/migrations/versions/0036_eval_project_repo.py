"""Eval project repository: bind the dbt project an eval set runs against to the config.

The dbt project no longer comes from the eval.json manifest. The eval
configuration links a repository (and an optional branch) the same way it
links the eval repository. Idempotent on purpose: the shared staging
database may receive these columns ahead of this revision, so each step
checks the catalog before creating.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


def _inspector():
    return inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in _inspector().get_columns(table))


revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

_TABLE = "gateway_eval_configs"


def upgrade():
    if not _has_column(_TABLE, "project_repo_url"):
        op.add_column(
            _TABLE,
            sa.Column("project_repo_url", sa.String(2048), nullable=False, server_default=""),
        )
    if not _has_column(_TABLE, "project_repo_installation_id"):
        op.add_column(_TABLE, sa.Column("project_repo_installation_id", sa.String(64), nullable=True))
    if not _has_column(_TABLE, "project_repo_id"):
        op.add_column(_TABLE, sa.Column("project_repo_id", sa.BigInteger(), nullable=True))
    if not _has_column(_TABLE, "project_ref"):
        op.add_column(
            _TABLE,
            sa.Column("project_ref", sa.String(200), nullable=False, server_default=""),
        )


def downgrade():
    op.drop_column(_TABLE, "project_ref")
    op.drop_column(_TABLE, "project_repo_id")
    op.drop_column(_TABLE, "project_repo_installation_id")
    op.drop_column(_TABLE, "project_repo_url")
