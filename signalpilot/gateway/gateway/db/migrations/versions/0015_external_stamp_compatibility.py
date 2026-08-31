"""reconcile the externally stamped 0015 revision

The shared staging database was stamped at revision ``0015`` by an image or
manual operation whose migration files never entered repository history. The
tracked migration chain ends at ``0013``; the only known ``0014`` belongs to an
unmerged feature and was not part of the deployed application schema.

This compatibility marker intentionally performs no DDL. Its exact revision ID
allows Alembic-managed processes to resolve the existing database state and
keeps future migrations anchored to tracked history again.
"""

from __future__ import annotations

revision = "0015"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
