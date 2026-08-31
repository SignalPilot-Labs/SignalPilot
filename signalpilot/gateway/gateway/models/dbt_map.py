"""Pydantic models for the dbt map endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class DbtMapInfo(BaseModel):
    id: str
    project_id: str
    branch: str
    revision: int
    status: str
    trigger: str
    error: str | None = None
    dbt_version: str | None = None
    node_count: int = 0
    manifest_bytes: int = 0
    created_at: float
    updated_at: float


class DbtMapResponse(BaseModel):
    """Latest compile state for a branch, with the distilled graph inline."""

    status: str  # none | queued | running | success | failed
    map: DbtMapInfo | None = None
    graph: dict | None = None


class DbtMapCompileResponse(BaseModel):
    scheduled: bool
    map: DbtMapInfo | None = None
