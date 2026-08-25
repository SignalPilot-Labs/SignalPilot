"""Notion integrations, installations, deliverables, webhooks

Part of the initial Alembic baseline: this revision creates the notion
tables exactly as the gateway models define them today.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('gateway_notion_integrations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('api_key_enc', sa.LargeBinary(), nullable=False),
    sa.Column('search_page_ids', sa.JSON(), nullable=False),
    sa.Column('report_parent_page_id', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'name', name='uq_gw_notion_org_name')
    )
    op.create_index('ix_gw_notion_org_id', 'gateway_notion_integrations', ['org_id'], unique=False)
    op.create_table('notion_installations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('workspace_id', sa.String(length=100), nullable=False),
    sa.Column('workspace_name', sa.String(length=500), nullable=True),
    sa.Column('bot_id', sa.String(length=100), nullable=False),
    sa.Column('owner_user_id', sa.String(length=100), nullable=True),
    sa.Column('access_token_enc', sa.LargeBinary(), nullable=False),
    sa.Column('refresh_token_enc', sa.LargeBinary(), nullable=True),
    sa.Column('owner', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='connected', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'workspace_id', 'bot_id', name='uq_notion_install_org_workspace_bot')
    )
    op.create_index('ix_notion_install_org_status', 'notion_installations', ['org_id', 'status'], unique=False)
    op.create_index('ix_notion_install_workspace', 'notion_installations', ['workspace_id'], unique=False)
    op.create_table('notion_installation_config',
    sa.Column('installation_id', sa.String(), nullable=False),
    sa.Column('parent_page_id', sa.String(length=100), nullable=True),
    sa.Column('trigger_page_id', sa.String(length=100), nullable=True),
    sa.Column('requests_data_source_id', sa.String(length=100), nullable=True),
    sa.Column('requests_database_page_id', sa.String(length=100), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('default_project_id', sa.String(), nullable=True),
    sa.Column('default_branch', sa.String(length=100), server_default='main', nullable=False),
    sa.Column('analysis_branch_mode', sa.String(length=30), server_default='per_request', nullable=False),
    sa.PrimaryKeyConstraint('installation_id')
    )
    op.create_table('notion_webhook_deliveries',
    sa.Column('event_id', sa.String(length=100), nullable=False),
    sa.Column('installation_id', sa.String(), nullable=True),
    sa.Column('org_id', sa.String(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('attempt_number', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('event_id')
    )
    op.create_index('ix_notion_delivery_install', 'notion_webhook_deliveries', ['installation_id'], unique=False)
    op.create_index('ix_notion_delivery_org_status', 'notion_webhook_deliveries', ['org_id', 'status'], unique=False)
    op.create_table('notion_deliverables',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('installation_id', sa.String(), nullable=False),
    sa.Column('page_id', sa.String(length=100), nullable=False),
    sa.Column('request_page_id', sa.String(length=100), nullable=True),
    sa.Column('discussion_id', sa.String(length=100), nullable=True),
    sa.Column('request_id', sa.String(length=120), nullable=False),
    sa.Column('report_id', sa.String(), nullable=False),
    sa.Column('kind', sa.String(length=20), server_default='report', nullable=False),
    sa.Column('embed_block_id', sa.String(length=100), nullable=True),
    sa.Column('file_upload_id', sa.String(length=100), nullable=True),
    sa.Column('session_id', sa.String(length=120), nullable=True),
    sa.Column('context_snapshot_id', sa.String(), nullable=True),
    sa.Column('latest_update_id', sa.String(), nullable=True),
    sa.Column('latest_file_upload_id', sa.String(length=100), nullable=True),
    sa.Column('latest_html_bytes', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='active', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_notion_deliverables_embed', 'notion_deliverables', ['installation_id', 'embed_block_id'], unique=False)
    op.create_index('ix_notion_deliverables_install', 'notion_deliverables', ['installation_id', 'created_at'], unique=False)
    op.create_index('ix_notion_deliverables_org_request', 'notion_deliverables', ['org_id', 'request_id'], unique=False)
    op.create_index('ix_notion_deliverables_report', 'notion_deliverables', ['org_id', 'report_id'], unique=False)
    op.create_table('notion_deliverable_context_snapshots',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('deliverable_id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('request_id', sa.String(length=120), nullable=False),
    sa.Column('session_id', sa.String(length=120), nullable=True),
    sa.Column('base_notebook_code', sa.Text(), nullable=False),
    sa.Column('base_chat_events', sa.JSON(), nullable=True),
    sa.Column('base_final_packet', sa.JSON(), nullable=True),
    sa.Column('base_notebook_sha256', sa.String(length=64), nullable=True),
    sa.Column('base_notebook_path', sa.Text(), nullable=True),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('branch', sa.String(length=100), nullable=True),
    sa.Column('source_prompt', sa.Text(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_notion_deliverable_context_deliverable', 'notion_deliverable_context_snapshots', ['deliverable_id', 'created_at'], unique=False)
    op.create_index('ix_notion_deliverable_context_org_request', 'notion_deliverable_context_snapshots', ['org_id', 'request_id'], unique=False)
    op.create_table('notion_deliverable_updates',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('deliverable_id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('mode', sa.String(length=30), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='running', nullable=False),
    sa.Column('prompt', sa.Text(), nullable=True),
    sa.Column('data_instruction', sa.Text(), nullable=True),
    sa.Column('render_instruction', sa.Text(), nullable=True),
    sa.Column('ephemeral_run_id', sa.String(length=160), nullable=True),
    sa.Column('old_file_upload_id', sa.String(length=100), nullable=True),
    sa.Column('new_file_upload_id', sa.String(length=100), nullable=True),
    sa.Column('html_bytes', sa.Integer(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_notion_deliverable_updates_deliverable', 'notion_deliverable_updates', ['deliverable_id', 'created_at'], unique=False)
    op.create_index('ix_notion_deliverable_updates_org_status', 'notion_deliverable_updates', ['org_id', 'status'], unique=False)
    op.create_table('notion_oauth_states',
    sa.Column('state', sa.String(length=128), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('redirect_after', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('state')
    )
    op.create_index('ix_notion_oauth_states_expires', 'notion_oauth_states', ['expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_notion_oauth_states_expires', table_name='notion_oauth_states')
    op.drop_index('ix_notion_deliverable_updates_org_status', table_name='notion_deliverable_updates')
    op.drop_index('ix_notion_deliverable_updates_deliverable', table_name='notion_deliverable_updates')
    op.drop_index('ix_notion_deliverable_context_org_request', table_name='notion_deliverable_context_snapshots')
    op.drop_index('ix_notion_deliverable_context_deliverable', table_name='notion_deliverable_context_snapshots')
    op.drop_index('ix_notion_deliverables_report', table_name='notion_deliverables')
    op.drop_index('ix_notion_deliverables_org_request', table_name='notion_deliverables')
    op.drop_index('ix_notion_deliverables_install', table_name='notion_deliverables')
    op.drop_index('ix_notion_deliverables_embed', table_name='notion_deliverables')
    op.drop_index('ix_notion_delivery_org_status', table_name='notion_webhook_deliveries')
    op.drop_index('ix_notion_delivery_install', table_name='notion_webhook_deliveries')
    op.drop_index('ix_notion_install_workspace', table_name='notion_installations')
    op.drop_index('ix_notion_install_org_status', table_name='notion_installations')
    op.drop_index('ix_gw_notion_org_id', table_name='gateway_notion_integrations')
    op.drop_table('notion_oauth_states')
    op.drop_table('notion_deliverable_updates')
    op.drop_table('notion_deliverable_context_snapshots')
    op.drop_table('notion_deliverables')
    op.drop_table('notion_webhook_deliveries')
    op.drop_table('notion_installation_config')
    op.drop_table('notion_installations')
    op.drop_table('gateway_notion_integrations')
