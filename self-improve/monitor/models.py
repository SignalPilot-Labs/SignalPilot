"""Pydantic models for the monitor API."""

from datetime import datetime
from pydantic import BaseModel


class RunResponse(BaseModel):
    id: str
    started_at: datetime
    ended_at: datetime | None = None
    branch_name: str
    name: str | None = None
    status: str
    pr_url: str | None = None
    total_tool_calls: int
    total_cost_usd: float | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    error_message: str | None = None


class ToolCallResponse(BaseModel):
    id: int
    run_id: str
    ts: datetime
    phase: str
    tool_name: str
    input_data: dict | None = None
    output_data: dict | None = None
    duration_ms: int | None = None
    permitted: bool
    deny_reason: str | None = None


class AuditLogResponse(BaseModel):
    id: int
    run_id: str
    ts: datetime
    event_type: str
    details: dict
