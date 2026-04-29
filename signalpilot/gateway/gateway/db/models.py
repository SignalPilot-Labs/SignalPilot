"""SQLAlchemy models for gateway-owned tables.

These tables live in the same PostgreSQL database as the backend tables but are
managed by the gateway's own Alembic migrations (version_table=gateway_alembic_version).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
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
    encryption_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="managed"
    )
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

    __table_args__ = (
        Index("ix_gw_health_org_conn_ts", "org_id", "connection_name", "timestamp"),
    )


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
