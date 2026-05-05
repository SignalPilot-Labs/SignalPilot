"""Notebook Pydantic models: upload payload, metadata, and analysis results."""

from __future__ import annotations

import time

from pydantic import BaseModel, Field, field_validator

from ._helpers import _validate_string_list


class NotebookUpload(BaseModel):
    """Payload for uploading a Jupyter notebook."""

    name: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1)
    description: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        return _validate_string_list(v, 64, "tags")


class NotebookUpdate(BaseModel):
    """Payload for updating notebook metadata (PATCH semantics)."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = Field(default=None, max_length=50)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return _validate_string_list(v, 64, "tags")


class NotebookInfo(BaseModel):
    """Persisted metadata for an uploaded notebook."""

    id: str
    name: str
    description: str
    tags: list[str]
    cell_count: int
    code_cell_count: int
    markdown_cell_count: int
    kernel_name: str | None
    created_at: float
    updated_at: float
    analyzed_at: float | None


class NotebookAnalysis(BaseModel):
    """Full analysis results for a notebook."""

    notebook_id: str
    cell_counts: dict[str, int]
    imports: list[str]
    execution_order_gaps: list[int]
    error_cells: list[int]
    output_summary: dict[str, int]
    total_code_lines: int
    functions_defined: list[str]
    kernel_info: dict | None
    analyzed_at: float = Field(default_factory=time.time)
