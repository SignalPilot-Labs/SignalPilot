"""Pydantic v2 request and response schemas for the Workspaces API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RunCreateRequest(BaseModel):
    workspace_id: str
    prompt: str = Field(min_length=1, max_length=16000)
    dbt_proxy_host_port: int | None = None
    requested_inference: Literal["local", "byo", "metered"] | None = None


class RunResponse(BaseModel):
    id: uuid.UUID
    workspace_id: str
    state: str
    inference_mode: str
    dbt_proxy_host_port: int | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class RunEventOut(BaseModel):
    id: int
    run_id: uuid.UUID
    kind: str
    payload: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class ApprovalDecisionRequest(BaseModel):
    approval_id: str
    reason: str | None = None


class ApprovalResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    tool_name: str
    tool_input: dict
    requested_at: datetime
    decided_at: datetime | None
    decision: str | None
    reason: str | None

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str
    deployment_mode: str
