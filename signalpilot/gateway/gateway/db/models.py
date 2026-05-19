"""SQLAlchemy models for gateway-owned tables.

These tables live in the same PostgreSQL database as the backend tables but are
managed by the gateway's own Alembic migrations (version_table=gateway_alembic_version).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TZDateTime = DateTime(timezone=True)


class GatewayBase(DeclarativeBase):
    pass


class GatewayConnection(GatewayBase):
    __tablename__ = "gateway_connections"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    db_type: Mapped[str] = mapped_column(String(20), nullable=False)
    host: Mapped[str | None] = mapped_column(String(500))
    port: Mapped[int | None] = mapped_column(Integer)
    database: Mapped[str | None] = mapped_column(String(500))
    username: Mapped[str | None] = mapped_column(String(200))
    ssl: Mapped[bool] = mapped_column(Boolean, default=False)
    ssl_config: Mapped[dict | None] = mapped_column(JSON)
    ssh_tunnel: Mapped[dict | None] = mapped_column(JSON)
    # Snowflake
    account: Mapped[str | None] = mapped_column(String(200))
    warehouse: Mapped[str | None] = mapped_column(String(200))
    schema_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(200))
    # BigQuery
    project: Mapped[str | None] = mapped_column(String(200))
    dataset: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(100))
    # Databricks
    http_path: Mapped[str | None] = mapped_column(String(500))
    catalog: Mapped[str | None] = mapped_column(String(200))
    # Metadata
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSON)
    schema_filter_include: Mapped[list | None] = mapped_column(JSON)
    schema_filter_exclude: Mapped[list | None] = mapped_column(JSON)
    schema_refresh_interval: Mapped[int | None] = mapped_column(Integer)
    connection_timeout: Mapped[int | None] = mapped_column(Integer)
    query_timeout: Mapped[int | None] = mapped_column(Integer)
    keepalive_interval: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    last_used: Mapped[float | None] = mapped_column(Float)
    last_schema_refresh: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    # Schema endorsements stored inline
    endorsements: Mapped[dict | None] = mapped_column(JSON)
    # PII redaction: {column_name: "hash"|"mask"|"hide", ...}
    pii_rules: Mapped[dict | None] = mapped_column(JSON)
    pii_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    byok_key_alias: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Health monitor state (persisted across restarts)
    health_last_check: Mapped[float | None] = mapped_column(Float, nullable=True)
    health_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    health_consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_gw_conn_org_name"),
        Index("ix_gw_conn_org_id", "org_id"),
    )

    def to_info_dict(self) -> dict:
        """Convert to a dict matching ConnectionInfo fields."""
        return {
            "id": self.id,
            "name": self.name,
            "db_type": self.db_type,
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "username": self.username,
            "ssl": self.ssl,
            "ssl_config": self.ssl_config,
            "ssh_tunnel": self.ssh_tunnel,
            "account": self.account,
            "warehouse": self.warehouse,
            "schema_name": self.schema_name,
            "role": self.role,
            "project": self.project,
            "dataset": self.dataset,
            "location": self.location,
            "http_path": self.http_path,
            "catalog": self.catalog,
            "description": self.description,
            "tags": self.tags,
            "schema_filter_include": self.schema_filter_include,
            "schema_filter_exclude": self.schema_filter_exclude,
            "schema_refresh_interval": self.schema_refresh_interval,
            "connection_timeout": self.connection_timeout,
            "query_timeout": self.query_timeout,
            "keepalive_interval": self.keepalive_interval,
            "status": self.status or "unknown",
            "last_used": self.last_used,
            "last_schema_refresh": self.last_schema_refresh,
            "created_at": self.created_at,
            "pii_rules": self.pii_rules,
            "pii_enabled": self.pii_enabled or False,
            "org_id": self.org_id,
            "byok_key_alias": self.byok_key_alias,
        }


class GatewayBYOKKey(GatewayBase):
    """Registry of BYOK key-encryption-keys (KEKs) per org.

    Phase 1: table is created but not yet populated via API (read path only).
    Phase 2 will add the encrypt path and API endpoints for key management.
    """

    __tablename__ = "gateway_byok_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    key_alias: Mapped[str] = mapped_column(String(200), nullable=False)
    # "local", "aws_kms", "gcp_kms", "azure_kv"
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # KMS ARN, key URI, etc. — provider-specific config blob
    provider_config: Mapped[dict | None] = mapped_column(JSON)
    # "active", "revoked", "rotating"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    revoked_at: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("org_id", "key_alias", name="uq_gw_byok_org_alias"),
        Index("ix_gw_byok_org_id", "org_id"),
    )


class GatewayCredential(GatewayBase):
    __tablename__ = "gateway_credentials"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    connection_string_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    extras_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # BYOK columns (Phase 1: read path only; Phase 2 adds write path and API)
    # "managed" (existing Fernet) or "byok" (envelope encryption)
    encryption_mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="managed")
    # Wrapped (KMS-encrypted) DEK — only set for BYOK mode
    wrapped_dek: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # FK-like reference to gateway_byok_keys.id — only set for BYOK mode
    byok_key_id: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("org_id", "connection_name", name="uq_gw_cred_org_conn"),
        Index("ix_gw_cred_org_id", "org_id"),
    )


class GatewaySetting(GatewayBase):
    __tablename__ = "gateway_settings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    settings_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())


class GatewayAuditLog(GatewayBase):
    __tablename__ = "gateway_audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    connection_name: Mapped[str | None] = mapped_column(String(100))
    sandbox_id: Mapped[str | None] = mapped_column(String)
    sql_text: Mapped[str | None] = mapped_column(Text)
    tables: Mapped[list | None] = mapped_column(JSON)
    rows_returned: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    block_reason: Mapped[str | None] = mapped_column(String(500))
    duration_ms: Mapped[float | None] = mapped_column(Float)
    agent_id: Mapped[str | None] = mapped_column(String)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    parent_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_gw_audit_org_ts", "org_id", "timestamp"),
        Index("ix_gw_audit_conn", "connection_name"),
    )


class GatewayProject(GatewayBase):
    __tablename__ = "gateway_projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    project_dir: Mapped[str | None] = mapped_column(String(1000))
    storage: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str | None] = mapped_column(String(20))
    db_type: Mapped[str | None] = mapped_column(String(20))
    dbt_version: Mapped[str | None] = mapped_column(String(20))
    model_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[float | None] = mapped_column(Float)
    last_scanned_at: Mapped[float | None] = mapped_column(Float)
    git_remote: Mapped[str | None] = mapped_column(String(500))
    git_branch: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_gw_proj_org_name"),
        Index("ix_gw_proj_org_id", "org_id"),
    )


class GatewayOrg(GatewayBase):
    """Organization record for BYOK key management.

    org_id is the primary key — it is the same string used in
    GatewayConnection.org_id and GatewayBYOKKey.org_id, eliminating any
    identity ambiguity between a UUID id and a name.
    """

    __tablename__ = "gateway_orgs"

    org_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    plan_tier: Mapped[str] = mapped_column(String(20), default="free", server_default="free")
    byok_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    default_byok_key_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class GatewayHealthEvent(GatewayBase):
    """Individual health check / query event for a connection."""

    __tablename__ = "gateway_health_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_gw_health_org_conn_ts", "org_id", "connection_name", "timestamp"),)


class GatewaySessionBudget(GatewayBase):
    """Per-session budget tracking, persisted across restarts."""

    __tablename__ = "gateway_session_budgets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    budget_usd: Mapped[float] = mapped_column(Float, nullable=False)
    spent_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    query_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_activity: Mapped[float] = mapped_column(Float, nullable=False)
    closed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    __table_args__ = (
        UniqueConstraint("org_id", "session_id", name="uq_gw_budget_org_session"),
        Index("ix_gw_budget_org_id", "org_id"),
    )


class GatewayApiKey(GatewayBase):
    __tablename__ = "gateway_api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    key_hash: Mapped[str] = mapped_column(String, nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str | None] = mapped_column(String)
    last_used_at: Mapped[str | None] = mapped_column(String)
    expires_at: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_gw_api_keys_org", "org_id"),
        Index("ix_gw_api_keys_hash", "key_hash"),
    )


class GatewayKnowledgeDoc(GatewayBase):
    """Knowledge Base documents — org/project/connection-scoped markdown docs."""

    __tablename__ = "gateway_knowledge_docs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    proposed_by_agent: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("idx_knowledge_org_scope", "org_id", "scope", "scope_ref"),
        Index("idx_knowledge_org_status", "org_id", "status"),
        Index("idx_knowledge_org_cat", "org_id", "category"),
    )


class GatewayKnowledgeEdit(GatewayBase):
    """Edit history for Knowledge Base documents."""

    __tablename__ = "gateway_knowledge_edits"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    doc_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    body_before: Mapped[str] = mapped_column(Text, nullable=False)
    bytes_before: Mapped[int] = mapped_column(Integer, nullable=False)
    edited_at: Mapped[float] = mapped_column(Float, nullable=False)
    edited_by: Mapped[str | None] = mapped_column(String, nullable=True)
    edit_kind: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        Index("idx_knowledge_edits_doc", "doc_id", "edited_at"),
        Index("idx_knowledge_edits_org", "org_id"),
    )


# ─── Workspace Projects ─────────────────────────────────────────────────────


class GatewayWorkspaceProject(GatewayBase):
    """S3-backed workspace project."""

    __tablename__ = "gateway_workspace_projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    connection_name: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="managed")
    s3_prefix: Mapped[str] = mapped_column(String(500), nullable=False)
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


# ─── Chat ────────────────────────────────────────────────────────────────────


class GatewayChatConversation(GatewayBase):
    """Conversation header for per-user per-project chat."""

    __tablename__ = "gateway_chat_conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String(200))
    agent_session_id: Mapped[str | None] = mapped_column(String)
    model: Mapped[str | None] = mapped_column(String(50))
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_gw_conv_org_user", "org_id", "user_id"),
        Index("ix_gw_conv_org_proj", "org_id", "project_id"),
        Index("ix_gw_conv_updated", "org_id", "updated_at"),
    )


class GatewayChatMessage(GatewayBase):
    """Individual chat message within a conversation."""

    __tablename__ = "gateway_chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_gw_chat_conversation", "conversation_id", "sequence"),
        Index("ix_gw_chat_org_user_proj", "org_id", "user_id", "project_id"),
        Index("ix_gw_chat_org_created", "org_id", "created_at"),
    )


# ─── Agent Runs ──────────────────────────────────────────────────────────────


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


# ─── Notebook Sessions ──────────────────────────────────────────────────────


class GatewayNotebookSession(GatewayBase):
    """One active notebook pod per user."""

    __tablename__ = "gateway_notebook_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String)
    branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    pod_name: Mapped[str | None] = mapped_column(String)
    pod_ip: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="creating")
    last_ping: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_gw_nbsession_org_user"),
        Index("ix_gw_nbsession_org_status", "org_id", "status"),
    )
