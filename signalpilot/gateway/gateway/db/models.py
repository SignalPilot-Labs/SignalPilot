"""SQLAlchemy models for gateway-owned tables.

These tables live in the same PostgreSQL database as the backend tables but are
managed by the gateway's own Alembic migrations (version_table=gateway_alembic_version).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
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
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TZDateTime = DateTime(timezone=True)


class GatewayBase(DeclarativeBase):
    pass


# TLS material lives only in the encrypted credential extras. These fields are
# stripped before the ssl_config metadata column is written and redacted again on
# read so rows written by earlier releases cannot leak through a response.
SSL_SECRET_FIELDS = ("ca_cert", "client_cert", "client_key")


def strip_ssl_secrets(ssl_config: dict | None) -> dict | None:
    """Return ssl_config with certificate/key material removed."""
    if not ssl_config:
        return ssl_config
    return {k: v for k, v in ssl_config.items() if k not in SSL_SECRET_FIELDS}


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
            "ssl_config": strip_ssl_secrets(self.ssl_config),
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
    # KMS ARN, key URI, etc. provider-specific config blob
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
    # Wrapped (KMS-encrypted) DEK: only set for BYOK mode
    wrapped_dek: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # FK-like reference to gateway_byok_keys.id: only set for BYOK mode
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

    org_id is the primary key: it is the same string used in
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


class GatewayUploadSession(GatewayBase):
    """Reserved slot for an in-flight eval multipart upload.

    The bytes go straight to S3, so this row is the only server-side record of
    what a principal was allowed to upload, and the per-principal open-upload
    and concurrent-byte caps are counted from it. It is written before
    CreateMultipartUpload is awaited (upload_id filled in afterwards) so racing
    initiations in any worker or replica contend on one shared reservation.
    """

    __tablename__ = "gateway_upload_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String(500), nullable=False)
    upload_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 8 GB ceiling overflows INTEGER on Postgres.
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    part_lengths: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "key", name="uq_gw_upload_org_key"),
        Index("ix_gw_upload_org_user", "org_id", "user_id"),
        Index("ix_gw_upload_expires", "expires_at"),
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


class GatewaySlackThreadWatch(GatewayBase):
    """Durable Slack thread invitation state.

    A row means SignalPilot was explicitly mentioned in the Slack thread and may
    route later plain replies through intake without another @mention.
    """

    __tablename__ = "gateway_slack_thread_watches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    team_id: Mapped[str] = mapped_column(String(100), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(100), nullable=False)
    thread_ts: Mapped[str] = mapped_column(String(50), nullable=False)
    source_thread_id: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    invited_by_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latest_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    first_event_ts: Mapped[str | None] = mapped_column(String(50), nullable=True)
    latest_event_ts: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("org_id", "team_id", "channel_id", "thread_ts", name="uq_slack_thread_watch_identity"),
        Index("ix_slack_thread_watch_source_thread", "org_id", "source_thread_id"),
        Index("ix_slack_thread_watch_active", "org_id", "team_id", "channel_id", "status"),
    )


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
    # The evaluation binding limits this key to one run and one task.
    # The credential stores the warehouse pin and the proposed document overlay.
    # Request headers cannot define this boundary because the agent controls them.
    eval_run_id: Mapped[str | None] = mapped_column(String(64))
    eval_task_id: Mapped[str | None] = mapped_column(String(200))
    eval_connection: Mapped[str | None] = mapped_column(String(64))
    eval_doc_ids: Mapped[list | None] = mapped_column(JSON)

    __table_args__ = (
        Index("ix_gw_api_keys_org", "org_id"),
        Index("ix_gw_api_keys_hash", "key_hash"),
    )


class GatewayKnowledgeDoc(GatewayBase):
    """Knowledge Base documents: org/project/connection-scoped markdown docs."""

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


class GatewayKnowledgeRetrieval(GatewayBase):
    """Per-retrieval event log: which docs agents actually pull, and how.

    Written fire-and-forget from the hot paths (get_knowledge /
    search_knowledge / REST search). Feeds the retrieval heat-map UI and the
    KB Reflector's usage signal. Pruned after ~90 days by the sync loop.
    """

    __tablename__ = "gateway_knowledge_retrievals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    doc_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    query: Mapped[str | None] = mapped_column(String(300), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ts: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("idx_knowledge_retr_org_doc_ts", "org_id", "doc_id", "ts"),
        Index("idx_knowledge_retr_org_ts", "org_id", "ts"),
    )


class GatewaySchemaWatch(GatewayBase):
    """Scheduled schema-diff watch: introspect a connection on an interval and
    open a GitHub PR documenting any structural drift.

    The last snapshot is stored inline (schema JSON + fingerprint) so diffs
    survive gateway restarts: unlike the in-memory schema_cache history.
    """

    __tablename__ = "gateway_schema_watches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_s: Mapped[int] = mapped_column(Integer, nullable=False, default=86400)
    github_repo: Mapped[str] = mapped_column(String(200), nullable=False)  # owner/name
    github_base_branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_run_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_change_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_pr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "connection_name", "github_repo", name="uq_gw_schema_watch"),
        Index("idx_schema_watch_org", "org_id"),
    )


class GatewayReport(GatewayBase):
    """Rendered HTML reports: org-scoped, optionally grouped by project (scope_ref)."""

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


# Chat.


class GatewayChatConversation(GatewayBase):
    """Conversation header for per-user per-project chat."""

    __tablename__ = "gateway_chat_conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String)
    surface: Mapped[str] = mapped_column(String(20), nullable=False, default="notebook", server_default="notebook")
    # "user" (person-initiated) or "improvement" (system-initiated improvement run)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="user", server_default="user")
    branch: Mapped[str | None] = mapped_column(String(100))
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    per_query_budget_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.25, server_default="0.25")
    chat_budget_usd: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1.0")
    estimated_spend_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    actual_spend_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    reserved_spend_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    forked_from_conversation_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    internal_summary: Mapped[str | None] = mapped_column(Text)
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
        Index(
            "ix_gw_conv_standalone_history",
            "org_id",
            "user_id",
            "surface",
            "status",
            "updated_at",
        ),
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
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_gw_chat_conversation", "conversation_id", "sequence"),
        Index("ix_gw_chat_org_user_proj", "org_id", "user_id", "project_id"),
        Index("ix_gw_chat_org_created", "org_id", "created_at"),
        Index(
            "uq_gw_chat_message_idempotency",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class GatewayChatRun(GatewayBase):
    """Durable standalone-chat execution claimed by the chat worker."""

    __tablename__ = "gateway_chat_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    user_message_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued", server_default="queued")
    retry_of_run_id: Mapped[str | None] = mapped_column(String)
    execution_session_id: Mapped[str | None] = mapped_column(String)
    runtime_archive_id: Mapped[str | None] = mapped_column(String)
    execution_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    public_error_code: Mapped[str | None] = mapped_column(String(100))
    public_error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    terminal_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        Index("ix_gw_chat_runs_queue", "status", "lease_expires_at", "created_at"),
        Index("ix_gw_chat_runs_owner", "org_id", "user_id", "conversation_id"),
        Index(
            "uq_gw_chat_run_nonterminal_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status IN ('queued','running','waiting_for_user','waiting_for_query_approval')"),
            sqlite_where=text("status IN ('queued','running','waiting_for_user','waiting_for_query_approval')"),
        ),
    )


class GatewayChatRunEvent(GatewayBase):
    """Author-visible, redacted event emitted by one standalone run."""

    __tablename__ = "gateway_chat_run_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_gw_chat_run_event_sequence"),
        Index("ix_gw_chat_run_events_owner", "org_id", "user_id", "run_id", "sequence"),
    )


class GatewayChatArtifact(GatewayBase):
    """Immutable standalone-chat artifact snapshot."""

    __tablename__ = "gateway_chat_artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    assistant_message_id: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    binary_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    storage_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="inline", server_default="inline")
    object_key: Mapped[str | None] = mapped_column(Text)
    source_object_key: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    provenance_json: Mapped[dict | None] = mapped_column(JSON)
    freshness_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    assumptions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    exclusions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    caveats: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    parent_artifact_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "kind",
            "filename",
            name="uq_gw_chat_artifact_publication",
        ),
        Index("ix_gw_chat_artifacts_owner", "org_id", "user_id", "conversation_id"),
        Index("ix_gw_chat_artifacts_run", "run_id", "created_at"),
    )


class GatewayChatShareGrant(GatewayBase):
    """Revocable same-organization access grant for one standalone chat."""

    __tablename__ = "gateway_chat_share_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (
        Index(
            "uq_gw_chat_share_active_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
            sqlite_where=text("state = 'active'"),
        ),
        Index(
            "ix_gw_chat_share_lookup",
            "org_id",
            "token_hash",
            "state",
        ),
        Index(
            "ix_gw_chat_share_owner",
            "org_id",
            "owner_user_id",
            "conversation_id",
            "state",
        ),
    )


class GatewayChatStarterCache(GatewayBase):
    """Four starter prompts cached by project metadata checksum."""

    __tablename__ = "gateway_chat_starter_cache"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    metadata_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    questions_json: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "project_id",
            "metadata_checksum",
            name="uq_gw_chat_starters_checksum",
        ),
        Index("ix_gw_chat_starters_project", "org_id", "project_id"),
    )


class GatewayChatUserPreference(GatewayBase):
    """Per-user default selection for the standalone chat surface."""

    __tablename__ = "gateway_chat_user_preferences"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    default_chat_project_id: Mapped[str | None] = mapped_column(String)
    default_per_query_budget_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.25, server_default="0.25"
    )
    default_chat_budget_usd: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1.0")
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_gw_chat_user_preference"),)


class GatewayGovernedQueryExecution(GatewayBase):
    """Durable identity and outcome for every governed database query."""

    __tablename__ = "gateway_governed_query_executions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String)
    conversation_id: Mapped[str | None] = mapped_column(String)
    run_id: Mapped[str | None] = mapped_column(String)
    project_id: Mapped[str | None] = mapped_column(String)
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    plan_id: Mapped[str | None] = mapped_column(String)
    query_path: Mapped[str] = mapped_column(String(30), nullable=False)
    sql_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    warehouse_query_id: Mapped[str | None] = mapped_column(String(500))
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float)
    actual_scan_bytes: Mapped[int | None] = mapped_column(BigInteger)
    actual_output_bytes: Mapped[int | None] = mapped_column(BigInteger)
    execution_ms: Mapped[float | None] = mapped_column(Float)
    row_count: Mapped[int | None] = mapped_column(Integer)
    completeness: Mapped[str | None] = mapped_column(String(20))
    truncation_reason: Mapped[str | None] = mapped_column(String(500))
    public_error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    terminal_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (
        Index("ix_gw_query_execution_scope", "org_id", "user_id", "created_at"),
        Index("ix_gw_query_execution_run", "org_id", "run_id", "created_at"),
        Index("ix_gw_query_execution_hash", "org_id", "connection_name", "sql_hash"),
    )


class GatewayStructuredQueryResult(GatewayBase):
    """Bounded gateway-owned rows and metadata from one governed execution."""

    __tablename__ = "gateway_structured_query_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id: Mapped[str | None] = mapped_column(String, unique=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String)
    conversation_id: Mapped[str | None] = mapped_column(String)
    run_id: Mapped[str | None] = mapped_column(String)
    columns_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    rows_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    preview_rows_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    storage_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="inline", server_default="inline")
    object_key: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    source_result_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    code_hash: Mapped[str | None] = mapped_column(String(64))
    result_origin: Mapped[str] = mapped_column(String(20), nullable=False, default="mcp", server_default="mcp")
    query_row_count: Mapped[int | None] = mapped_column(Integer)
    saved_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_completeness: Mapped[str] = mapped_column(String(20), nullable=False)
    result_completeness: Mapped[str] = mapped_column(String(20), nullable=False)
    display_completeness: Mapped[str] = mapped_column(String(20), nullable=False)
    truncation_reason: Mapped[str | None] = mapped_column(String(500))
    provenance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    freshness_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (Index("ix_gw_structured_result_owner", "org_id", "owner_user_id", "created_at"),)


class GatewayQueryPlan(GatewayBase):
    """Immutable route decision bound to SQL, policy, and one execution scope."""

    __tablename__ = "gateway_query_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String)
    conversation_id: Mapped[str | None] = mapped_column(String)
    run_id: Mapped[str | None] = mapped_column(String)
    project_id: Mapped[str | None] = mapped_column(String)
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    branch: Mapped[str | None] = mapped_column(String(100))
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    execution_need: Mapped[str] = mapped_column(String(20), nullable=False)
    normalized_sql: Mapped[str] = mapped_column(Text, nullable=False)
    sql_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    estimated_scan_rows: Mapped[int | None] = mapped_column(BigInteger)
    estimated_scan_bytes: Mapped[int | None] = mapped_column(BigInteger)
    estimated_output_rows: Mapped[int | None] = mapped_column(BigInteger)
    estimated_output_bytes: Mapped[int | None] = mapped_column(BigInteger)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    estimate_quality: Mapped[str] = mapped_column(String(20), nullable=False)
    route: Mapped[str] = mapped_column(String(30), nullable=False)
    route_reason: Mapped[str] = mapped_column(Text, nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    proposal_id: Mapped[str | None] = mapped_column(String)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    shadow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scout_row_limit: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (
        Index("ix_gw_query_plan_scope", "org_id", "user_id", "run_id", "created_at"),
        Index("ix_gw_query_plan_hash", "org_id", "connection_name", "sql_hash"),
    )


class GatewayRuntimeDataset(GatewayBase):
    """Opaque, expiring Parquet dataset produced by streamed governed execution."""

    __tablename__ = "gateway_runtime_datasets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    plan_id: Mapped[str] = mapped_column(String, nullable=False)
    query_execution_id: Mapped[str] = mapped_column(String, nullable=False)
    schema_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completeness: Mapped[str] = mapped_column(String(20), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "plan_id", name="uq_gw_runtime_dataset_plan"),
        Index("ix_gw_runtime_dataset_owner", "org_id", "owner_user_id", "run_id"),
        Index("ix_gw_runtime_dataset_expiry", "expires_at"),
    )


class GatewayChatRuntimeArchive(GatewayBase):
    """Owner-only static notebook snapshot retained after its kernel stops."""

    __tablename__ = "gateway_chat_runtime_archives"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    source_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    html_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    html_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (Index("ix_gw_chat_archive_owner", "org_id", "user_id", "run_id"),)


class GatewayChatObjectDeletion(GatewayBase):
    """Idempotent asynchronous deletion request for one conversation prefix."""

    __tablename__ = "gateway_chat_object_deletions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    object_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (Index("ix_gw_chat_object_deletion_pending", "status", "created_at"),)


class GatewayQueryProposal(GatewayBase):
    """Durable estimated SQL unit awaiting automatic or explicit approval."""

    __tablename__ = "gateway_query_proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    plan_id: Mapped[str | None] = mapped_column(String)
    query_path: Mapped[str] = mapped_column(String(30), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_sql: Mapped[str] = mapped_column(Text, nullable=False)
    sql_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    estimate_quality: Mapped[str] = mapped_column(String(30), nullable=False)
    estimate_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False, default="chat-budget-v1")
    reserved_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    terminal_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (
        UniqueConstraint("run_id", "sql_hash", name="uq_gw_query_proposal_run_hash"),
        Index("ix_gw_query_proposal_waiting", "org_id", "user_id", "status", "created_at"),
    )


class GatewayQueryApproval(GatewayBase):
    """Idempotent user decision bound to one exact proposed query."""

    __tablename__ = "gateway_query_approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    proposal_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    approver_user_id: Mapped[str] = mapped_column(String, nullable=False)
    approval_scope: Mapped[str] = mapped_column(String(30), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    sql_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    per_query_budget_usd: Mapped[float | None] = mapped_column(Float)
    chat_budget_usd: Mapped[float | None] = mapped_column(Float)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("proposal_id", "approver_user_id", name="uq_gw_query_approval_decision"),
        Index("ix_gw_query_approval_owner", "org_id", "approver_user_id", "created_at"),
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
    """One active notebook pod per user."""

    __tablename__ = "gateway_notebook_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String)
    branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    pod_name: Mapped[str | None] = mapped_column(String)
    pod_ip: Mapped[str | None] = mapped_column(String)
    # pod_ip_internal is the cluster address that the gateway proxy uses.
    # pod_ip is the external NodePort address.
    pod_ip_internal: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="creating")
    last_ping: Mapped[float | None] = mapped_column(Float)
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


# Evaluation harness state.
# Retention windows remove run and task details.
# Accuracy history is the permanent record for the accuracy page.
# S3 stores transcripts, setup logs, and captures under evals/<org>/runs/<run_id>/.


class GatewayEvalConfig(GatewayBase):
    """Store the evaluation harness configuration for one organization."""

    __tablename__ = "gateway_eval_configs"

    org_id: Mapped[str] = mapped_column(String, primary_key=True)
    repo_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    repo_installation_id: Mapped[str | None] = mapped_column(String(64))
    repo_id: Mapped[int | None] = mapped_column(BigInteger)
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="sonnet")
    max_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_preamble: Mapped[str] = mapped_column(Text, nullable=False, default="")
    connection: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    autorun_on_knowledge_add: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Opt-in regression notifications (spec §3.7). Empty list = nobody opted in.
    notify_emails: Mapped[list | None] = mapped_column(JSON)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class GatewayEvalRun(GatewayBase):
    """Store one evaluation harness run.

    Retention removes detail rows after the trace window.
    gateway_eval_accuracy_history stores the permanent record.
    """

    __tablename__ = "gateway_eval_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="preparing")
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String(40))
    doc_ids: Mapped[list | None] = mapped_column(JSON)
    doc_titles: Mapped[list | None] = mapped_column(JSON)
    task_filter: Mapped[list | None] = mapped_column(JSON)
    repo_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    eval_set_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Exact references support regression attribution.
    # A notification identifies a cause only when all other inputs are unchanged.
    eval_set_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    project_repo: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    project_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    build_fingerprint: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    kb_doc_ids: Mapped[list | None] = mapped_column(JSON)
    summary: Mapped[dict | None] = mapped_column(JSON)
    progress: Mapped[dict | None] = mapped_column(JSON)
    coverage: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    artifact_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    artifacts_pruned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    traces_pruned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # A live run refreshes the heartbeat lease.
    # Startup recovery and the reaper classify a run with an expired lease as inactive.
    # This classification releases credentials and branches after an interrupted gateway process.
    lease_expires_at: Mapped[float | None] = mapped_column(Float)
    api_key_id: Mapped[str | None] = mapped_column(String)
    # This hash contains the model, preamble, connection, and task limit.
    # Two runs must have the same hash for regression attribution.
    config_hash: Mapped[str | None] = mapped_column(String(40))

    __table_args__ = (
        Index("ix_gw_evalrun_org_created", "org_id", "created_at"),
        Index("ix_gw_evalrun_org_status", "org_id", "status"),
    )


class GatewayEvalRunTask(GatewayBase):
    """One task inside a run (read-only analytics question or write task)."""

    __tablename__ = "gateway_eval_run_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    task_id: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="query")
    task_class: Mapped[str] = mapped_column(String(10), nullable=False, default="read")
    gt: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    checks: Mapped[list | None] = mapped_column(JSON)
    grade: Mapped[dict | None] = mapped_column(JSON)
    covers: Mapped[list | None] = mapped_column(JSON)
    builds: Mapped[list | None] = mapped_column(JSON)
    capture_spec: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    verdict: Mapped[str | None] = mapped_column(String(20))
    check_results: Mapped[list | None] = mapped_column(JSON)
    answer: Mapped[str | None] = mapped_column(Text)
    duration_s: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[str | None] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40))
    sandbox: Mapped[dict | None] = mapped_column(JSON)
    branch_name: Mapped[str | None] = mapped_column(String(120))
    capture_result: Mapped[dict | None] = mapped_column(JSON)
    observed_tables: Mapped[list | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("run_id", "task_id", name="uq_gw_evaltask_run_task"),
        Index("ix_gw_evaltask_org_run", "org_id", "run_id"),
    )


class GatewayEvalAccuracyHistory(GatewayBase):
    """Store one immutable accuracy record for each completed run.

    Retention does not remove this record.
    """

    __tablename__ = "gateway_eval_accuracy_history"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    eval_set_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    eval_set_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    build_fingerprint: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    tasks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tasks_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accuracy_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    coverage_pct: Mapped[float | None] = mapped_column(Float)
    kb_doc_ids: Mapped[list | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("org_id", "run_id", name="uq_gw_evalacc_org_run"),
        Index("ix_gw_evalacc_org_created", "org_id", "created_at"),
    )


class GatewayEvalRegression(GatewayBase):
    """A detected accuracy drop, attributed (carefully) to KB changes."""

    __tablename__ = "gateway_eval_regressions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    baseline_run_ids: Mapped[list | None] = mapped_column(JSON)
    baseline_accuracy_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    run_accuracy_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    drop_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # "Coincided with", not "caused by", unless sole_change is true.
    suspected_doc_ids: Mapped[list | None] = mapped_column(JSON)
    sole_change: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    flipped_tasks: Mapped[list | None] = mapped_column(JSON)
    notified_at: Mapped[str | None] = mapped_column(String(40))
    recipients: Mapped[list | None] = mapped_column(JSON)
    # These fields identify all differences between the baseline and this run.
    # suspected_doc_ids contains both added and removed identifiers.
    # other_changes contains model and prompt configuration differences.
    added_doc_ids: Mapped[list | None] = mapped_column(JSON)
    removed_doc_ids: Mapped[list | None] = mapped_column(JSON)
    other_changes: Mapped[list | None] = mapped_column(JSON)

    __table_args__ = (Index("ix_gw_evalreg_org_created", "org_id", "created_at"),)


# Automated improvement runs.


class GatewayImprovementRun(GatewayBase):
    """One system-initiated improvement run attempt per org per ET calendar day.

    A row is written for every consumed day slot — seeded, skipped (no eligible
    project), or failed — so the (org_id, started_et_date) uniqueness makes
    double-fires impossible even across processes.
    """

    __tablename__ = "gateway_improvement_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String)
    conversation_id: Mapped[str | None] = mapped_column(String)
    run_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued", server_default="queued")
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled", server_default="scheduled")
    detail_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    # The America/New_York calendar date (YYYY-MM-DD) this run counts for.
    # ET calendar day ("2026-08-11") for nightly slots; manual triggers use a
    # longer unique tag so they never consume the nightly slot.
    started_et_date: Mapped[str] = mapped_column(String(40), nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "started_et_date", name="uq_gw_improvement_org_day"),
        Index("ix_gw_improvement_org_created", "org_id", "created_at"),
    )
