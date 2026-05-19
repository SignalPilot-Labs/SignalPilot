"""Pydantic models for notebook sessions."""

from __future__ import annotations

import time

from pydantic import BaseModel, Field


class NotebookSessionCreate(BaseModel):
    project_id: str | None = None
    branch: str = "main"


class NotebookSessionInfo(BaseModel):
    id: str
    org_id: str
    user_id: str
    project_id: str | None = None
    branch: str = "main"
    pod_name: str | None = None
    pod_ip: str | None = None
    status: str = "creating"
    proxy_base: str | None = None
    last_ping: float | None = None
    created_at: float = Field(default_factory=time.time)
