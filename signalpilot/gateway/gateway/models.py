"""Pydantic models shared across the gateway."""

from __future__ import annotations

import json
import time
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _validate_string_list(v: list[str], max_item_len: int, field_name: str) -> list[str]:
    """Validate that each item in a string list does not exceed max_item_len."""
    for item in v:
        if len(item) > max_item_len:
            raise ValueError(
                f"Each item in {field_name} must be at most {max_item_len} characters"
            )
    return v


# ─── Settings ────────────────────────────────────────────────────────────────

class SandboxProvider(str, Enum):
    local = "local"       # local sandbox_manager at socket/http
    remote = "remote"     # BYOS -- remote sandbox manager HTTP endpoint


class GatewaySettings(BaseModel):
    # Sandbox configuration (BYOS -- Bring Your Own Sandbox)
    sandbox_provider: SandboxProvider = SandboxProvider.local
    sandbox_manager_url: str = Field(default="http://localhost:8180", max_length=2048)
    sandbox_api_key: str | None = None

    # Governance defaults
    default_row_limit: int = 10_000
    default_budget_usd: float = 10.0
    default_timeout_seconds: int = 30
    max_concurrent_sandboxes: int = 10

    # Governance — blocked tables (Feature #19)
    blocked_tables: list[str] = Field(default_factory=list, max_length=500)

    # Gateway
    gateway_url: str = Field(default="http://localhost:3300", max_length=2048)
    api_key: str | None = None

    @field_validator("blocked_tables")
    @classmethod
    def validate_blocked_tables(cls, v: list[str]) -> list[str]:
        return _validate_string_list(v, 256, "blocked_tables")


# ─── API Keys ────────────────────────────────────────────────────────────────

VALID_API_KEY_SCOPES: frozenset[str] = frozenset({"read", "query", "execute", "write", "admin"})


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    scopes: list[str] = Field(default_factory=lambda: ["read", "query"])
    expires_at: str | None = None

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v: list[str]) -> list[str]:
        invalid = [s for s in v if s not in VALID_API_KEY_SCOPES]
        if invalid:
            raise ValueError(
                f"Invalid scope(s): {invalid}. Valid scopes are: {sorted(VALID_API_KEY_SCOPES)}"
            )
        return v

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from datetime import datetime, timezone
        try:
            parsed = datetime.fromisoformat(v)
        except (ValueError, TypeError):
            raise ValueError("expires_at must be a valid ISO-8601 datetime string")
        if parsed.tzinfo is None:
            raise ValueError("expires_at must include timezone (e.g. +00:00 or Z)")
        return v


class ApiKeyRecord(BaseModel):
    """Persisted API key record (hash stored, never the raw key)."""
    id: str
    name: str
    prefix: str          # e.g. "sp_a1b2" — first 7 chars for display
    key_hash: str        # SHA-256 hex digest of the full raw key
    scopes: list[str]
    created_at: str      # ISO 8601
    last_used_at: str | None = None
    expires_at: str | None = None
    user_id: str = "local"


