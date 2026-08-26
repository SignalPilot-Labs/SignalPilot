"""core platform: orgs, connections, credentials, settings, keys, audit

Part of the initial Alembic baseline: this revision creates the core_platform
tables exactly as the gateway models define them today.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('gateway_orgs',
    sa.Column('org_id', sa.String(length=100), nullable=False),
    sa.Column('plan_tier', sa.String(length=20), server_default='free', nullable=False),
    sa.Column('byok_enabled', sa.Boolean(), nullable=False),
    sa.Column('default_byok_key_id', sa.String(), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('org_id')
    )
    op.create_table('gateway_connections',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('db_type', sa.String(length=20), nullable=False),
    sa.Column('host', sa.String(length=500), nullable=True),
    sa.Column('port', sa.Integer(), nullable=True),
    sa.Column('database', sa.String(length=500), nullable=True),
    sa.Column('username', sa.String(length=200), nullable=True),
    sa.Column('ssl', sa.Boolean(), nullable=False),
    sa.Column('ssl_config', sa.JSON(), nullable=True),
    sa.Column('ssh_tunnel', sa.JSON(), nullable=True),
    sa.Column('account', sa.String(length=200), nullable=True),
    sa.Column('warehouse', sa.String(length=200), nullable=True),
    sa.Column('schema_name', sa.String(length=200), nullable=True),
    sa.Column('role', sa.String(length=200), nullable=True),
    sa.Column('project', sa.String(length=200), nullable=True),
    sa.Column('dataset', sa.String(length=200), nullable=True),
    sa.Column('location', sa.String(length=100), nullable=True),
    sa.Column('http_path', sa.String(length=500), nullable=True),
    sa.Column('catalog', sa.String(length=200), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('tags', sa.JSON(), nullable=True),
    sa.Column('schema_filter_include', sa.JSON(), nullable=True),
    sa.Column('schema_filter_exclude', sa.JSON(), nullable=True),
    sa.Column('schema_refresh_interval', sa.Integer(), nullable=True),
    sa.Column('connection_timeout', sa.Integer(), nullable=True),
    sa.Column('query_timeout', sa.Integer(), nullable=True),
    sa.Column('keepalive_interval', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('last_used', sa.Float(), nullable=True),
    sa.Column('last_schema_refresh', sa.Float(), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('endorsements', sa.JSON(), nullable=True),
    sa.Column('pii_rules', sa.JSON(), nullable=True),
    sa.Column('pii_enabled', sa.Boolean(), nullable=False),
    sa.Column('byok_key_alias', sa.String(length=200), nullable=True),
    sa.Column('health_last_check', sa.Float(), nullable=True),
    sa.Column('health_last_error', sa.Text(), nullable=True),
    sa.Column('health_consecutive_failures', sa.Integer(), server_default='0', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'name', name='uq_gw_conn_org_name')
    )
    op.create_index('ix_gw_conn_org_id', 'gateway_connections', ['org_id'], unique=False)
    op.create_table('gateway_credentials',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('connection_name', sa.String(length=100), nullable=False),
    sa.Column('connection_string_enc', sa.LargeBinary(), nullable=False),
    sa.Column('extras_enc', sa.LargeBinary(), nullable=True),
    sa.Column('key_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('encryption_mode', sa.String(length=20), server_default='managed', nullable=False),
    sa.Column('wrapped_dek', sa.LargeBinary(), nullable=True),
    sa.Column('byok_key_id', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'connection_name', name='uq_gw_cred_org_conn')
    )
    op.create_index('ix_gw_cred_org_id', 'gateway_credentials', ['org_id'], unique=False)
    op.create_table('gateway_byok_keys',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('key_alias', sa.String(length=200), nullable=False),
    sa.Column('provider_type', sa.String(length=50), nullable=False),
    sa.Column('provider_config', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('revoked_at', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'key_alias', name='uq_gw_byok_org_alias')
    )
    op.create_index('ix_gw_byok_org_id', 'gateway_byok_keys', ['org_id'], unique=False)
    op.create_table('gateway_settings',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('settings_json', sa.JSON(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id')
    )
    op.create_table('gateway_api_keys',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('prefix', sa.String(length=20), nullable=False),
    sa.Column('key_hash', sa.String(), nullable=False),
    sa.Column('scopes', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.String(), nullable=True),
    sa.Column('last_used_at', sa.String(), nullable=True),
    sa.Column('expires_at', sa.String(), nullable=True),
    sa.Column('eval_run_id', sa.String(length=64), nullable=True),
    sa.Column('eval_task_id', sa.String(length=200), nullable=True),
    sa.Column('eval_connection', sa.String(length=64), nullable=True),
    sa.Column('eval_doc_ids', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_gw_api_keys_hash', 'gateway_api_keys', ['key_hash'], unique=False)
    op.create_index('ix_gw_api_keys_org', 'gateway_api_keys', ['org_id'], unique=False)
    op.create_table('gateway_audit_logs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('timestamp', sa.Float(), nullable=False),
    sa.Column('event_type', sa.String(length=20), nullable=False),
    sa.Column('connection_name', sa.String(length=100), nullable=True),
    sa.Column('sandbox_id', sa.String(), nullable=True),
    sa.Column('sql_text', sa.Text(), nullable=True),
    sa.Column('tables', sa.JSON(), nullable=True),
    sa.Column('rows_returned', sa.Integer(), nullable=True),
    sa.Column('cost_usd', sa.Float(), nullable=True),
    sa.Column('blocked', sa.Boolean(), nullable=False),
    sa.Column('block_reason', sa.String(length=500), nullable=True),
    sa.Column('duration_ms', sa.Float(), nullable=True),
    sa.Column('agent_id', sa.String(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('parent_id', sa.Text(), nullable=True),
    sa.Column('client_ip', sa.Text(), nullable=True),
    sa.Column('user_agent', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_gw_audit_conn', 'gateway_audit_logs', ['connection_name'], unique=False)
    op.create_index('ix_gw_audit_org_ts', 'gateway_audit_logs', ['org_id', 'timestamp'], unique=False)
    op.create_table('gateway_health_events',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('connection_name', sa.String(length=100), nullable=False),
    sa.Column('timestamp', sa.Float(), nullable=False),
    sa.Column('latency_ms', sa.Float(), nullable=False),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_gw_health_org_conn_ts', 'gateway_health_events', ['org_id', 'connection_name', 'timestamp'], unique=False)
    op.create_table('gateway_session_budgets',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=False),
    sa.Column('budget_usd', sa.Float(), nullable=False),
    sa.Column('spent_usd', sa.Float(), server_default='0', nullable=False),
    sa.Column('query_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('last_activity', sa.Float(), nullable=False),
    sa.Column('closed', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'session_id', name='uq_gw_budget_org_session')
    )
    op.create_index('ix_gw_budget_org_id', 'gateway_session_budgets', ['org_id'], unique=False)
    op.create_table('gateway_upload_sessions',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('key', sa.String(length=500), nullable=False),
    sa.Column('upload_id', sa.String(length=500), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('part_lengths', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('expires_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'key', name='uq_gw_upload_org_key')
    )
    op.create_index('ix_gw_upload_expires', 'gateway_upload_sessions', ['expires_at'], unique=False)
    op.create_index('ix_gw_upload_org_user', 'gateway_upload_sessions', ['org_id', 'user_id'], unique=False)
    op.create_table('gateway_user_sessions',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('active_branch', sa.String(length=100), nullable=False),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'user_id', 'project_id', name='uq_gw_session_org_user_proj')
    )
    op.create_index('ix_gw_session_org_user', 'gateway_user_sessions', ['org_id', 'user_id'], unique=False)
    op.create_table('gateway_user_secrets',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('anthropic_api_key_enc', sa.LargeBinary(), nullable=True),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'user_id', name='uq_gw_usersecrets_org_user')
    )
    op.create_index('ix_gw_usersecrets_org_id', 'gateway_user_secrets', ['org_id'], unique=False)
    op.create_table('gateway_org_secrets',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('anthropic_api_key_enc', sa.LargeBinary(), nullable=True),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id')
    )
    op.create_index('ix_gw_orgsecrets_org_id', 'gateway_org_secrets', ['org_id'], unique=False)
    op.create_table('gateway_projects',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('connection_name', sa.String(length=100), nullable=False),
    sa.Column('project_dir', sa.String(length=1000), nullable=True),
    sa.Column('storage', sa.String(length=20), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=True),
    sa.Column('db_type', sa.String(length=20), nullable=True),
    sa.Column('dbt_version', sa.String(length=20), nullable=True),
    sa.Column('model_count', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=True),
    sa.Column('last_scanned_at', sa.Float(), nullable=True),
    sa.Column('git_remote', sa.String(length=500), nullable=True),
    sa.Column('git_branch', sa.String(length=100), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('tags', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'name', name='uq_gw_proj_org_name')
    )
    op.create_index('ix_gw_proj_org_id', 'gateway_projects', ['org_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_gw_proj_org_id', table_name='gateway_projects')
    op.drop_index('ix_gw_orgsecrets_org_id', table_name='gateway_org_secrets')
    op.drop_index('ix_gw_usersecrets_org_id', table_name='gateway_user_secrets')
    op.drop_index('ix_gw_session_org_user', table_name='gateway_user_sessions')
    op.drop_index('ix_gw_upload_org_user', table_name='gateway_upload_sessions')
    op.drop_index('ix_gw_upload_expires', table_name='gateway_upload_sessions')
    op.drop_index('ix_gw_budget_org_id', table_name='gateway_session_budgets')
    op.drop_index('ix_gw_health_org_conn_ts', table_name='gateway_health_events')
    op.drop_index('ix_gw_audit_org_ts', table_name='gateway_audit_logs')
    op.drop_index('ix_gw_audit_conn', table_name='gateway_audit_logs')
    op.drop_index('ix_gw_api_keys_org', table_name='gateway_api_keys')
    op.drop_index('ix_gw_api_keys_hash', table_name='gateway_api_keys')
    op.drop_index('ix_gw_byok_org_id', table_name='gateway_byok_keys')
    op.drop_index('ix_gw_cred_org_id', table_name='gateway_credentials')
    op.drop_index('ix_gw_conn_org_id', table_name='gateway_connections')
    op.drop_table('gateway_projects')
    op.drop_table('gateway_org_secrets')
    op.drop_table('gateway_user_secrets')
    op.drop_table('gateway_user_sessions')
    op.drop_table('gateway_upload_sessions')
    op.drop_table('gateway_session_budgets')
    op.drop_table('gateway_health_events')
    op.drop_table('gateway_audit_logs')
    op.drop_table('gateway_api_keys')
    op.drop_table('gateway_settings')
    op.drop_table('gateway_byok_keys')
    op.drop_table('gateway_credentials')
    op.drop_table('gateway_connections')
    op.drop_table('gateway_orgs')
