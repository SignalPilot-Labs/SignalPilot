"""Define workspace project, branch, revision, and lease models."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import GatewayBase

# Workspace Projects.


class GatewayWorkspaceProject(GatewayBase):
    """Git-backed workspace project."""

    __tablename__ = "gateway_workspace_projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    connection_name: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="managed")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    tags: Mapped[list | None] = mapped_column(JSON)
    settings: Mapped[dict | None] = mapped_column(JSON)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    default_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    protected_branches: Mapped[list | None] = mapped_column(JSON)
    git_remote: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_gw_wsproj_org_name"),
        Index("ix_gw_wsproj_org_id", "org_id"),
        Index("ix_gw_wsproj_org_status", "org_id", "status"),
    )


class GatewayProjectBranch(GatewayBase):
    """Branch within a workspace project."""

    __tablename__ = "gateway_project_branches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_from: Mapped[str | None] = mapped_column(String(100))
    is_protected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_gw_branch_proj_name"),
        Index("ix_gw_branch_project_id", "project_id"),
        Index("ix_gw_branch_org_id", "org_id"),
    )


class GatewayWorkspaceRevision(GatewayBase):
    """One immutable manifest revision of a project branch.

    The UNIQUE (project_id, branch, revision) constraint IS the compare-and-
    swap: a commit inserts base+1 and a stale base loses with an integrity
    error. Revision numbers are therefore strictly monotonic per branch.
    """

    __tablename__ = "gateway_workspace_revisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    branch: Mapped[str] = mapped_column(String(100), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision: Mapped[int | None] = mapped_column(Integer)
    manifest_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    # Export bookkeeping: the git commit this revision was exported as, if any.
    export_commit_sha: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint("project_id", "branch", "revision", name="uq_gw_wsrev_proj_branch_rev"),
        Index("ix_gw_wsrev_org_project", "org_id", "project_id"),
        Index("ix_gw_wsrev_proj_branch", "project_id", "branch"),
    )


class GatewayWorkspaceLease(GatewayBase):
    """Single-writer lease per (project, branch). TTL-expired rows are
    reclaimable; read-only sessions never take one."""

    __tablename__ = "gateway_workspace_leases"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    branch: Mapped[str] = mapped_column(String(100), nullable=False)
    holder: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str | None] = mapped_column(String)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "branch", name="uq_gw_wslease_proj_branch"),
        Index("ix_gw_wslease_org", "org_id"),
    )


class GatewayUserSession(GatewayBase):
    """Tracks which branch a user is on per project."""

    __tablename__ = "gateway_user_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    active_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", "project_id", name="uq_gw_session_org_user_proj"),
        Index("ix_gw_session_org_user", "org_id", "user_id"),
    )
