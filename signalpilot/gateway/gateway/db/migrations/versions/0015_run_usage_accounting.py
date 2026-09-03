"""cost and token usage accounting on chat runs

Each run stores the agent SDK's reported total cost (USD) and the aggregate
token usage dict from the result message. Operator-facing only — the chat UX
never reads these columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gateway_chat_runs",
        sa.Column("cost_usd", sa.Float(), nullable=True),
    )
    op.add_column(
        "gateway_chat_runs",
        sa.Column("usage_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gateway_chat_runs", "usage_json")
    op.drop_column("gateway_chat_runs", "cost_usd")
