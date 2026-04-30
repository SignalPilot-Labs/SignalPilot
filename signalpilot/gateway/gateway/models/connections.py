"""Database connection models."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ._helpers import _validate_string_list


class DBType(str, Enum):  # noqa: UP042 — (str,Enum) keeps str(X.A)=='X.A'; StrEnum returns 'A' and breaks f-string/log output
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
        default=None,
        ge=0,
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

    @field_validator("schema_filter_include", "schema_filter_exclude", mode="before")
    @classmethod
    def coerce_schema_filters(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()] if v.strip() else []
        if v is None:
            return []
        return v

    @field_validator("schema_filter_include", "schema_filter_exclude")
    @classmethod
    def validate_schema_filters(cls, v: list[str]) -> list[str]:
        return _validate_string_list(v, 256, "schema_filter")

    # ─── Scheduled schema refresh (HEX pattern) ───────────────────
    schema_refresh_interval: int | None = Field(
        default=None,
        ge=60,
        le=86400,
        description="Auto-refresh schema every N seconds (60-86400). None = disabled.",
    )
    # ─── Timeout configuration ──────────────────────────────────────
    connection_timeout: int | None = Field(
        default=None,
        ge=1,
        le=300,
        description="Connection timeout in seconds (1-300). Default varies by connector.",
    )
    query_timeout: int | None = Field(
        default=None,
        ge=1,
        le=3600,
        description="Query timeout in seconds (1-3600). Default: 120.",
    )
    keepalive_interval: int | None = Field(
        default=None,
        ge=0,
        le=600,
        description="Keepalive ping interval in seconds. 0 = disabled.",
    )
    # ─── BYOK ───────────────────────────────────────────────────────────
    org_id: str | None = Field(default=None, max_length=100)
    byok_key_alias: str | None = Field(default=None, max_length=200, pattern=r"^[a-zA-Z0-9_-]+$")


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
    # PII redaction
    pii_rules: dict[str, str] | None = None  # {column_name: "hash"|"mask"|"hide"}
    pii_enabled: bool = False  # toggle to activate PII redaction at query time
    # BYOK scaffolding (Phase 1: always None; Phase 2 populates on encrypt)
    org_id: str | None = None
    byok_key_alias: str | None = None
