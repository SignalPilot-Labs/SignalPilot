"""reconcile the externally stamped 0016 revision

The staging database reports revision ``0016``, but no migration with that
identifier exists in repository history. Revision ``0015`` is already tracked
as a compatibility marker for the same externally managed migration chain.

This compatibility marker intentionally performs no DDL. It lets Alembic
resolve the database's existing revision without making assumptions about the
schema operation that originally stamped it.
"""

from __future__ import annotations

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
