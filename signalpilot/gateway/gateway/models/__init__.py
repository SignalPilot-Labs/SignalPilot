"""Pydantic models shared across the gateway.

Split into feature modules; this package re-exports the full public
surface so callers can keep using ``from gateway.models import X``.
"""

from __future__ import annotations

from .api_keys import (
    VALID_API_KEY_SCOPES,
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyRecord,
    ApiKeyResponse,
)
from .audit import AuditEntry
from .byok import (
    BYOKKeyCreate,
    BYOKKeyResponse,
    BYOKKeyUpdate,
    BYOKMigrateRequest,
    BYOKMigrateResponse,
    BYOKMigrationStatusResponse,
    BYOKRotateRequest,
    BYOKRotateResponse,
)
from .connections import (
    ConnectionCreate,
    ConnectionInfo,
    ConnectionUpdate,
    DBType,
    SSHTunnelConfig,
    SSLConfig,
)
from .mcp import MCPToolCall
from .projects import (
    ProjectCreate,
    ProjectInfo,
    ProjectSource,
    ProjectStatus,
    ProjectStorage,
    ProjectUpdate,
)
from .sandboxes import (
    ExecuteRequest,
    ExecuteResult,
    SandboxCreate,
    SandboxInfo,
)
from .settings import GatewaySettings, SandboxProvider

__all__ = [
    "VALID_API_KEY_SCOPES",
    "ApiKeyCreate",
    "ApiKeyCreatedResponse",
    "ApiKeyRecord",
    "ApiKeyResponse",
    "AuditEntry",
    "BYOKKeyCreate",
    "BYOKKeyResponse",
    "BYOKKeyUpdate",
    "BYOKMigrateRequest",
    "BYOKMigrateResponse",
    "BYOKMigrationStatusResponse",
    "BYOKRotateRequest",
    "BYOKRotateResponse",
    "ConnectionCreate",
    "ConnectionInfo",
    "ConnectionUpdate",
    "DBType",
    "ExecuteRequest",
    "ExecuteResult",
    "GatewaySettings",
    "MCPToolCall",
    "ProjectCreate",
    "ProjectInfo",
    "ProjectSource",
    "ProjectStatus",
    "ProjectStorage",
    "ProjectUpdate",
    "SSHTunnelConfig",
    "SSLConfig",
    "SandboxCreate",
    "SandboxInfo",
    "SandboxProvider",
]
