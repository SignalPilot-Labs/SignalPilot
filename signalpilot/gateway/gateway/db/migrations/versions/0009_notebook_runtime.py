"""notebook sessions (runtime v2) and improvement runs

Part of the initial Alembic baseline: this revision creates the notebook_runtime
tables exactly as the gateway models define them today.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('gateway_notebook_sessions',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('branch', sa.String(length=100), nullable=False),
    sa.Column('backend', sa.String(length=20), nullable=False),
    sa.Column('runtime_handle', sa.String(length=200), nullable=True),
    sa.Column('upstream_url', sa.Text(), nullable=True),
    sa.Column('snapshot_id', sa.String(length=200), nullable=True),
    sa.Column('access_token_enc', sa.LargeBinary(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('last_ping', sa.Float(), nullable=True),
    sa.Column('last_extend_at', sa.Float(), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'user_id', name='uq_gw_nbsession_org_user')
    )
    op.create_index('ix_gw_nbsession_org_status', 'gateway_notebook_sessions', ['org_id', 'status'], unique=False)
    op.create_table('gateway_improvement_runs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('conversation_id', sa.String(), nullable=True),
    sa.Column('run_id', sa.String(), nullable=True),
    sa.Column('status', sa.String(length=30), server_default='queued', nullable=False),
    sa.Column('trigger', sa.String(length=20), server_default='scheduled', nullable=False),
    sa.Column('detail_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_et_date', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'started_et_date', name='uq_gw_improvement_org_day')
    )
    op.create_index('ix_gw_improvement_org_created', 'gateway_improvement_runs', ['org_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_gw_improvement_org_created', table_name='gateway_improvement_runs')
    op.drop_index('ix_gw_nbsession_org_status', table_name='gateway_notebook_sessions')
    op.drop_table('gateway_improvement_runs')
    op.drop_table('gateway_notebook_sessions')
