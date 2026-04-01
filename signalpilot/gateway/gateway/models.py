"""Pydantic models shared across the gateway."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ─── Settings ────────────────────────────────────────────────────────────────

class SandboxProvider(str, Enum):
    local = "local"       # local sandbox_manager at socket/http
    remote = "remote"     # BYOF — remote sandbox manager HTTP endpoint


class GatewaySettings(BaseModel):
    # BYOF Firecracker configuration
    sandbox_provider: SandboxProvider = SandboxProvider.local
    sandbox_manager_url: str = "http://localhost:8180"
    sandbox_api_key: str | None = None

    # Governance defaults
    default_row_limit: int = 10_000
    default_budget_usd: float = 10.0
    default_timeout_seconds: int = 30
    max_concurrent_sandboxes: int = 10

    # Gateway
    gateway_url: str = "http://localhost:3300"
    api_key: str | None = None


# ─── Connections ─────────────────────────────────────────────────────────────

class DBType(str, Enum):
    postgres = "postgres"
    duckdb = "duckdb"
    mysql = "mysql"
    snowflake = "snowflake"


class ConnectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    db_type: DBType
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None
    connection_string: str | None = None  # alternative to individual fields
    ssl: bool = False
    description: str = ""


class ConnectionInfo(BaseModel):
    id: str
    name: str
    db_type: DBType
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    ssl: bool = False
    description: str = ""
    created_at: float = Field(default_factory=time.time)
    last_used: float | None = None
    status: str = "unknown"  # healthy | error | unknown


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
    code: str
    timeout: int = 30


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
