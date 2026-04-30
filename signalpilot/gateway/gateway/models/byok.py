"""BYOK (Bring Your Own Key) API models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class BYOKKeyCreate(BaseModel):
    key_alias: str = Field(..., min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_-]+$")
    provider_type: str = Field(..., pattern=r"^(local|aws_kms|gcp_kms|azure_kv)$")
    provider_config: dict[str, Any] | None = None


class BYOKKeyUpdate(BaseModel):
    key_alias: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_-]+$")
    status: str | None = Field(default=None, pattern=r"^(active|revoked)$")


class BYOKKeyResponse(BaseModel):
    id: str
    org_id: str
    key_alias: str
    provider_type: str
    provider_config: dict[str, Any] | None = None
    status: str
    created_at: float
    revoked_at: float | None = None


class BYOKMigrateRequest(BaseModel):
    key_id: str = Field(..., min_length=1, max_length=2048)


class BYOKMigrateResponse(BaseModel):
    migrated: int
    failed: int
    errors: list[str] = Field(default_factory=list)


class BYOKRotateRequest(BaseModel):
    new_key_id: str = Field(..., min_length=1, max_length=2048)


class BYOKRotateResponse(BaseModel):
    rotated: int
    failed: int
    errors: list[str] = Field(default_factory=list)


class BYOKMigrationStatusResponse(BaseModel):
    total: int
    byok: int
    managed: int
    status: Literal["none", "partial", "complete"]
