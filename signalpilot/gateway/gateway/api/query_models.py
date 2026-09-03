"""Request bodies for the /api/query endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DirectQueryRequest(BaseModel):
    connection_name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    sql: str = Field(..., min_length=1, max_length=100_000)
    row_limit: int = Field(default=10_000, ge=1, le=100_000)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    plan_id: str | None = Field(default=None, min_length=1, max_length=200)


class QueryPlanRequest(BaseModel):
    connection_name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    sql: str = Field(..., min_length=1, max_length=100_000)
    purpose: str = Field(..., min_length=1, max_length=2_000)
    row_level_analysis_justified: bool = False


class PublishResultRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    rows: list[dict[str, Any]]
    source_result_ids: list[str] = Field(..., min_length=1, max_length=100)
    completeness: str = Field(..., pattern=r"^(complete|truncated|unknown)$")
    reconciliation: str | None = Field(default=None, max_length=2_000)
    code_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class QueryDatasetRequest(BaseModel):
    connection_name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    sql: str = Field(..., min_length=1, max_length=100_000)
    plan_id: str | None = Field(default=None, min_length=1, max_length=200)
