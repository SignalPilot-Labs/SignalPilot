"""Pydantic models for notebook sessions (Runtime v2)."""

from __future__ import annotations

import time

from pydantic import BaseModel, Field


class NotebookSessionCreate(BaseModel):
    project_id: str | None = None
    branch: str = "main"


class NotebookSessionInfo(BaseModel):
    """FE-facing session view. Never carries credentials or upstream URLs —
    the browser only ever talks to the gateway proxy path."""

    id: str
    org_id: str
    user_id: str
    project_id: str | None = None
    branch: str = "main"
    backend: str = "vercel"
    status: str = "creating"
    notebook_url: str | None = None
    last_ping: float | None = None
    created_at: float = Field(default_factory=time.time)
