"""API key models."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

VALID_API_KEY_SCOPES: frozenset[str] = frozenset({"read", "query", "execute", "write", "admin", "dbt_proxy"})


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    scopes: list[str] = Field(default_factory=lambda: ["read", "query"])
    expires_at: str | None = None

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v: list[str]) -> list[str]:
        invalid = [s for s in v if s not in VALID_API_KEY_SCOPES]
        if invalid:
            raise ValueError(f"Invalid scope(s): {invalid}. Valid scopes are: {sorted(VALID_API_KEY_SCOPES)}")
        return v

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from datetime import datetime

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
    prefix: str  # e.g. "sp_a1b2" — first 7 chars for display
    key_hash: str  # SHA-256 hex digest of the full raw key
    scopes: list[str]
    created_at: str  # ISO 8601
    last_used_at: str | None = None
    expires_at: str | None = None
    user_id: str = "local"
    org_id: str = "local"


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
