"""chat: conversations, messages, runs, artifacts, shares, preferences

Part of the initial Alembic baseline: this revision creates the chat
tables exactly as the gateway models define them today.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('gateway_chat_conversations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('surface', sa.String(length=20), server_default='notebook', nullable=False),
    sa.Column('origin', sa.String(length=20), server_default='user', nullable=False),
    sa.Column('branch', sa.String(length=100), nullable=True),
    sa.Column('commit_sha', sa.String(length=40), nullable=True),
    sa.Column('per_query_budget_usd', sa.Float(), server_default='0.25', nullable=False),
    sa.Column('chat_budget_usd', sa.Float(), server_default='1.0', nullable=False),
    sa.Column('estimated_spend_usd', sa.Float(), server_default='0', nullable=False),
    sa.Column('actual_spend_usd', sa.Float(), server_default='0', nullable=False),
    sa.Column('reserved_spend_usd', sa.Float(), server_default='0', nullable=False),
    sa.Column('forked_from_conversation_id', sa.String(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='active', nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('internal_summary', sa.Text(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=True),
    sa.Column('agent_session_id', sa.String(), nullable=True),
    sa.Column('model', sa.String(length=50), nullable=True),
    sa.Column('message_count', sa.Integer(), nullable=False),
    sa.Column('total_tokens', sa.Integer(), nullable=False),
    sa.Column('total_cost_usd', sa.Float(), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_gw_conv_org_proj', 'gateway_chat_conversations', ['org_id', 'project_id'], unique=False)
    op.create_index('ix_gw_conv_org_user', 'gateway_chat_conversations', ['org_id', 'user_id'], unique=False)
    op.create_index('ix_gw_conv_standalone_history', 'gateway_chat_conversations', ['org_id', 'user_id', 'surface', 'status', 'updated_at'], unique=False)
    op.create_index('ix_gw_conv_updated', 'gateway_chat_conversations', ['org_id', 'updated_at'], unique=False)
    op.create_table('gateway_chat_messages',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('conversation_id', sa.String(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('idempotency_key', sa.String(length=200), nullable=True),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_gw_chat_conversation', 'gateway_chat_messages', ['conversation_id', 'sequence'], unique=False)
    op.create_index('ix_gw_chat_org_created', 'gateway_chat_messages', ['org_id', 'created_at'], unique=False)
    op.create_index('ix_gw_chat_org_user_proj', 'gateway_chat_messages', ['org_id', 'user_id', 'project_id'], unique=False)
    op.create_index('uq_gw_chat_message_idempotency', 'gateway_chat_messages', ['idempotency_key'], unique=True, postgresql_where=sa.text('idempotency_key IS NOT NULL'), sqlite_where=sa.text('idempotency_key IS NOT NULL'))
    op.create_table('gateway_chat_runs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('conversation_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('user_message_id', sa.String(), nullable=False),
    sa.Column('status', sa.String(length=30), server_default='queued', nullable=False),
    sa.Column('retry_of_run_id', sa.String(), nullable=True),
    sa.Column('execution_session_id', sa.String(), nullable=True),
    sa.Column('runtime_archive_id', sa.String(), nullable=True),
    sa.Column('execution_attempt', sa.Integer(), server_default='0', nullable=False),
    sa.Column('lease_owner', sa.String(length=200), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancellation_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('public_error_code', sa.String(length=100), nullable=True),
    sa.Column('public_error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('terminal_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_event_sequence', sa.Integer(), server_default='0', nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_gw_chat_runs_owner', 'gateway_chat_runs', ['org_id', 'user_id', 'conversation_id'], unique=False)
    op.create_index('ix_gw_chat_runs_queue', 'gateway_chat_runs', ['status', 'lease_expires_at', 'created_at'], unique=False)
    op.create_index('uq_gw_chat_run_nonterminal_conversation', 'gateway_chat_runs', ['conversation_id'], unique=True, postgresql_where=sa.text("status IN ('queued','running','waiting_for_user','waiting_for_query_approval')"), sqlite_where=sa.text("status IN ('queued','running','waiting_for_user','waiting_for_query_approval')"))
    op.create_table('gateway_chat_run_events',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('conversation_id', sa.String(), nullable=False),
    sa.Column('run_id', sa.String(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=50), nullable=False),
    sa.Column('payload_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'sequence', name='uq_gw_chat_run_event_sequence')
    )
    op.create_index('ix_gw_chat_run_events_owner', 'gateway_chat_run_events', ['org_id', 'user_id', 'run_id', 'sequence'], unique=False)
    op.create_table('gateway_chat_artifacts',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('conversation_id', sa.String(), nullable=False),
    sa.Column('run_id', sa.String(), nullable=False),
    sa.Column('assistant_message_id', sa.String(), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=150), nullable=False),
    sa.Column('snapshot_json', sa.JSON(), nullable=False),
    sa.Column('binary_data', sa.LargeBinary(), nullable=True),
    sa.Column('storage_kind', sa.String(length=20), server_default='inline', nullable=False),
    sa.Column('object_key', sa.Text(), nullable=True),
    sa.Column('source_object_key', sa.Text(), nullable=True),
    sa.Column('byte_size', sa.BigInteger(), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('provenance_json', sa.JSON(), nullable=True),
    sa.Column('freshness_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('assumptions', sa.JSON(), nullable=False),
    sa.Column('exclusions', sa.JSON(), nullable=False),
    sa.Column('caveats', sa.JSON(), nullable=False),
    sa.Column('parent_artifact_id', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'kind', 'filename', name='uq_gw_chat_artifact_publication')
    )
    op.create_index('ix_gw_chat_artifacts_owner', 'gateway_chat_artifacts', ['org_id', 'user_id', 'conversation_id'], unique=False)
    op.create_index('ix_gw_chat_artifacts_run', 'gateway_chat_artifacts', ['run_id', 'created_at'], unique=False)
    op.create_table('gateway_chat_share_grants',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('conversation_id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('owner_user_id', sa.String(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('state', sa.String(length=20), server_default='active', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index('ix_gw_chat_share_lookup', 'gateway_chat_share_grants', ['org_id', 'token_hash', 'state'], unique=False)
    op.create_index('ix_gw_chat_share_owner', 'gateway_chat_share_grants', ['org_id', 'owner_user_id', 'conversation_id', 'state'], unique=False)
    op.create_index('uq_gw_chat_share_active_conversation', 'gateway_chat_share_grants', ['conversation_id'], unique=True, postgresql_where=sa.text("state = 'active'"), sqlite_where=sa.text("state = 'active'"))
    op.create_table('gateway_chat_starter_cache',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('metadata_checksum', sa.String(length=64), nullable=False),
    sa.Column('questions_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'project_id', 'metadata_checksum', name='uq_gw_chat_starters_checksum')
    )
    op.create_index('ix_gw_chat_starters_project', 'gateway_chat_starter_cache', ['org_id', 'project_id'], unique=False)
    op.create_table('gateway_chat_user_preferences',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('default_chat_project_id', sa.String(), nullable=True),
    sa.Column('default_per_query_budget_usd', sa.Float(), server_default='0.25', nullable=False),
    sa.Column('default_chat_budget_usd', sa.Float(), server_default='1.0', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'user_id', name='uq_gw_chat_user_preference')
    )


def downgrade() -> None:
    op.drop_index('ix_gw_chat_starters_project', table_name='gateway_chat_starter_cache')
    op.drop_index('uq_gw_chat_share_active_conversation', table_name='gateway_chat_share_grants')
    op.drop_index('ix_gw_chat_share_owner', table_name='gateway_chat_share_grants')
    op.drop_index('ix_gw_chat_share_lookup', table_name='gateway_chat_share_grants')
    op.drop_index('ix_gw_chat_artifacts_run', table_name='gateway_chat_artifacts')
    op.drop_index('ix_gw_chat_artifacts_owner', table_name='gateway_chat_artifacts')
    op.drop_index('ix_gw_chat_run_events_owner', table_name='gateway_chat_run_events')
    op.drop_index('uq_gw_chat_run_nonterminal_conversation', table_name='gateway_chat_runs')
    op.drop_index('ix_gw_chat_runs_queue', table_name='gateway_chat_runs')
    op.drop_index('ix_gw_chat_runs_owner', table_name='gateway_chat_runs')
    op.drop_index('uq_gw_chat_message_idempotency', table_name='gateway_chat_messages')
    op.drop_index('ix_gw_chat_org_user_proj', table_name='gateway_chat_messages')
    op.drop_index('ix_gw_chat_org_created', table_name='gateway_chat_messages')
    op.drop_index('ix_gw_chat_conversation', table_name='gateway_chat_messages')
    op.drop_index('ix_gw_conv_updated', table_name='gateway_chat_conversations')
    op.drop_index('ix_gw_conv_standalone_history', table_name='gateway_chat_conversations')
    op.drop_index('ix_gw_conv_org_user', table_name='gateway_chat_conversations')
    op.drop_index('ix_gw_conv_org_proj', table_name='gateway_chat_conversations')
    op.drop_table('gateway_chat_user_preferences')
    op.drop_table('gateway_chat_starter_cache')
    op.drop_table('gateway_chat_share_grants')
    op.drop_table('gateway_chat_artifacts')
    op.drop_table('gateway_chat_run_events')
    op.drop_table('gateway_chat_runs')
    op.drop_table('gateway_chat_messages')
    op.drop_table('gateway_chat_conversations')
