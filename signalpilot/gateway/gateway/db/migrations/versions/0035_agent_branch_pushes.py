"""Agent branch pushes: last pushed sha/time and draft flag on agent pull requests.

Chat agents push plain git to the gateway git server; each accepted push to a
``signalpilot/**`` branch is recorded on the pull request row (status
``pushed`` until a PR is opened). Idempotent on purpose: the shared staging
database may receive these columns ahead of this revision, so each step checks
the catalog before creating.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


def _inspector():
    return inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in _inspector().get_columns(table))


revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

_TABLE = "gateway_agent_pull_requests"


def upgrade():
    if not _has_column(_TABLE, "last_pushed_sha"):
        op.add_column(_TABLE, sa.Column("last_pushed_sha", sa.String(64), nullable=True))
    if not _has_column(_TABLE, "last_pushed_at"):
        op.add_column(_TABLE, sa.Column("last_pushed_at", sa.Float(), nullable=True))
    if not _has_column(_TABLE, "draft"):
        op.add_column(
            _TABLE,
            sa.Column("draft", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade():
    op.drop_column(_TABLE, "draft")
    op.drop_column(_TABLE, "last_pushed_at")
    op.drop_column(_TABLE, "last_pushed_sha")