class ApiKeyResponse(BaseModel):
    """Returned to clients — never includes hash."""
    id: str
    name: str
    prefix: str
    scopes: list[str]
    created_at: str
    last_used_at: str | None = None
    expires_at: str | None = None


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned only on creation — includes the raw key once."""
    raw_key: str


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
    auth_method: Literal["password", "key", "agent"] = "password"
    password: str | None = Field(default=None, max_length=1024)
    private_key: str | None = Field(default=None, max_length=16384)
    private_key_passphrase: str | None = Field(default=None, max_length=1024)
    # HTTP proxy for SSH (HEX pattern) — for VPCs that block direct SSH
    proxy_host: str | None = Field(default=None, max_length=255)
    proxy_port: int = Field(default=3128, ge=1, le=65535)


class SSLConfig(BaseModel):
    """SSL/TLS configuration for database connections."""
    enabled: bool = False
    mode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = "require"
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
    tags: list[str] = Field(default_factory=list, max_length=50)  # organizational tags
    # ─── Schema filtering (HEX pattern) ────────────────────────────
    schema_filter_include: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="Only include these schemas (empty = include all). Glob patterns supported.",
    )
    schema_filter_exclude: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="Exclude these schemas from AI introspection. Common: staging, dev, raw, tmp.",
    )

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        return _validate_string_list(v, 64, "tags")

    @field_validator("schema_filter_include", "schema_filter_exclude")
    @classmethod
    def validate_schema_filters(cls, v: list[str]) -> list[str]:
        return _validate_string_list(v, 256, "schema_filter")
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
    tags: list[str] | None = Field(default=None, max_length=50)
    schema_filter_include: list[str] | None = Field(default=None, max_length=100)
    schema_filter_exclude: list[str] | None = Field(default=None, max_length=100)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return _validate_string_list(v, 64, "tags")

    @field_validator("schema_filter_include", "schema_filter_exclude")
    @classmethod
    def validate_schema_filters(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return _validate_string_list(v, 256, "schema_filter")
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
    # BYOK scaffolding (Phase 1: always None; Phase 2 populates on encrypt)
    org_id: str | None = None
    byok_key_alias: str | None = None


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
    connection_name: str = Field(..., min_length=1, max_length=64)
    source: ProjectSource = ProjectSource.new
    # For source="local"
    local_path: str | None = Field(default=None, max_length=4096)
    link_mode: Literal["link", "copy"] = "link"
    # For source="github"
    git_url: str | None = Field(default=None, max_length=2048)
    git_branch: str | None = Field(default=None, max_length=256)
    description: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        return _validate_string_list(v, 64, "tags")


class ProjectUpdate(BaseModel):
    """Partial update for an existing dbt project."""
    connection_name: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = Field(default=None, max_length=50)
    git_remote: str | None = Field(default=None, max_length=2048)
    git_branch: str | None = Field(default=None, max_length=256)
    status: ProjectStatus | None = None
    last_scanned_at: float | None = None

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return _validate_string_list(v, 64, "tags")


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
    connection_name: str | None = Field(default=None, max_length=64)
    row_limit: int = Field(default=10_000, ge=1, le=100_000)
    budget_usd: float = Field(default=10.0, ge=0.01, le=10_000.0)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    label: str = Field(default="", max_length=128)


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


_MCP_ARGUMENTS_MAX_DEPTH: int = 20
_MCP_ARGUMENTS_MAX_SIZE_BYTES: int = 100_000


def _check_dict_depth(obj: Any, current_depth: int, max_depth: int) -> None:
    """Check that obj does not exceed max_depth nesting levels.

    Raises ValueError if current_depth exceeds max_depth BEFORE recursing into
    children, ensuring the Python call stack is never blown even by deeply
    nested inputs.
    """
    if current_depth > max_depth:
        raise ValueError(
            f"arguments nesting depth exceeds maximum of {max_depth} levels"
        )
    if isinstance(obj, dict):
        for value in obj.values():
            _check_dict_depth(value, current_depth + 1, max_depth)
    elif isinstance(obj, list):
        for item in obj:
            _check_dict_depth(item, current_depth + 1, max_depth)


# ─── MCP ─────────────────────────────────────────────────────────────────────

class MCPToolCall(BaseModel):
    tool: str = Field(..., max_length=128)
    arguments: dict[str, Any] = {}
    session_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _validate_arguments(self) -> MCPToolCall:
        serialized = json.dumps(self.arguments)
        if len(serialized) > _MCP_ARGUMENTS_MAX_SIZE_BYTES:
            raise ValueError(
                f"arguments serialized size exceeds maximum of "
                f"{_MCP_ARGUMENTS_MAX_SIZE_BYTES} bytes"
            )
        _check_dict_depth(self.arguments, current_depth=0, max_depth=_MCP_ARGUMENTS_MAX_DEPTH)
        return self
