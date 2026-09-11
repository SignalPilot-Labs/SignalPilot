"""Define agent run, notebook session, secret, GitHub, and dbt manifest models."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Float,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import GatewayBase

# Agent Runs.


class GatewayAgentRun(GatewayBase):
    """Agent execution tracking."""

    __tablename__ = "gateway_agent_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String)
    project_id: Mapped[str | None] = mapped_column(String)
    conversation_id: Mapped[str | None] = mapped_column(String)
    agent_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    input_json: Mapped[dict | None] = mapped_column(JSON)
    output_json: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[float | None] = mapped_column(Float)
    completed_at: Mapped[float | None] = mapped_column(Float)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_gw_arun_org_status", "org_id", "status"),
        Index("ix_gw_arun_org_proj", "org_id", "project_id"),
        Index("ix_gw_arun_org_created", "org_id", "created_at"),
        Index("ix_gw_arun_conversation", "conversation_id"),
    )


# Notebook Sessions.


class GatewayNotebookSession(GatewayBase):
    """One notebook compute session per (org, user).

    Runtime v2: compute is a sandbox VM (or the local direct container), never
    a pod. `runtime_handle` is the provider handle (sandbox name), reattachable
    by any gateway worker. `upstream_url` is the base URL the proxy dials.
    Status: creating | running | snapshotted | stopped | error.
    """

    __tablename__ = "gateway_notebook_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String)
    branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    backend: Mapped[str] = mapped_column(String(20), nullable=False, default="vercel")
    runtime_handle: Mapped[str | None] = mapped_column(String(200))
    upstream_url: Mapped[str | None] = mapped_column(Text)
    snapshot_id: Mapped[str | None] = mapped_column(String(200))
    access_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="creating")
    last_ping: Mapped[float | None] = mapped_column(Float)
    last_extend_at: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_gw_nbsession_org_user"),
        Index("ix_gw_nbsession_org_status", "org_id", "status"),
    )


# GitHub App Installations.


class GatewayUserSecrets(GatewayBase):
    """Per-user secrets: encrypted at rest."""

    __tablename__ = "gateway_user_secrets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    anthropic_api_key_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_gw_usersecrets_org_user"),
        Index("ix_gw_usersecrets_org_id", "org_id"),
    )


class GatewayOrgSecrets(GatewayBase):
    """Org-scoped secrets: encrypted at rest."""

    __tablename__ = "gateway_org_secrets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    anthropic_api_key_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (Index("ix_gw_orgsecrets_org_id", "org_id"),)


class GatewayGitHubInstallation(GatewayBase):
    """GitHub App installation linked to an org."""

    __tablename__ = "gateway_github_installations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    github_installation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    github_account_login: Mapped[str] = mapped_column(String(200), nullable=False)
    github_account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    access_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    token_expires_at: Mapped[float | None] = mapped_column(Float)
    permissions: Mapped[dict | None] = mapped_column(JSON)
    # These repository identifiers record the installation authorization scope.
    # New and refreshed installation tokens remain restricted to this set.
    # NULL requires the installation to reconnect before token issuance.
    authorized_repository_ids: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "github_installation_id", name="uq_gw_ghinstall_org_install"),
        Index("ix_gw_ghinstall_org_id", "org_id"),
    )


class GatewayGitHubRepoLink(GatewayBase):
    """Links a workspace project to a GitHub repo."""

    __tablename__ = "gateway_github_repo_links"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    installation_id: Mapped[str] = mapped_column(String, nullable=False)
    repo_full_name: Mapped[str] = mapped_column(String(500), nullable=False)
    repo_id: Mapped[int] = mapped_column(Integer, nullable=False)
    default_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    last_sync_at: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "project_id", name="uq_gw_ghrepo_org_project"),
        Index("ix_gw_ghrepo_org_id", "org_id"),
        Index("ix_gw_ghrepo_installation", "installation_id"),
    )


class GatewayDbtManifest(GatewayBase):
    """One dbt-map compile job per (project, branch, workspace revision).

    The compiled artifacts (gzipped manifest.json + distilled lineage graph)
    live in workspace S3 under the project prefix; this row is the index,
    job-status record, and dedup claim. The unique constraint doubles as the
    cross-process slot claim: exactly one compile per revision.
    """

    __tablename__ = "gateway_dbt_manifests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    branch: Mapped[str] = mapped_column(String(200), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    error: Mapped[str | None] = mapped_column(Text)
    dbt_version: Mapped[str | None] = mapped_column(String(40))
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manifest_key: Mapped[str | None] = mapped_column(String(500))
    graph_key: Mapped[str | None] = mapped_column(String(500))
    # Per-node raw/compiled SQL artifact; null for maps compiled before 0025.
    sql_key: Mapped[str | None] = mapped_column(String(500))
    manifest_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # A live compile refreshes the lease; the reaper fails runs whose gateway
    # process died mid-compile so the UI never shows an eternal "running".
    lease_expires_at: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "branch", "revision", name="uq_gw_dbtmanifest_proj_branch_rev"),
        Index("ix_gw_dbtmanifest_org_project", "org_id", "project_id"),
    )
