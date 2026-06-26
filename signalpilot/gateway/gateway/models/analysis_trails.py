"""Models for durable external analysis trails."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

AnalysisTrailSource = Literal["notion", "slack"]
AnalysisTrailStatus = Literal["active", "done", "failed"]


class AnalysisTrailUpsert(BaseModel):
    source: AnalysisTrailSource
    request_id: str = Field(..., min_length=1, max_length=200)
    thread_id: str = Field(..., min_length=1, max_length=300)
    runtime_session_id: str | None = Field(None, max_length=200)
    project_id: str = Field(..., min_length=1, max_length=200)
    branch: str = Field(..., min_length=1, max_length=100)
    default_branch: str = Field(default="main", min_length=1, max_length=100)
    notebook_path: str = Field(..., min_length=1, max_length=4000)
    status: AnalysisTrailStatus = "active"
    latest_commit_sha: str | None = Field(None, max_length=64)
    source_url: str | None = Field(None, max_length=4000)
    source_thread_id: str | None = Field(None, max_length=300)
    source_request_id: str | None = Field(None, max_length=300)
    analysis_user_id: str | None = Field(None, max_length=300)
    metadata: dict[str, Any] | None = None


class AnalysisTrailUpdate(BaseModel):
    runtime_session_id: str | None = Field(None, max_length=200)
    status: AnalysisTrailStatus | None = None
    latest_commit_sha: str | None = Field(None, max_length=64)
    notebook_path: str | None = Field(None, max_length=4000)
    metadata: dict[str, Any] | None = None


class AnalysisTrailInfo(BaseModel):
    id: str
    org_id: str
    source: str
    request_id: str
    thread_id: str
    runtime_session_id: str | None = None
    project_id: str
    branch: str
    default_branch: str = "main"
    notebook_path: str
    status: str = "active"
    latest_commit_sha: str | None = None
    source_url: str | None = None
    source_thread_id: str | None = None
    source_request_id: str | None = None
    analysis_user_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
