"""Pydantic DTOs for the Reports feature (rendered HTML reports)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReportSummary(BaseModel):
    """Report metadata without the HTML body — used for list views."""

    id: str
    org_id: str
    scope_ref: str | None
    title: str
    bytes: int
    view_count: int
    created_at: float
    updated_at: float
    created_by: str | None
    proposed_by_agent: str | None


class Report(ReportSummary):
    """Full report including the rendered HTML body."""

    html: str


class ReportCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    html: str = Field(..., min_length=1)
    scope_ref: str | None = Field(default=None, max_length=200)
