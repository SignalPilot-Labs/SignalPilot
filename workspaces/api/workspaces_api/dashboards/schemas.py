"""Pydantic v2 request/response schemas for the dashboards module."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

_CHART_TYPES = {"line", "bar", "table", "number"}
_SQL_MAX_CHARS = 50_000


class ChartQueryCreate(BaseModel):
    connector_name: str = Field(..., min_length=1, max_length=64)
    sql: str = Field(..., min_length=1, max_length=_SQL_MAX_CHARS)
    params: dict[str, Any] = Field(default_factory=dict)
    refresh_interval_seconds: int = Field(..., ge=60, le=86400)

    @field_validator("sql")
    @classmethod
    def validate_sql_length(cls, v: str) -> str:
        if len(v) > _SQL_MAX_CHARS:
            raise ValueError("sql_too_long")
        return v


class ChartCreateRequest(BaseModel):
    workspace_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=256)
    chart_type: str
    echarts_option_json: dict[str, Any] = Field(default_factory=dict)
    query: ChartQueryCreate

    @field_validator("chart_type")
    @classmethod
    def validate_chart_type(cls, v: str) -> str:
        if v not in _CHART_TYPES:
            raise ValueError("invalid_chart_type")
        return v


class ChartQueryResponse(BaseModel):
    id: uuid.UUID
    chart_id: uuid.UUID
    connector_name: str
    sql: str
    params: dict[str, Any]
    refresh_interval_seconds: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ChartResponse(BaseModel):
    id: uuid.UUID
    workspace_id: str
    title: str
    chart_type: str
    echarts_option_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    query: ChartQueryResponse | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_chart(cls, chart: Any) -> "ChartResponse":
        """Build response from Chart ORM object."""
        query_resp: ChartQueryResponse | None = None
        if chart.query is not None:
            query_resp = ChartQueryResponse.model_validate(chart.query)
        return cls(
            id=chart.id,
            workspace_id=chart.workspace_id,
            title=chart.title,
            chart_type=chart.chart_type,
            echarts_option_json=chart.echarts_option or {},
            created_at=chart.created_at,
            updated_at=chart.updated_at,
            created_by=chart.created_by,
            query=query_resp,
        )


class ChartListResponse(BaseModel):
    items: list[ChartResponse]
    next_cursor: str | None


class ChartRunRequest(BaseModel):
    force: bool = False
    params: dict[str, Any] | None = None


class ChartRunResponse(BaseModel):
    """Returned on cache HIT or MISS (after execution)."""

    chart_id: uuid.UUID
    cache_key: str
    cached: bool
    computed_at: datetime
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    truncated: bool = False
