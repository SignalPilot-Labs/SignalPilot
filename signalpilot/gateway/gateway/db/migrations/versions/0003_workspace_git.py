"""workspace projects, branches, revisions, leases, GitHub app

Part of the initial Alembic baseline: this revision creates the workspace_git
tables exactly as the gateway models define them today.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('gateway_workspace_projects',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('connection_name', sa.String(length=100), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('tags', sa.JSON(), nullable=True),
    sa.Column('settings', sa.JSON(), nullable=True),
    sa.Column('file_count', sa.Integer(), nullable=False),
    sa.Column('total_bytes', sa.Integer(), nullable=False),
    sa.Column('default_branch', sa.String(length=100), nullable=False),
    sa.Column('protected_branches', sa.JSON(), nullable=True),
    sa.Column('git_remote', sa.String(length=500), nullable=True),
    sa.Column('created_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'name', name='uq_gw_wsproj_org_name')
    )
    op.create_index('ix_gw_wsproj_org_id', 'gateway_workspace_projects', ['org_id'], unique=False)
    op.create_index('ix_gw_wsproj_org_status', 'gateway_workspace_projects', ['org_id', 'status'], unique=False)
    op.create_table('gateway_project_branches',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('created_from', sa.String(length=100), nullable=True),
    sa.Column('is_protected', sa.Boolean(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('file_count', sa.Integer(), nullable=False),
    sa.Column('total_bytes', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'name', name='uq_gw_branch_proj_name')
    )
    op.create_index('ix_gw_branch_org_id', 'gateway_project_branches', ['org_id'], unique=False)
    op.create_index('ix_gw_branch_project_id', 'gateway_project_branches', ['project_id'], unique=False)
    op.create_table('gateway_workspace_revisions',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('branch', sa.String(length=100), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('parent_revision', sa.Integer(), nullable=True),
    sa.Column('manifest_key', sa.String(length=500), nullable=False),
    sa.Column('file_count', sa.Integer(), nullable=False),
    sa.Column('total_bytes', sa.Integer(), nullable=False),
    sa.Column('message', sa.String(length=500), nullable=True),
    sa.Column('created_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('export_commit_sha', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'branch', 'revision', name='uq_gw_wsrev_proj_branch_rev')
    )
    op.create_index('ix_gw_wsrev_org_project', 'gateway_workspace_revisions', ['org_id', 'project_id'], unique=False)
    op.create_index('ix_gw_wsrev_proj_branch', 'gateway_workspace_revisions', ['project_id', 'branch'], unique=False)
    op.create_table('gateway_workspace_leases',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('branch', sa.String(length=100), nullable=False),
    sa.Column('holder', sa.String(), nullable=False),
    sa.Column('session_id', sa.String(), nullable=True),
    sa.Column('expires_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'branch', name='uq_gw_wslease_proj_branch')
    )
    op.create_index('ix_gw_wslease_org', 'gateway_workspace_leases', ['org_id'], unique=False)
    op.create_table('gateway_github_installations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('github_installation_id', sa.Integer(), nullable=False),
    sa.Column('github_account_login', sa.String(length=200), nullable=False),
    sa.Column('github_account_type', sa.String(length=20), nullable=False),
    sa.Column('access_token_enc', sa.LargeBinary(), nullable=True),
    sa.Column('token_expires_at', sa.Float(), nullable=True),
    sa.Column('permissions', sa.JSON(), nullable=True),
    sa.Column('authorized_repository_ids', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'github_installation_id', name='uq_gw_ghinstall_org_install')
    )
    op.create_index('ix_gw_ghinstall_org_id', 'gateway_github_installations', ['org_id'], unique=False)
    op.create_table('gateway_github_repo_links',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('org_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('installation_id', sa.String(), nullable=False),
    sa.Column('repo_full_name', sa.String(length=500), nullable=False),
    sa.Column('repo_id', sa.Integer(), nullable=False),
    sa.Column('default_branch', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('last_sync_at', sa.Float(), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'project_id', name='uq_gw_ghrepo_org_project')
    )
    op.create_index('ix_gw_ghrepo_installation', 'gateway_github_repo_links', ['installation_id'], unique=False)
    op.create_index('ix_gw_ghrepo_org_id', 'gateway_github_repo_links', ['org_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_gw_ghrepo_org_id', table_name='gateway_github_repo_links')
    op.drop_index('ix_gw_ghrepo_installation', table_name='gateway_github_repo_links')
    op.drop_index('ix_gw_ghinstall_org_id', table_name='gateway_github_installations')
    op.drop_index('ix_gw_wslease_org', table_name='gateway_workspace_leases')
    op.drop_index('ix_gw_wsrev_proj_branch', table_name='gateway_workspace_revisions')
    op.drop_index('ix_gw_wsrev_org_project', table_name='gateway_workspace_revisions')
    op.drop_index('ix_gw_branch_project_id', table_name='gateway_project_branches')
    op.drop_index('ix_gw_branch_org_id', table_name='gateway_project_branches')
    op.drop_index('ix_gw_wsproj_org_status', table_name='gateway_workspace_projects')
    op.drop_index('ix_gw_wsproj_org_id', table_name='gateway_workspace_projects')
    op.drop_table('gateway_github_repo_links')
    op.drop_table('gateway_github_installations')
    op.drop_table('gateway_workspace_leases')
    op.drop_table('gateway_workspace_revisions')
    op.drop_table('gateway_project_branches')
    op.drop_table('gateway_workspace_projects')
