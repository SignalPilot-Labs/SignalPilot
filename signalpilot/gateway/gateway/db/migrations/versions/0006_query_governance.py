"""governed query executions, results, plans, proposals, runtime objects

Part of the initial Alembic baseline: this revision creates the query_governance
tables exactly as the gateway models define them today.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('gateway_governed_query_executions',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('conversation_id', sa.String(), nullable=True),
    sa.Column('run_id', sa.String(), nullable=True),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('commit_sha', sa.String(length=40), nullable=True),
    sa.Column('connection_name', sa.String(length=100), nullable=False),
    sa.Column('plan_id', sa.String(), nullable=True),
    sa.Column('query_path', sa.String(length=30), nullable=False),
    sa.Column('sql_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('timeout_seconds', sa.Integer(), nullable=False),
    sa.Column('warehouse_query_id', sa.String(length=500), nullable=True),
    sa.Column('estimated_cost_usd', sa.Float(), nullable=False),
    sa.Column('actual_cost_usd', sa.Float(), nullable=True),
    sa.Column('actual_scan_bytes', sa.BigInteger(), nullable=True),
    sa.Column('actual_output_bytes', sa.BigInteger(), nullable=True),
    sa.Column('execution_ms', sa.Float(), nullable=True),
    sa.Column('row_count', sa.Integer(), nullable=True),
    sa.Column('completeness', sa.String(length=20), nullable=True),
    sa.Column('truncation_reason', sa.String(length=500), nullable=True),
    sa.Column('public_error_code', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('terminal_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_gw_query_execution_hash', 'gateway_governed_query_executions', ['org_id', 'connection_name', 'sql_hash'], unique=False)
    op.create_index('ix_gw_query_execution_run', 'gateway_governed_query_executions', ['org_id', 'run_id', 'created_at'], unique=False)
    op.create_index('ix_gw_query_execution_scope', 'gateway_governed_query_executions', ['org_id', 'user_id', 'created_at'], unique=False)
    op.create_table('gateway_structured_query_results',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('execution_id', sa.String(), nullable=True),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('owner_user_id', sa.String(), nullable=True),
    sa.Column('conversation_id', sa.String(), nullable=True),
    sa.Column('run_id', sa.String(), nullable=True),
    sa.Column('columns_json', sa.JSON(), nullable=False),
    sa.Column('rows_json', sa.JSON(), nullable=False),
    sa.Column('preview_rows_json', sa.JSON(), nullable=False),
    sa.Column('storage_kind', sa.String(length=20), server_default='inline', nullable=False),
    sa.Column('object_key', sa.Text(), nullable=True),
    sa.Column('byte_size', sa.BigInteger(), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('source_result_ids_json', sa.JSON(), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=True),
    sa.Column('result_origin', sa.String(length=20), server_default='mcp', nullable=False),
    sa.Column('query_row_count', sa.Integer(), nullable=True),
    sa.Column('saved_row_count', sa.Integer(), nullable=False),
    sa.Column('source_completeness', sa.String(length=20), nullable=False),
    sa.Column('result_completeness', sa.String(length=20), nullable=False),
    sa.Column('display_completeness', sa.String(length=20), nullable=False),
    sa.Column('truncation_reason', sa.String(length=500), nullable=True),
    sa.Column('provenance_json', sa.JSON(), nullable=False),
    sa.Column('freshness_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('execution_id')
    )
    op.create_index('ix_gw_structured_result_owner', 'gateway_structured_query_results', ['org_id', 'owner_user_id', 'created_at'], unique=False)
    op.create_table('gateway_query_plans',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('conversation_id', sa.String(), nullable=True),
    sa.Column('run_id', sa.String(), nullable=True),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('commit_sha', sa.String(length=40), nullable=True),
    sa.Column('branch', sa.String(length=100), nullable=True),
    sa.Column('connection_name', sa.String(length=100), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('execution_need', sa.String(length=20), nullable=False),
    sa.Column('normalized_sql', sa.Text(), nullable=False),
    sa.Column('sql_hash', sa.String(length=64), nullable=False),
    sa.Column('estimated_scan_rows', sa.BigInteger(), nullable=True),
    sa.Column('estimated_scan_bytes', sa.BigInteger(), nullable=True),
    sa.Column('estimated_output_rows', sa.BigInteger(), nullable=True),
    sa.Column('estimated_output_bytes', sa.BigInteger(), nullable=True),
    sa.Column('estimated_cost_usd', sa.Float(), nullable=False),
    sa.Column('estimate_quality', sa.String(length=20), nullable=False),
    sa.Column('route', sa.String(length=30), nullable=False),
    sa.Column('route_reason', sa.Text(), nullable=False),
    sa.Column('approval_required', sa.Boolean(), nullable=False),
    sa.Column('proposal_id', sa.String(), nullable=True),
    sa.Column('policy_version', sa.String(length=100), nullable=False),
    sa.Column('policy_hash', sa.String(length=64), nullable=False),
    sa.Column('shadow', sa.Boolean(), nullable=False),
    sa.Column('scout_row_limit', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_gw_query_plan_hash', 'gateway_query_plans', ['org_id', 'connection_name', 'sql_hash'], unique=False)
    op.create_index('ix_gw_query_plan_scope', 'gateway_query_plans', ['org_id', 'user_id', 'run_id', 'created_at'], unique=False)
    op.create_table('gateway_query_proposals',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('conversation_id', sa.String(), nullable=False),
    sa.Column('run_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('commit_sha', sa.String(length=40), nullable=False),
    sa.Column('connection_name', sa.String(length=100), nullable=False),
    sa.Column('plan_id', sa.String(), nullable=True),
    sa.Column('query_path', sa.String(length=30), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('normalized_sql', sa.Text(), nullable=False),
    sa.Column('sql_hash', sa.String(length=64), nullable=False),
    sa.Column('timeout_seconds', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('estimated_cost_usd', sa.Float(), nullable=False),
    sa.Column('estimate_quality', sa.String(length=30), nullable=False),
    sa.Column('estimate_json', sa.JSON(), nullable=False),
    sa.Column('policy_version', sa.String(length=100), nullable=False),
    sa.Column('reserved_cost_usd', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('terminal_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'sql_hash', name='uq_gw_query_proposal_run_hash')
    )
    op.create_index('ix_gw_query_proposal_waiting', 'gateway_query_proposals', ['org_id', 'user_id', 'status', 'created_at'], unique=False)
    op.create_table('gateway_query_approvals',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('proposal_id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('approver_user_id', sa.String(), nullable=False),
    sa.Column('approval_scope', sa.String(length=30), nullable=False),
    sa.Column('decision', sa.String(length=20), nullable=False),
    sa.Column('sql_hash', sa.String(length=64), nullable=False),
    sa.Column('approved_estimated_cost_usd', sa.Float(), nullable=False),
    sa.Column('per_query_budget_usd', sa.Float(), nullable=True),
    sa.Column('chat_budget_usd', sa.Float(), nullable=True),
    sa.Column('policy_version', sa.String(length=100), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('proposal_id', 'approver_user_id', name='uq_gw_query_approval_decision')
    )
    op.create_index('ix_gw_query_approval_owner', 'gateway_query_approvals', ['org_id', 'approver_user_id', 'created_at'], unique=False)
    op.create_table('gateway_runtime_datasets',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('owner_user_id', sa.String(), nullable=False),
    sa.Column('conversation_id', sa.String(), nullable=False),
    sa.Column('run_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('commit_sha', sa.String(length=40), nullable=False),
    sa.Column('connection_name', sa.String(length=100), nullable=False),
    sa.Column('plan_id', sa.String(), nullable=False),
    sa.Column('query_execution_id', sa.String(), nullable=False),
    sa.Column('schema_json', sa.JSON(), nullable=False),
    sa.Column('row_count', sa.BigInteger(), nullable=False),
    sa.Column('byte_size', sa.BigInteger(), nullable=False),
    sa.Column('completeness', sa.String(length=20), nullable=False),
    sa.Column('object_key', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'plan_id', name='uq_gw_runtime_dataset_plan')
    )
    op.create_index('ix_gw_runtime_dataset_expiry', 'gateway_runtime_datasets', ['expires_at'], unique=False)
    op.create_index('ix_gw_runtime_dataset_owner', 'gateway_runtime_datasets', ['org_id', 'owner_user_id', 'run_id'], unique=False)
    op.create_table('gateway_chat_runtime_archives',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('conversation_id', sa.String(), nullable=False),
    sa.Column('run_id', sa.String(), nullable=False),
    sa.Column('source_object_key', sa.Text(), nullable=False),
    sa.Column('html_object_key', sa.Text(), nullable=False),
    sa.Column('manifest_object_key', sa.Text(), nullable=False),
    sa.Column('source_hash', sa.String(length=64), nullable=False),
    sa.Column('html_hash', sa.String(length=64), nullable=False),
    sa.Column('manifest_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id')
    )
    op.create_index('ix_gw_chat_archive_owner', 'gateway_chat_runtime_archives', ['org_id', 'user_id', 'run_id'], unique=False)
    op.create_table('gateway_chat_object_deletions',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('conversation_id', sa.String(), nullable=False),
    sa.Column('object_prefix', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('conversation_id')
    )
    op.create_index('ix_gw_chat_object_deletion_pending', 'gateway_chat_object_deletions', ['status', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_gw_chat_object_deletion_pending', table_name='gateway_chat_object_deletions')
    op.drop_index('ix_gw_chat_archive_owner', table_name='gateway_chat_runtime_archives')
    op.drop_index('ix_gw_runtime_dataset_owner', table_name='gateway_runtime_datasets')
    op.drop_index('ix_gw_runtime_dataset_expiry', table_name='gateway_runtime_datasets')
    op.drop_index('ix_gw_query_approval_owner', table_name='gateway_query_approvals')
    op.drop_index('ix_gw_query_proposal_waiting', table_name='gateway_query_proposals')
    op.drop_index('ix_gw_query_plan_scope', table_name='gateway_query_plans')
    op.drop_index('ix_gw_query_plan_hash', table_name='gateway_query_plans')
    op.drop_index('ix_gw_structured_result_owner', table_name='gateway_structured_query_results')
    op.drop_index('ix_gw_query_execution_scope', table_name='gateway_governed_query_executions')
    op.drop_index('ix_gw_query_execution_run', table_name='gateway_governed_query_executions')
    op.drop_index('ix_gw_query_execution_hash', table_name='gateway_governed_query_executions')
    op.drop_table('gateway_chat_object_deletions')
    op.drop_table('gateway_chat_runtime_archives')
    op.drop_table('gateway_runtime_datasets')
    op.drop_table('gateway_query_approvals')
    op.drop_table('gateway_query_proposals')
    op.drop_table('gateway_query_plans')
    op.drop_table('gateway_structured_query_results')
    op.drop_table('gateway_governed_query_executions')
