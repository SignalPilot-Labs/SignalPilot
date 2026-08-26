"""knowledge base: docs, edits, retrievals, schema watches, reports

Part of the initial Alembic baseline: this revision creates the knowledge
tables exactly as the gateway models define them today.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('gateway_knowledge_docs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('scope', sa.String(length=20), nullable=False),
    sa.Column('scope_ref', sa.String(length=200), nullable=True),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='active', nullable=False),
    sa.Column('bytes', sa.Integer(), nullable=False),
    sa.Column('view_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.Column('created_by', sa.String(), nullable=True),
    sa.Column('updated_by', sa.String(), nullable=True),
    sa.Column('proposed_by_agent', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_knowledge_org_cat', 'gateway_knowledge_docs', ['org_id', 'category'], unique=False)
    op.create_index('idx_knowledge_org_scope', 'gateway_knowledge_docs', ['org_id', 'scope', 'scope_ref'], unique=False)
    op.create_index('idx_knowledge_org_status', 'gateway_knowledge_docs', ['org_id', 'status'], unique=False)
    op.create_table('gateway_knowledge_edits',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('doc_id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('body_before', sa.Text(), nullable=False),
    sa.Column('bytes_before', sa.Integer(), nullable=False),
    sa.Column('edited_at', sa.Float(), nullable=False),
    sa.Column('edited_by', sa.String(), nullable=True),
    sa.Column('edit_kind', sa.String(length=20), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_knowledge_edits_doc', 'gateway_knowledge_edits', ['doc_id', 'edited_at'], unique=False)
    op.create_index('idx_knowledge_edits_org', 'gateway_knowledge_edits', ['org_id'], unique=False)
    op.create_table('gateway_knowledge_retrievals',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('doc_id', sa.String(), nullable=False),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('query', sa.String(length=300), nullable=True),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('rank', sa.Integer(), nullable=True),
    sa.Column('score', sa.Float(), nullable=True),
    sa.Column('ts', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_knowledge_retr_org_doc_ts', 'gateway_knowledge_retrievals', ['org_id', 'doc_id', 'ts'], unique=False)
    op.create_index('idx_knowledge_retr_org_ts', 'gateway_knowledge_retrievals', ['org_id', 'ts'], unique=False)
    op.create_table('gateway_schema_watches',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('connection_name', sa.String(length=100), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('interval_s', sa.Integer(), nullable=False),
    sa.Column('github_repo', sa.String(length=200), nullable=False),
    sa.Column('github_base_branch', sa.String(length=100), nullable=True),
    sa.Column('last_fingerprint', sa.String(length=64), nullable=True),
    sa.Column('last_schema', sa.JSON(), nullable=True),
    sa.Column('last_run_at', sa.Float(), nullable=True),
    sa.Column('last_change_at', sa.Float(), nullable=True),
    sa.Column('last_pr_url', sa.String(length=500), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'connection_name', 'github_repo', name='uq_gw_schema_watch')
    )
    op.create_index('idx_schema_watch_org', 'gateway_schema_watches', ['org_id'], unique=False)
    op.create_table('gateway_reports',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('scope_ref', sa.String(length=200), nullable=True),
    sa.Column('kind', sa.String(length=20), server_default='report', nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('html', sa.Text(), nullable=False),
    sa.Column('data_json', sa.JSON(), nullable=True),
    sa.Column('bytes', sa.Integer(), nullable=False),
    sa.Column('view_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.Column('created_by', sa.String(), nullable=True),
    sa.Column('proposed_by_agent', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_reports_org_created', 'gateway_reports', ['org_id', 'created_at'], unique=False)
    op.create_index('idx_reports_org_kind', 'gateway_reports', ['org_id', 'kind', 'created_at'], unique=False)
    op.create_index('idx_reports_org_scope', 'gateway_reports', ['org_id', 'scope_ref'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_reports_org_scope', table_name='gateway_reports')
    op.drop_index('idx_reports_org_kind', table_name='gateway_reports')
    op.drop_index('idx_reports_org_created', table_name='gateway_reports')
    op.drop_index('idx_schema_watch_org', table_name='gateway_schema_watches')
    op.drop_index('idx_knowledge_retr_org_ts', table_name='gateway_knowledge_retrievals')
    op.drop_index('idx_knowledge_retr_org_doc_ts', table_name='gateway_knowledge_retrievals')
    op.drop_index('idx_knowledge_edits_org', table_name='gateway_knowledge_edits')
    op.drop_index('idx_knowledge_edits_doc', table_name='gateway_knowledge_edits')
    op.drop_index('idx_knowledge_org_status', table_name='gateway_knowledge_docs')
    op.drop_index('idx_knowledge_org_scope', table_name='gateway_knowledge_docs')
    op.drop_index('idx_knowledge_org_cat', table_name='gateway_knowledge_docs')
    op.drop_table('gateway_reports')
    op.drop_table('gateway_schema_watches')
    op.drop_table('gateway_knowledge_retrievals')
    op.drop_table('gateway_knowledge_edits')
    op.drop_table('gateway_knowledge_docs')
