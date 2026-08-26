"""search and performance indexes the ORM models do not declare

These indexes were historically created by the idempotent "ensure" helpers
in gateway/db/engine.py because SQLAlchemy create_all could not express
them (partial unique indexes, expression indexes) or because they exist
purely for query performance:

- audit log lookup indexes (org/time, org/event, parent linkage)
- knowledge doc partial unique indexes (org-scoped vs ref-scoped titles)
- knowledge doc full-text and trigram search indexes
- the org-scoped settings unique index

The trigram index requires the pg_trgm extension; deployments where the
extension is unavailable simply skip it, matching the legacy best-effort
behavior.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_audit_org_ts",
        "gateway_audit_logs",
        ["org_id", sa.text("timestamp DESC")],
    )
    op.create_index("idx_audit_org_event", "gateway_audit_logs", ["org_id", "event_type"])
    op.create_index(
        "idx_audit_parent",
        "gateway_audit_logs",
        ["parent_id"],
        postgresql_where=sa.text("parent_id IS NOT NULL"),
    )

    op.create_index("uq_gw_settings_org", "gateway_settings", ["org_id"], unique=True)

    op.create_index(
        "uq_knowledge_doc_org_null",
        "gateway_knowledge_docs",
        ["org_id", "scope", "category", "title"],
        unique=True,
        postgresql_where=sa.text("scope_ref IS NULL"),
    )
    op.create_index(
        "uq_knowledge_doc_scoped",
        "gateway_knowledge_docs",
        ["org_id", "scope", "scope_ref", "category", "title"],
        unique=True,
        postgresql_where=sa.text("scope_ref IS NOT NULL"),
    )
    op.execute(
        "CREATE INDEX idx_knowledge_fts ON gateway_knowledge_docs "
        "USING gin (to_tsvector('english', title || ' ' || body))"
    )

    # Trigram title search: best-effort, needs pg_trgm.
    conn = op.get_bind()
    trgm_available = conn.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'")
    ).first()
    if trgm_available:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.execute(
            "CREATE INDEX idx_knowledge_title_trgm ON gateway_knowledge_docs "
            "USING gin (title gin_trgm_ops)"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_knowledge_title_trgm")
    op.execute("DROP INDEX IF EXISTS idx_knowledge_fts")
    op.drop_index("uq_knowledge_doc_scoped", table_name="gateway_knowledge_docs")
    op.drop_index("uq_knowledge_doc_org_null", table_name="gateway_knowledge_docs")
    op.drop_index("uq_gw_settings_org", table_name="gateway_settings")
    op.drop_index("idx_audit_parent", table_name="gateway_audit_logs")
    op.drop_index("idx_audit_org_event", table_name="gateway_audit_logs")
    op.drop_index("idx_audit_org_ts", table_name="gateway_audit_logs")
