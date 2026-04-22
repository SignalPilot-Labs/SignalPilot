"""Pydantic models shared across the gateway."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ─── Settings ────────────────────────────────────────────────────────────────

class SandboxProvider(str, Enum):
    local = "local"       # local sandbox_manager at socket/http
    remote = "remote"     # BYOS -- remote sandbox manager HTTP endpoint


class GatewaySettings(BaseModel):
    # Sandbox configuration (BYOS -- Bring Your Own Sandbox)
    sandbox_provider: SandboxProvider = SandboxProvider.local
    sandbox_manager_url: str = "http://localhost:8180"
    sandbox_api_key: str | None = None

    # Governance defaults
    default_row_limit: int = 10_000
    default_budget_usd: float = 10.0
    default_timeout_seconds: int = 30
    max_concurrent_sandboxes: int = 10

    # Governance — blocked tables (Feature #19)
    blocked_tables: list[str] = Field(default_factory=list)

    # Gateway
    gateway_url: str = "http://localhost:3300"
    api_key: str | None = None


# ─── Connections ─────────────────────────────────────────────────────────────

class DBType(str, Enum):
    postgres = "postgres"
    duckdb = "duckdb"
    mysql = "mysql"
    snowflake = "snowflake"
    bigquery = "bigquery"
    redshift = "redshift"
    clickhouse = "clickhouse"
    databricks = "databricks"
    mssql = "mssql"
    trino = "trino"
    sqlite = "sqlite"


class SSHTunnelConfig(BaseModel):
    """SSH tunnel configuration for connecting through bastion hosts."""
    enabled: bool = False
    host: str | None = Field(default=None, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=128)
    auth_method: str = "password"  # password | key | agent
    password: str | None = Field(default=None, max_length=1024)
    private_key: str | None = Field(default=None, max_length=16384)
    private_key_passphrase: str | None = Field(default=None, max_length=1024)
    # HTTP proxy for SSH (HEX pattern) — for VPCs that block direct SSH
    proxy_host: str | None = Field(default=None, max_length=255)
    proxy_port: int = Field(default=3128, ge=1, le=65535)


class SSLConfig(BaseModel):
    """SSL/TLS configuration for database connections."""
    enabled: bool = False
    mode: str = "require"  # disable | allow | prefer | require | verify-ca | verify-full
    ca_cert: str | None = Field(default=None, max_length=32768)  # PEM-encoded CA certificate
    client_cert: str | None = Field(default=None, max_length=32768)  # PEM-encoded client certificate
    client_key: str | None = Field(default=None, max_length=32768)  # PEM-encoded client private key


class ConnectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    db_type: DBType
    # ─── Common fields (host/port style) ────────────────────────────
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, max_length=128)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=1024)
    # ─── Connection string mode (alternative to individual fields) ──
    connection_string: str | None = Field(default=None, max_length=4096)
    # ─── SSL/TLS ────────────────────────────────────────────────────
    ssl: bool = False
    ssl_config: SSLConfig | None = None
    # ─── SSH tunnel ─────────────────────────────────────────────────
    ssh_tunnel: SSHTunnelConfig | None = None
    # ─── Snowflake-specific ─────────────────────────────────────────
    account: str | None = Field(default=None, max_length=255)  # Snowflake account identifier
    warehouse: str | None = Field(default=None, max_length=128)
    schema_name: str | None = Field(default=None, max_length=128)  # default schema
    role: str | None = Field(default=None, max_length=128)  # Snowflake role
    # ─── BigQuery-specific ──────────────────────────────────────────
    project: str | None = Field(default=None, max_length=255)  # GCP project ID
    dataset: str | None = Field(default=None, max_length=255)  # default dataset
    credentials_json: str | None = Field(default=None, max_length=65536)  # service account JSON
    location: str | None = Field(default=None, max_length=64)  # BQ location: US, EU, us-east1, etc.
    maximum_bytes_billed: int | None = Field(
        default=None, ge=0,
        description="BigQuery safety limit: query fails if estimated scan exceeds this (bytes). "
                    "Recommended: 10GB = 10737418240 for dev, 100GB for prod.",
    )
    # ─── Databricks-specific ────────────────────────────────────────
    http_path: str | None = Field(default=None, max_length=512)  # SQL endpoint path
    access_token: str | None = Field(default=None, max_length=1024)  # PAT token
    catalog: str | None = Field(default=None, max_length=128)  # Unity Catalog
    # ─── ClickHouse-specific ──────────────────────────────────────
    protocol: str | None = Field(default=None, pattern=r"^(native|http)$")  # ClickHouse: native TCP or HTTP
    # ─── Snowflake key-pair auth ───────────────────────────────────
    private_key: str | None = Field(default=None, max_length=16384)  # PEM-encoded private key
    private_key_passphrase: str | None = Field(default=None, max_length=1024)
    # ─── DuckDB / MotherDuck ──────────────────────────────────────
    motherduck_token: str | None = Field(default=None, max_length=2048)  # MotherDuck personal access token
    # ─── Metadata ───────────────────────────────────────────────────
    description: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list)  # organizational tags
    # ─── Schema filtering (HEX pattern) ────────────────────────────
    schema_filter_include: list[str] = Field(
        default_factory=list,
        description="Only include these schemas (empty = include all). Glob patterns supported.",
    )
    schema_filter_exclude: list[str] = Field(
        default_factory=list,
        description="Exclude these schemas from AI introspection. Common: staging, dev, raw, tmp.",
    )
    # ─── Scheduled schema refresh (HEX pattern) ───────────────────
    schema_refresh_interval: int | None = Field(
        default=None, ge=60, le=86400,
        description="Auto-refresh schema every N seconds (60-86400). None = disabled.",
    )
    # ─── Timeout configuration ──────────────────────────────────────
    connection_timeout: int | None = Field(
        default=None, ge=1, le=300,
        description="Connection timeout in seconds (1-300). Default varies by connector.",
    )
    query_timeout: int | None = Field(
        default=None, ge=1, le=3600,
        description="Query timeout in seconds (1-3600). Default: 120.",
    )
    keepalive_interval: int | None = Field(
        default=None, ge=0, le=600,
        description="Keepalive ping interval in seconds. 0 = disabled.",
    )


class ConnectionUpdate(BaseModel):
    """Partial update for an existing connection. Only provided fields are changed."""
    db_type: DBType | None = None
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, max_length=128)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=1024)
    connection_string: str | None = Field(default=None, max_length=4096)
    ssl: bool | None = None
    ssl_config: SSLConfig | None = None
    ssh_tunnel: SSHTunnelConfig | None = None
    account: str | None = Field(default=None, max_length=255)
    warehouse: str | None = Field(default=None, max_length=128)
    schema_name: str | None = Field(default=None, max_length=128)
    role: str | None = Field(default=None, max_length=128)
    project: str | None = Field(default=None, max_length=255)
    dataset: str | None = Field(default=None, max_length=255)
    credentials_json: str | None = Field(default=None, max_length=65536)
    location: str | None = Field(default=None, max_length=64)
    maximum_bytes_billed: int | None = Field(default=None, ge=0)
    http_path: str | None = Field(default=None, max_length=512)
    access_token: str | None = Field(default=None, max_length=1024)
    catalog: str | None = Field(default=None, max_length=128)
    private_key: str | None = Field(default=None, max_length=16384)
    private_key_passphrase: str | None = Field(default=None, max_length=1024)
    description: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = None
    schema_filter_include: list[str] | None = None
    schema_filter_exclude: list[str] | None = None
    schema_refresh_interval: int | None = Field(default=None, ge=60, le=86400)
    last_schema_refresh: float | None = None  # internal — set by scheduler
    connection_timeout: int | None = Field(default=None, ge=1, le=300)
    query_timeout: int | None = Field(default=None, ge=1, le=3600)
    keepalive_interval: int | None = Field(default=None, ge=0, le=600)


class ConnectionInfo(BaseModel):
    id: str
    name: str
    db_type: DBType
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    ssl: bool = False
    ssl_config: SSLConfig | None = None
    ssh_tunnel: SSHTunnelConfig | None = None
    # Snowflake
    account: str | None = None
    warehouse: str | None = None
    schema_name: str | None = None
    role: str | None = None
    # BigQuery
    project: str | None = None
    dataset: str | None = None
    location: str | None = None  # BQ region
    maximum_bytes_billed: int | None = None  # BQ safety limit
    # Databricks
    http_path: str | None = None
    catalog: str | None = None
    # Metadata
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    schema_filter_include: list[str] = Field(default_factory=list)
    schema_filter_exclude: list[str] = Field(default_factory=list)
    schema_refresh_interval: int | None = None  # seconds, None = disabled
    last_schema_refresh: float | None = None  # timestamp of last successful refresh
    connection_timeout: int | None = None
    query_timeout: int | None = None
    keepalive_interval: int | None = None
    created_at: float = Field(default_factory=time.time)
    last_used: float | None = None
    status: str = "unknown"  # healthy | error | unknown


# ─── Projects ─────────────────────────────────────────────────────────────────


class ProjectSource(str, Enum):
    """How the dbt project was created or imported."""
    new = "new"
    local = "local"
    github = "github"
    dbt_cloud = "dbt-cloud"


class ProjectStorage(str, Enum):
    """Whether the project files are managed by SignalPilot or externally linked."""
    managed = "managed"
    linked = "linked"


class ProjectStatus(str, Enum):
    """Lifecycle status of a dbt project."""
    active = "active"
    error = "error"
    archived = "archived"


class ProjectCreate(BaseModel):
    """Payload for creating a new dbt project."""
    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    connection_name: str = Field(..., min_length=1)
    source: ProjectSource = ProjectSource.new
    # For source="local"
    local_path: str | None = None
    link_mode: str = "link"  # "link" | "copy"
    # For source="github"
    git_url: str | None = None
    git_branch: str | None = None
    description: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    """Partial update for an existing dbt project."""
    connection_name: str | None = None
    description: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = None
    git_remote: str | None = None
    git_branch: str | None = None
    status: str | None = None
    last_scanned_at: float | None = None


class ProjectInfo(BaseModel):
    """Persisted metadata for a dbt project."""
    id: str
    name: str
    connection_name: str
    project_dir: str
    storage: ProjectStorage
    source: ProjectSource
    db_type: str
    dbt_version: str = "1.9"
    model_count: int = 0
    status: ProjectStatus = ProjectStatus.active
    created_at: float = Field(default_factory=time.time)
    last_scanned_at: float | None = None
    git_remote: str | None = None
    git_branch: str | None = None
    description: str = ""
    tags: list[str] = Field(default_factory=list)


# ─── Sandboxes ────────────────────────────────────────────────────────────────

class SandboxCreate(BaseModel):
    connection_name: str | None = None
    row_limit: int = 10_000
    budget_usd: float = 10.0
    timeout_seconds: int = 300
    label: str = ""


class SandboxInfo(BaseModel):
    id: str
    vm_id: str | None = None
    connection_name: str | None = None
    label: str = ""
    status: str  # starting | running | stopped | error
    created_at: float = Field(default_factory=time.time)
    boot_ms: float | None = None
    uptime_sec: float | None = None
    budget_usd: float = 10.0
    budget_used: float = 0.0
    row_limit: int = 10_000


class ExecuteRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=1_000_000)
    timeout: int = Field(default=30, ge=1, le=300)


class ExecuteResult(BaseModel):
    success: bool
    output: str = ""
    error: str | None = None
    execution_ms: float | None = None
    vm_id: str | None = None


# ─── Audit ───────────────────────────────────────────────────────────────────

class AuditEntry(BaseModel):
    id: str
    timestamp: float
    event_type: str  # query | execute | connect | block
    connection_name: str | None = None
    sandbox_id: str | None = None
    sql: str | None = None
    tables: list[str] = []
    rows_returned: int | None = None
    cost_usd: float | None = None
    blocked: bool = False
    block_reason: str | None = None
    duration_ms: float | None = None
    agent_id: str | None = None
    metadata: dict[str, Any] = {}


# ─── MCP ─────────────────────────────────────────────────────────────────────

class MCPToolCall(BaseModel):
    tool: str
    arguments: dict[str, Any] = {}
    session_id: str | None = None
