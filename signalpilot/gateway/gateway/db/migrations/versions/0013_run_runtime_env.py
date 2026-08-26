"""runtime_env on chat runs

Runs are stamped with the environment that created them (SP_RUNTIME_ENV) so
workers in different environments sharing one database — e.g. staging and a
local developer stack — only claim their own runs. NULL means unstamped
(legacy rows or an environment with no SP_RUNTIME_ENV); any worker may claim
those.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gateway_chat_runs",
        sa.Column("runtime_env", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gateway_chat_runs", "runtime_env")
