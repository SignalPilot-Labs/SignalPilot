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


class GatewayNotionIntegration(GatewayBase):
    """Notion integration configuration scoped by org."""

    __tablename__ = "gateway_notion_integrations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    api_key_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    search_page_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    report_parent_page_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_gw_notion_org_name"),
        Index("ix_gw_notion_org_id", "org_id"),
    )

    def to_info_dict(self) -> dict:
        """Convert to a dict matching NotionIntegrationInfo fields."""
        return {
            "id": self.id,
            "name": self.name,
            "search_page_ids": self.search_page_ids or [],
            "report_parent_page_id": self.report_parent_page_id,
            "status": self.status or "unknown",
            "created_at": self.created_at,
            "org_id": self.org_id,
        }


class NotionInstallation(GatewayBase):
    """OAuth-installed Notion public connection scoped by org."""

    __tablename__ = "notion_installations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    workspace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    workspace_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bot_id: Mapped[str] = mapped_column(String(100), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    access_token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    owner: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="connected", server_default="connected")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("org_id", "workspace_id", "bot_id", name="uq_notion_install_org_workspace_bot"),
        Index("ix_notion_install_org_status", "org_id", "status"),
        Index("ix_notion_install_workspace", "workspace_id"),
    )


class NotionInstallationConfig(GatewayBase):
    """Provisioning metadata for a Notion OAuth installation."""

    __tablename__ = "notion_installation_config"

    installation_id: Mapped[str] = mapped_column(String, primary_key=True)
    parent_page_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trigger_page_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requests_data_source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requests_database_page_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    default_project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    default_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main", server_default="main")
    analysis_branch_mode: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="per_request",
        server_default="per_request",
    )


class NotionWebhookDelivery(GatewayBase):
    """Idempotency and audit record for Notion webhook deliveries."""

    __tablename__ = "notion_webhook_deliveries"

    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    installation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    org_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_notion_delivery_install", "installation_id"),
        Index("ix_notion_delivery_org_status", "org_id", "status"),
    )


class NotionDeliverable(GatewayBase):
    """Link a Notion HTML deliverable block to the report and analysis request."""

    __tablename__ = "notion_deliverables"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    installation_id: Mapped[str] = mapped_column(String, nullable=False)
    page_id: Mapped[str] = mapped_column(String(100), nullable=False)
    request_page_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    discussion_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_id: Mapped[str] = mapped_column(String(120), nullable=False)
    report_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="report", server_default="report")
    embed_block_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_upload_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    context_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    latest_update_id: Mapped[str | None] = mapped_column(String, nullable=True)
    latest_file_upload_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latest_html_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_notion_deliverables_org_request", "org_id", "request_id"),
        Index("ix_notion_deliverables_report", "org_id", "report_id"),
        Index("ix_notion_deliverables_embed", "installation_id", "embed_block_id"),
        Index("ix_notion_deliverables_install", "installation_id", "created_at"),
    )


class NotionDeliverableContextSnapshot(GatewayBase):
    """Immutable source context captured when a Notion HTML deliverable is created."""

    __tablename__ = "notion_deliverable_context_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    deliverable_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    request_id: Mapped[str] = mapped_column(String(120), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    base_notebook_code: Mapped[str] = mapped_column(Text, nullable=False)
    base_chat_events: Mapped[list | None] = mapped_column(JSON)
    base_final_packet: Mapped[dict | None] = mapped_column(JSON)
    base_notebook_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_notebook_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_notion_deliverable_context_deliverable", "deliverable_id", "created_at"),
        Index("ix_notion_deliverable_context_org_request", "org_id", "request_id"),
    )


class NotionDeliverableUpdate(GatewayBase):
    """Lifecycle record for a follow-up refresh/edit of an existing Notion deliverable."""

    __tablename__ = "notion_deliverable_updates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    deliverable_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", server_default="running")
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    render_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    ephemeral_run_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    old_file_upload_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    new_file_upload_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    html_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_notion_deliverable_updates_deliverable", "deliverable_id", "created_at"),
        Index("ix_notion_deliverable_updates_org_status", "org_id", "status"),
    )


