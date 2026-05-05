"""Notebook Pydantic models: upload payload, metadata, and analysis results."""

from __future__ import annotations

import re
import time

from pydantic import BaseModel, Field, field_validator

from ._helpers import _validate_string_list

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


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


class ImportCount(BaseModel):
    """Import name paired with its occurrence count across notebooks."""

    name: str
    count: int


class NotebookSummary(BaseModel):
    """Aggregate statistics across all notebooks."""

    total_notebooks: int
    total_cells: int
    total_code_cells: int
    total_markdown_cells: int
    total_code_lines: int
    analyzed_count: int
    pending_count: int
    notebooks_with_errors: int
    total_error_cells: int
    top_imports: list[ImportCount]


class BatchNotebookRequest(BaseModel):
    """Request body for batch operations on notebooks."""

    notebook_ids: list[str] = Field(..., min_length=1, max_length=50)

    @field_validator("notebook_ids")
    @classmethod
    def validate_notebook_ids(cls, v: list[str]) -> list[str]:
        for nid in v:
            if not _UUID_PATTERN.match(nid):
                raise ValueError(f"Invalid notebook ID format: '{nid}'")
        return v


class BatchResultItem(BaseModel):
    """Per-notebook result from a batch operation."""

    notebook_id: str
    success: bool
    error: str | None = None


class BatchResult(BaseModel):
    """Aggregated result from a batch operation."""

    results: list[BatchResultItem]
    succeeded: int
    failed: int
