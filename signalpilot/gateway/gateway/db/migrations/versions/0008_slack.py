"""Slack installations, config, thread watches, oauth states

Part of the initial Alembic baseline: this revision creates the slack
tables exactly as the gateway models define them today.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('slack_installations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('team_id', sa.String(length=100), nullable=False),
    sa.Column('team_name', sa.String(length=500), nullable=True),
    sa.Column('enterprise_id', sa.String(length=100), nullable=True),
    sa.Column('enterprise_name', sa.String(length=500), nullable=True),
    sa.Column('app_id', sa.String(length=100), server_default='', nullable=False),
    sa.Column('bot_user_id', sa.String(length=100), nullable=False),
    sa.Column('authed_user_id', sa.String(length=100), nullable=True),
    sa.Column('bot_access_token_enc', sa.LargeBinary(), nullable=False),
    sa.Column('scopes', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='connected', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'team_id', 'app_id', name='uq_slack_install_org_team_app')
    )
    op.create_index('ix_slack_install_org_status', 'slack_installations', ['org_id', 'status'], unique=False)
    op.create_index('ix_slack_install_team', 'slack_installations', ['team_id'], unique=False)
    op.create_table('slack_installation_config',
    sa.Column('installation_id', sa.String(), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('default_project_id', sa.String(), nullable=True),
    sa.Column('default_branch', sa.String(length=100), server_default='main', nullable=False),
    sa.Column('analysis_branch_mode', sa.String(length=30), server_default='per_request', nullable=False),
    sa.Column('allowed_channel_ids', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('installation_id')
    )
    op.create_table('slack_oauth_states',
    sa.Column('state', sa.String(length=128), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('redirect_after', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('state')
    )
    op.create_index('ix_slack_oauth_states_expires', 'slack_oauth_states', ['expires_at'], unique=False)
    op.create_table('gateway_slack_thread_watches',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('team_id', sa.String(length=100), nullable=False),
    sa.Column('channel_id', sa.String(length=100), nullable=False),
    sa.Column('thread_ts', sa.String(length=50), nullable=False),
    sa.Column('source_thread_id', sa.String(length=300), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='active', nullable=False),
    sa.Column('invited_by_user_id', sa.String(length=100), nullable=True),
    sa.Column('latest_user_id', sa.String(length=100), nullable=True),
    sa.Column('first_event_ts', sa.String(length=50), nullable=True),
    sa.Column('latest_event_ts', sa.String(length=50), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'team_id', 'channel_id', 'thread_ts', name='uq_slack_thread_watch_identity')
    )
    op.create_index('ix_slack_thread_watch_active', 'gateway_slack_thread_watches', ['org_id', 'team_id', 'channel_id', 'status'], unique=False)
    op.create_index('ix_slack_thread_watch_source_thread', 'gateway_slack_thread_watches', ['org_id', 'source_thread_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_slack_thread_watch_source_thread', table_name='gateway_slack_thread_watches')
    op.drop_index('ix_slack_thread_watch_active', table_name='gateway_slack_thread_watches')
    op.drop_index('ix_slack_oauth_states_expires', table_name='slack_oauth_states')
    op.drop_index('ix_slack_install_team', table_name='slack_installations')
    op.drop_index('ix_slack_install_org_status', table_name='slack_installations')
    op.drop_table('gateway_slack_thread_watches')
    op.drop_table('slack_oauth_states')
    op.drop_table('slack_installation_config')
    op.drop_table('slack_installations')
