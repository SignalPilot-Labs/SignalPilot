"""approval.decision vocabulary: wire verbs → past tense

Revision ID: 20260501_0003
Revises: 20260501_0002
Create Date: 2026-05-01

Migrates Approval.decision values from the wire-verb vocabulary
("approve"/"reject") used in R2–R5 to the canonical past-tense vocabulary
("approved"/"rejected") that matches the on-disk resume-marker files.

By aligning the DB column with the marker file, a future reader never
has to decide which layer has the "right" value — both agree.

Downgrade reverses. The WHERE conditions make both operations idempotent.
"""

from __future__ import annotations

from alembic import op


revision = "20260501_0003"
down_revision = "20260501_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE workspaces.approval SET decision='approved' WHERE decision='approve'"
    )
    op.execute(
        "UPDATE workspaces.approval SET decision='rejected' WHERE decision='reject'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE workspaces.approval SET decision='approve' WHERE decision='approved'"
    )
    op.execute(
        "UPDATE workspaces.approval SET decision='reject' WHERE decision='rejected'"
    )
