"""Gateway-wide settings models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator

from ._helpers import _validate_string_list

_INT_GTE_ZERO_MSG = "knowledge_history_versions_override must be a non-negative integer or None"


class SandboxProvider(str, Enum):  # noqa: UP042 — (str,Enum) keeps str(X.A)=='X.A'; StrEnum returns 'A' and breaks f-string/log output
    local = "local"  # local sandbox_manager at socket/http
    remote = "remote"  # BYOS -- remote sandbox manager HTTP endpoint


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

    # Knowledge Base — number of edit history versions to keep per doc.
    # None = follow plan default. 0 = unlimited. >= 1 = exact count.
    knowledge_history_versions_override: int | None = None

    @field_validator("blocked_tables")
    @classmethod
    def validate_blocked_tables(cls, v: list[str]) -> list[str]:
        return _validate_string_list(v, 256, "blocked_tables")

    @field_validator("knowledge_history_versions_override")
    @classmethod
    def validate_knowledge_history_versions_override(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if not isinstance(v, int):
            raise ValueError(_INT_GTE_ZERO_MSG)
        if v < 0:
            raise ValueError(_INT_GTE_ZERO_MSG)
        return v
