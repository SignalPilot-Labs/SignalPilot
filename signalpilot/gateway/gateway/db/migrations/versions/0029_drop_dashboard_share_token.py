"""Drop the dashboard share token: dashboards are private or org only.

Revision ID: 0029
Revises: 0028

Public share links were removed from the product. The ``link`` visibility,
its ``share_token`` column, and the unique constraint on it go away. Any row
still marked ``link`` becomes ``org`` so it stays visible to the team that
could already open it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE gateway_published_dashboards SET visibility = 'org' WHERE visibility = 'link'")
    op.drop_constraint("uq_gw_pubdash_share_token", "gateway_published_dashboards", type_="unique")
    op.drop_column("gateway_published_dashboards", "share_token")


def downgrade() -> None:
    op.add_column("gateway_published_dashboards", sa.Column("share_token", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_gw_pubdash_share_token", "gateway_published_dashboards", ["share_token"])
