"""Database connection models."""

from __future__ import annotations

import re
import time
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ._helpers import _validate_string_list

_XATA_REGION_RE = re.compile(r"^[a-z0-9-]{1,32}$")
_XATA_BRANCH_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_XATA_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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
    xata = "xata"


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


def _validate_xata_field_shapes(
    *,
    region: str | None,
    branch: str | None,
    workspace: str | None,
    xata_org: str | None,
    username: str | None,
    xata_api_url: str | None,
    xata_token_url: str | None,
) -> None:
    """Validate per-field shape rules (regex + SSRF). Raises ValueError.

    Only checks fields that are not None. Does NOT enforce required-field
    or cross-field (OIDC consistency) rules — those depend on the merged
    record and live in the model_validator (Create) or route (Update).

    NOTE: username has no regex validation today; add a pattern and re-enable
    when a suitable constraint is agreed on.
    """
    # Lazy import to preserve existing import-cycle avoidance pattern.
    from gateway.network.validation import validate_xata_control_url

    if region is not None and not _XATA_REGION_RE.match(region):
        raise ValueError("Xata 'region' must match ^[a-z0-9-]{1,32}$")
    if branch is not None and not _XATA_BRANCH_RE.match(branch):
        raise ValueError("Xata 'branch' must match ^[A-Za-z0-9_.-]{1,64}$")
    if workspace is not None and not _XATA_WORKSPACE_RE.match(workspace):
        raise ValueError("Xata 'workspace' must match ^[A-Za-z0-9_-]{1,64}$")
    if xata_org is not None and not _XATA_WORKSPACE_RE.match(xata_org):
        raise ValueError("Xata 'xata_org' must match ^[A-Za-z0-9_-]{1,64}$")
    # username: no regex today — see docstring TODO above.
    if xata_api_url is not None:
        validate_xata_control_url(xata_api_url)
    if xata_token_url is not None:
        validate_xata_control_url(xata_token_url)


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
    # ─── Xata-specific ────────────────────────────────────────────
    # A Xata "connection" is a WORKSPACE, not a single DB. The stored secret is a
    # scoped Xata API key (carried in `password`); the per-branch Postgres endpoint
    # is resolved server-side at connect time. Branches are addressed per-call, so
    # one credential serves every branch in the workspace.
    workspace: str | None = Field(default=None, max_length=128)  # Xata workspace id (URL user)
    region: str | None = Field(default=None, max_length=64)  # e.g. us-east-1, eu-central-1
    branch: str | None = Field(default=None, max_length=128)  # default branch (default: main)
    # Control-plane (branch lifecycle). Optional: only needed for list/create branch
    # tools. Auth is either the data-plane API key as a Bearer token (Xata Cloud) or
    # OIDC password grant (self-hosted dev). Secrets ride in extras_enc (encrypted).
    xata_api_url: str | None = Field(default=None, max_length=512)  # e.g. https://api.xata.io
    xata_org: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")  # control-plane org id
    xata_token_url: str | None = Field(default=None, max_length=512)  # OIDC token endpoint (self-hosted)
    xata_client_id: str | None = Field(default=None, max_length=128)
    xata_client_secret: str | None = Field(default=None, max_length=1024)
    xata_username: str | None = Field(default=None, max_length=128)   # OIDC user
    xata_password: str | None = Field(default=None, max_length=1024)  # OIDC password (NOT the data-plane API key)
    # ─── Snowflake key-pair auth ───────────────────────────────────
    private_key: str | None = Field(default=None, max_length=16384)  # PEM-encoded private key
    private_key_passphrase: str | None = Field(default=None, max_length=1024)
    # ─── Snowflake auth method + host override (supports all account types) ──
    # authenticator: password | key_pair | oauth | pat | mfa, OR an Okta URL
    # (https://<org>.okta.com). Empty = password.
    authenticator: str | None = Field(default=None, max_length=512)
    passcode: str | None = Field(default=None, max_length=16)  # MFA passcode (username_password_mfa)
    # Explicit host override for PrivateLink / China (.cn) / SnowGov / VPS — when the
    # account identifier alone does not produce the right <host>.snowflakecomputing.com.
    snowflake_host: str | None = Field(default=None, max_length=255)
    snowflake_protocol: str | None = Field(default=None, pattern=r"^https?$")  # default https
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

    @model_validator(mode="after")
    def validate_xata_fields(self) -> ConnectionCreate:
        if self.db_type != DBType.xata:
            return self

        # region and database are required
        if not self.region or not self.region.strip():
            raise ValueError("Xata connections require both 'region' and 'database'")
        if not self.database or not self.database.strip():
            raise ValueError("Xata connections require both 'region' and 'database'")

        # Per-field shape checks (regex + SSRF).
        _validate_xata_field_shapes(
            region=self.region,
            branch=self.branch,
            workspace=self.workspace,
            xata_org=self.xata_org,
            username=None,  # no regex on xata_username today — see helper docstring
            xata_api_url=self.xata_api_url,
            xata_token_url=self.xata_token_url,
        )

        # OIDC / control-plane consistency (cross-field; full record is known here).
        if self.xata_token_url:
            missing = [
                f for f, v in [
                    ("xata_client_id", self.xata_client_id),
                    ("xata_client_secret", self.xata_client_secret),
                    ("xata_username", self.xata_username),
                    ("xata_password", self.xata_password),
                ]
                if not v
            ]
            if missing:
                raise ValueError(
                    f"xata_token_url is set but the following OIDC fields are missing: {', '.join(missing)}"
                )
        else:
            oidc_only = [
                f for f, v in [
                    ("xata_client_id", self.xata_client_id),
                    ("xata_client_secret", self.xata_client_secret),
                    ("xata_username", self.xata_username),
                    ("xata_password", self.xata_password),
                ]
                if v
            ]
            if oidc_only:
                raise ValueError(
                    f"OIDC fields {', '.join(oidc_only)} are set but xata_token_url is not"
                )

        return self


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
    # Snowflake auth method + host override
    authenticator: str | None = Field(default=None, max_length=512)
    passcode: str | None = Field(default=None, max_length=16)
    snowflake_host: str | None = Field(default=None, max_length=255)
    snowflake_protocol: str | None = Field(default=None, pattern=r"^https?$")
    description: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = Field(default=None, max_length=50)
    schema_filter_include: list[str] | None = Field(default=None, max_length=100)
    schema_filter_exclude: list[str] | None = Field(default=None, max_length=100)
    # ─── Xata-specific ────────────────────────────────────────────────
    workspace: str | None = Field(default=None, max_length=128)
    region: str | None = Field(default=None, max_length=64)
    branch: str | None = Field(default=None, max_length=128)
    xata_api_url: str | None = Field(default=None, max_length=512)
    xata_org: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    xata_token_url: str | None = Field(default=None, max_length=512)
    xata_client_id: str | None = Field(default=None, max_length=128)
    xata_client_secret: str | None = Field(default=None, max_length=1024)
    xata_username: str | None = Field(default=None, max_length=128)
    xata_password: str | None = Field(default=None, max_length=1024)

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

    @model_validator(mode="after")
    def validate_xata_field_shapes(self) -> ConnectionUpdate:
        # Per-field shape checks run whenever a Xata field is supplied, regardless
        # of db_type (defense in depth: db_type may be omitted from the patch).
        # OIDC consistency + required-field checks are enforced at the route layer
        # against the merged record, where the existing DB row is available.
        _validate_xata_field_shapes(
            region=self.region,
            branch=self.branch,
            workspace=self.workspace,
            xata_org=self.xata_org,
            username=None,  # no regex on xata_username today — see helper docstring
            xata_api_url=self.xata_api_url,
            xata_token_url=self.xata_token_url,
        )
        return self

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
    authenticator: str | None = None  # auth method or Okta URL (non-secret)
    snowflake_host: str | None = None  # host override (PrivateLink/China/gov/VPS)
    snowflake_protocol: str | None = None
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
