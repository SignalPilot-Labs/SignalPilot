"""dbt map compile visibility: record which dbt directory a compile built and
the phase a running compile is in, so the settings page can show progress
instead of a static "running" label. Idempotent like 0036: the shared staging
database may already carry the columns.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspect(op.get_bind()).get_columns(table))


revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

_TABLE = "gateway_dbt_manifests"


def upgrade():
    if not _has_column(_TABLE, "dbt_project_dir"):
        op.add_column(_TABLE, sa.Column("dbt_project_dir", sa.String(500), nullable=True))
    if not _has_column(_TABLE, "phase"):
        op.add_column(_TABLE, sa.Column("phase", sa.String(40), nullable=True))


def downgrade():
    if _has_column(_TABLE, "phase"):
        op.drop_column(_TABLE, "phase")
    if _has_column(_TABLE, "dbt_project_dir"):
        op.drop_column(_TABLE, "dbt_project_dir")
