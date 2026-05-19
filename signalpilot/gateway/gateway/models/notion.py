"""Pydantic models for Notion integration."""

from __future__ import annotations

import time

from pydantic import BaseModel, Field


class NotionIntegrationCreate(BaseModel):
    """Create a new Notion integration."""

    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    api_key: str = Field(..., min_length=1, max_length=256)
    search_page_ids: list[str] = Field(default_factory=list, max_length=20)
    report_parent_page_id: str = Field(..., min_length=1, max_length=64)


class NotionIntegrationUpdate(BaseModel):
    """Partial update for an existing Notion integration."""

    api_key: str | None = Field(default=None, min_length=1, max_length=256)
    search_page_ids: list[str] | None = Field(default=None, max_length=20)
    report_parent_page_id: str | None = Field(default=None, min_length=1, max_length=64)


class NotionIntegrationInfo(BaseModel):
    """Read-only info returned from API (never includes api_key)."""

    id: str
    name: str
    search_page_ids: list[str] = Field(default_factory=list)
    report_parent_page_id: str | None = None
    status: str = "unknown"
    created_at: float = Field(default_factory=time.time)
    org_id: str | None = None
