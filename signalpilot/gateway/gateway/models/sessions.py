"""Kernel session models."""

from __future__ import annotations

import time

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    connection_name: str | None = Field(default=None, max_length=64)
    label: str = Field(default="", max_length=128)


class SessionExecuteRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=1_000_000)
    timeout: int = Field(default=30, ge=1, le=300)
    cell_id: str | None = Field(default=None, max_length=64)


class CellResultResponse(BaseModel):
    success: bool
    output: str = ""
    outputs: list[dict] | None = None
    error: str | None = None
    execution_ms: float | None = None
    execution_count: int = 0
    cell_id: str | None = None


class SessionInfoResponse(BaseModel):
    id: str
    org_id: str = ""
    status: str = "idle"
    created_at: float = Field(default_factory=time.time)
    last_active: float = Field(default_factory=time.time)
    cell_count: int = 0
    connection_name: str | None = None
    label: str = ""


class SessionHistoryResponse(BaseModel):
    session_id: str
    cells: list[CellResultResponse] = []
