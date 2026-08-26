"""eval configs, runs, tasks, accuracy history, regressions

Part of the initial Alembic baseline: this revision creates the evals
tables exactly as the gateway models define them today.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('gateway_eval_configs',
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('repo_url', sa.String(length=2048), nullable=False),
    sa.Column('repo_installation_id', sa.String(length=64), nullable=True),
    sa.Column('repo_id', sa.BigInteger(), nullable=True),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('max_tasks', sa.Integer(), nullable=False),
    sa.Column('prompt_preamble', sa.Text(), nullable=False),
    sa.Column('connection', sa.String(length=64), nullable=False),
    sa.Column('autorun_on_knowledge_add', sa.Boolean(), nullable=False),
    sa.Column('notify_emails', sa.JSON(), nullable=True),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('org_id')
    )
    op.create_table('gateway_eval_runs',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('trigger', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.Column('finished_at', sa.String(length=40), nullable=True),
    sa.Column('doc_ids', sa.JSON(), nullable=True),
    sa.Column('doc_titles', sa.JSON(), nullable=True),
    sa.Column('task_filter', sa.JSON(), nullable=True),
    sa.Column('repo_url', sa.String(length=2048), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('eval_set_name', sa.String(length=200), nullable=False),
    sa.Column('eval_set_ref', sa.String(length=64), nullable=False),
    sa.Column('project_repo', sa.String(length=2048), nullable=False),
    sa.Column('project_ref', sa.String(length=64), nullable=False),
    sa.Column('build_fingerprint', sa.String(length=80), nullable=False),
    sa.Column('kb_doc_ids', sa.JSON(), nullable=True),
    sa.Column('summary', sa.JSON(), nullable=True),
    sa.Column('progress', sa.JSON(), nullable=True),
    sa.Column('coverage', sa.JSON(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('artifact_bytes', sa.BigInteger(), nullable=False),
    sa.Column('artifacts_pruned', sa.Boolean(), nullable=False),
    sa.Column('traces_pruned', sa.Boolean(), nullable=False),
    sa.Column('lease_expires_at', sa.Float(), nullable=True),
    sa.Column('api_key_id', sa.String(), nullable=True),
    sa.Column('config_hash', sa.String(length=40), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_gw_evalrun_org_created', 'gateway_eval_runs', ['org_id', 'created_at'], unique=False)
    op.create_index('ix_gw_evalrun_org_status', 'gateway_eval_runs', ['org_id', 'status'], unique=False)
    op.create_table('gateway_eval_run_tasks',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('task_id', sa.String(length=200), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('task_class', sa.String(length=10), nullable=False),
    sa.Column('gt', sa.String(length=200), nullable=False),
    sa.Column('checks', sa.JSON(), nullable=True),
    sa.Column('grade', sa.JSON(), nullable=True),
    sa.Column('covers', sa.JSON(), nullable=True),
    sa.Column('builds', sa.JSON(), nullable=True),
    sa.Column('capture_spec', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('verdict', sa.String(length=20), nullable=True),
    sa.Column('check_results', sa.JSON(), nullable=True),
    sa.Column('answer', sa.Text(), nullable=True),
    sa.Column('duration_s', sa.Float(), nullable=True),
    sa.Column('started_at', sa.String(length=40), nullable=True),
    sa.Column('finished_at', sa.String(length=40), nullable=True),
    sa.Column('sandbox', sa.JSON(), nullable=True),
    sa.Column('branch_name', sa.String(length=120), nullable=True),
    sa.Column('capture_result', sa.JSON(), nullable=True),
    sa.Column('observed_tables', sa.JSON(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'task_id', name='uq_gw_evaltask_run_task')
    )
    op.create_index('ix_gw_evaltask_org_run', 'gateway_eval_run_tasks', ['org_id', 'run_id'], unique=False)
    op.create_table('gateway_eval_accuracy_history',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.Column('trigger', sa.String(length=20), nullable=False),
    sa.Column('eval_set_name', sa.String(length=200), nullable=False),
    sa.Column('eval_set_ref', sa.String(length=64), nullable=False),
    sa.Column('build_fingerprint', sa.String(length=80), nullable=False),
    sa.Column('tasks_total', sa.Integer(), nullable=False),
    sa.Column('tasks_passed', sa.Integer(), nullable=False),
    sa.Column('accuracy_pct', sa.Float(), nullable=False),
    sa.Column('coverage_pct', sa.Float(), nullable=True),
    sa.Column('kb_doc_ids', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'run_id', name='uq_gw_evalacc_org_run')
    )
    op.create_index('ix_gw_evalacc_org_created', 'gateway_eval_accuracy_history', ['org_id', 'created_at'], unique=False)
    op.create_table('gateway_eval_regressions',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.Column('baseline_run_ids', sa.JSON(), nullable=True),
    sa.Column('baseline_accuracy_pct', sa.Float(), nullable=False),
    sa.Column('run_accuracy_pct', sa.Float(), nullable=False),
    sa.Column('drop_pct', sa.Float(), nullable=False),
    sa.Column('suspected_doc_ids', sa.JSON(), nullable=True),
    sa.Column('sole_change', sa.Boolean(), nullable=False),
    sa.Column('flipped_tasks', sa.JSON(), nullable=True),
    sa.Column('notified_at', sa.String(length=40), nullable=True),
    sa.Column('recipients', sa.JSON(), nullable=True),
    sa.Column('added_doc_ids', sa.JSON(), nullable=True),
    sa.Column('removed_doc_ids', sa.JSON(), nullable=True),
    sa.Column('other_changes', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_gw_evalreg_org_created', 'gateway_eval_regressions', ['org_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_gw_evalreg_org_created', table_name='gateway_eval_regressions')
    op.drop_index('ix_gw_evalacc_org_created', table_name='gateway_eval_accuracy_history')
    op.drop_index('ix_gw_evaltask_org_run', table_name='gateway_eval_run_tasks')
    op.drop_index('ix_gw_evalrun_org_status', table_name='gateway_eval_runs')
    op.drop_index('ix_gw_evalrun_org_created', table_name='gateway_eval_runs')
    op.drop_table('gateway_eval_regressions')
    op.drop_table('gateway_eval_accuracy_history')
    op.drop_table('gateway_eval_run_tasks')
    op.drop_table('gateway_eval_runs')
    op.drop_table('gateway_eval_configs')
