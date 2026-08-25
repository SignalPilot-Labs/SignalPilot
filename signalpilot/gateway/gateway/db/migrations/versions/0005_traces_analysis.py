"""chat traces, analysis trails, agent runs

Part of the initial Alembic baseline: this revision creates the traces_analysis
tables exactly as the gateway models define them today.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('gateway_chat_trace_threads',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('thread_id', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('notebook_path', sa.Text(), nullable=False),
    sa.Column('notion_request_page_id', sa.String(length=100), nullable=True),
    sa.Column('notion_discussion_id', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'thread_id', name='uq_gw_trace_thread_org')
    )
    op.create_index('ix_gw_trace_threads_session_org', 'gateway_chat_trace_threads', ['org_id', 'session_id', 'updated_at'], unique=False)
    op.create_index('ix_gw_trace_threads_source_org', 'gateway_chat_trace_threads', ['org_id', 'source', 'updated_at'], unique=False)
    op.create_table('gateway_chat_trace_events',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('thread_id', sa.String(), nullable=False),
    sa.Column('idx', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=80), nullable=False),
    sa.Column('role', sa.String(length=30), nullable=True),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('tool_name', sa.String(length=300), nullable=False),
    sa.Column('tool_input_json', sa.JSON(), nullable=True),
    sa.Column('tool_call_id', sa.String(length=200), nullable=False),
    sa.Column('is_error', sa.Boolean(), nullable=False),
    sa.Column('cost_usd', sa.Float(), nullable=True),
    sa.Column('turn', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'thread_id', 'idx', name='uq_gw_trace_event_org_idx')
    )
    op.create_index('ix_gw_trace_events_thread_idx_org', 'gateway_chat_trace_events', ['org_id', 'thread_id', 'idx'], unique=False)
    op.create_table('gateway_analysis_trails',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('request_id', sa.String(length=200), nullable=False),
    sa.Column('thread_id', sa.String(length=300), nullable=False),
    sa.Column('runtime_session_id', sa.String(), nullable=True),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('branch', sa.String(length=100), nullable=False),
    sa.Column('default_branch', sa.String(length=100), nullable=False),
    sa.Column('notebook_path', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('latest_commit_sha', sa.String(length=64), nullable=True),
    sa.Column('source_url', sa.Text(), nullable=True),
    sa.Column('source_thread_id', sa.String(length=300), nullable=True),
    sa.Column('source_request_id', sa.String(length=300), nullable=True),
    sa.Column('analysis_user_id', sa.String(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'source', 'request_id', name='uq_gw_analysis_trail_request')
    )
    op.create_index('ix_gw_analysis_trail_project', 'gateway_analysis_trails', ['org_id', 'project_id', 'branch'], unique=False)
    op.create_index('ix_gw_analysis_trail_source_status', 'gateway_analysis_trails', ['org_id', 'source', 'status'], unique=False)
    op.create_index('ix_gw_analysis_trail_thread', 'gateway_analysis_trails', ['org_id', 'thread_id'], unique=False)
    op.create_table('gateway_agent_runs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('conversation_id', sa.String(), nullable=True),
    sa.Column('agent_type', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('input_json', sa.JSON(), nullable=True),
    sa.Column('output_json', sa.JSON(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.Float(), nullable=True),
    sa.Column('completed_at', sa.Float(), nullable=True),
    sa.Column('duration_ms', sa.Float(), nullable=True),
    sa.Column('total_tokens', sa.Integer(), nullable=True),
    sa.Column('cost_usd', sa.Float(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_gw_arun_conversation', 'gateway_agent_runs', ['conversation_id'], unique=False)
    op.create_index('ix_gw_arun_org_created', 'gateway_agent_runs', ['org_id', 'created_at'], unique=False)
    op.create_index('ix_gw_arun_org_proj', 'gateway_agent_runs', ['org_id', 'project_id'], unique=False)
    op.create_index('ix_gw_arun_org_status', 'gateway_agent_runs', ['org_id', 'status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_gw_arun_org_status', table_name='gateway_agent_runs')
    op.drop_index('ix_gw_arun_org_proj', table_name='gateway_agent_runs')
    op.drop_index('ix_gw_arun_org_created', table_name='gateway_agent_runs')
    op.drop_index('ix_gw_arun_conversation', table_name='gateway_agent_runs')
    op.drop_index('ix_gw_analysis_trail_thread', table_name='gateway_analysis_trails')
    op.drop_index('ix_gw_analysis_trail_source_status', table_name='gateway_analysis_trails')
    op.drop_index('ix_gw_analysis_trail_project', table_name='gateway_analysis_trails')
    op.drop_index('ix_gw_trace_events_thread_idx_org', table_name='gateway_chat_trace_events')
    op.drop_index('ix_gw_trace_threads_source_org', table_name='gateway_chat_trace_threads')
    op.drop_index('ix_gw_trace_threads_session_org', table_name='gateway_chat_trace_threads')
    op.drop_table('gateway_agent_runs')
    op.drop_table('gateway_analysis_trails')
    op.drop_table('gateway_chat_trace_events')
    op.drop_table('gateway_chat_trace_threads')