class NotionOAuthState(GatewayBase):
    """Short-lived OAuth state for CSRF protection and post-install redirect."""

    __tablename__ = "notion_oauth_states"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    redirect_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    __table_args__ = (Index("ix_notion_oauth_states_expires", "expires_at"),)


class SlackInstallation(GatewayBase):
    """OAuth-installed Slack app scoped by org."""

    __tablename__ = "slack_installations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    team_id: Mapped[str] = mapped_column(String(100), nullable=False)
    team_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enterprise_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enterprise_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    app_id: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    bot_user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    authed_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bot_access_token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="connected", server_default="connected")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("org_id", "team_id", "app_id", name="uq_slack_install_org_team_app"),
        Index("ix_slack_install_team", "team_id"),
        Index("ix_slack_install_org_status", "org_id", "status"),
    )


class SlackInstallationConfig(GatewayBase):
    """Setup metadata for a Slack OAuth installation."""

    __tablename__ = "slack_installation_config"

    installation_id: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    default_project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    default_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main", server_default="main")
    analysis_branch_mode: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="per_request",
        server_default="per_request",
    )
    allowed_channel_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class SlackOAuthState(GatewayBase):
    """Short-lived Slack OAuth state for CSRF protection and post-install redirect."""

    __tablename__ = "slack_oauth_states"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    redirect_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    __table_args__ = (Index("ix_slack_oauth_states_expires", "expires_at"),)


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


class GatewayReport(GatewayBase):
    """Rendered HTML reports — org-scoped, optionally grouped by project (scope_ref)."""

    __tablename__ = "gateway_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    scope_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="report", server_default="report")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    data_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    proposed_by_agent: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("idx_reports_org_created", "org_id", "created_at"),
        Index("idx_reports_org_scope", "org_id", "scope_ref"),
        Index("idx_reports_org_kind", "org_id", "kind", "created_at"),
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


class GatewayChatTraceThread(GatewayBase):
    """Durable agent trace thread metadata for notebook-originated chats."""

    __tablename__ = "gateway_chat_trace_threads"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    thread_id: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    notebook_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notion_request_page_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notion_discussion_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("org_id", "thread_id", name="uq_gw_trace_thread_org"),
        Index("ix_gw_trace_threads_session_org", "org_id", "session_id", "updated_at"),
        Index("ix_gw_trace_threads_source_org", "org_id", "source", "updated_at"),
    )


class GatewayChatTraceEvent(GatewayBase):
    """Ordered trace event within a durable notebook chat thread."""

    __tablename__ = "gateway_chat_trace_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    thread_id: Mapped[str] = mapped_column(String, nullable=False)
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    tool_input_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    tool_call_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    is_error: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    turn: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("org_id", "thread_id", "idx", name="uq_gw_trace_event_org_idx"),
        Index("ix_gw_trace_events_thread_idx_org", "org_id", "thread_id", "idx"),
    )


class GatewayAnalysisTrail(GatewayBase):
    """Durable metadata for external-source notebook analyses."""

    __tablename__ = "gateway_analysis_trails"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(300), nullable=False)
    runtime_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    branch: Mapped[str] = mapped_column(String(100), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    notebook_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    latest_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_thread_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_request_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    analysis_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "source", "request_id", name="uq_gw_analysis_trail_request"),
        Index("ix_gw_analysis_trail_thread", "org_id", "thread_id"),
        Index("ix_gw_analysis_trail_project", "org_id", "project_id", "branch"),
        Index("ix_gw_analysis_trail_source_status", "org_id", "source", "status"),
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
    # pod_ip_internal: raw pod IP used by the gateway proxy to reach the pod inside
    # the cluster. Distinct from pod_ip which is the legacy NodePort address.
    pod_ip_internal: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token: Mapped[str | None] = mapped_column(String)
    access_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="creating")
    last_ping: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_gw_nbsession_org_user"),
        Index("ix_gw_nbsession_org_status", "org_id", "status"),
    )


# ─── GitHub App Installations ──────────────────────────────────────────────


class GatewayUserSecrets(GatewayBase):
    """Per-user secrets — encrypted at rest."""

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
