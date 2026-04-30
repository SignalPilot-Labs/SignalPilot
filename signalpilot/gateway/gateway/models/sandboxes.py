"""Sandbox and execution models."""

from __future__ import annotations

import time

from pydantic import BaseModel, Field


class SandboxCreate(BaseModel):
    connection_name: str | None = Field(default=None, max_length=64)
    row_limit: int = Field(default=10_000, ge=1, le=100_000)
    budget_usd: float = Field(default=10.0, ge=0.01, le=10_000.0)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    label: str = Field(default="", max_length=128)


class SandboxInfo(BaseModel):
    id: str
    org_id: str = ""
    vm_id: str | None = None
    connection_name: str | None = None
    label: str = ""
    status: str  # starting | running | stopped | error
    created_at: float = Field(default_factory=time.time)
    boot_ms: float | None = None
    uptime_sec: float | None = None
    budget_usd: float = 10.0
    budget_used: float = 0.0
    row_limit: int = 10_000


class ExecuteRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=1_000_000)
    timeout: int = Field(default=30, ge=1, le=300)


class ExecuteResult(BaseModel):
    success: bool
    output: str = ""
    error: str | None = None
    execution_ms: float | None = None
    vm_id: str | None = None
