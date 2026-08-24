"""Public API contracts for durable governed dashboards."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from gateway.dashboard.domain import DashboardDefinition


class DashboardModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateDashboardRequest(DashboardModel):
    definition: DashboardDefinition


class CreateDashboardVersionRequest(DashboardModel):
    definition: DashboardDefinition
    expected_current_version_id: str = Field(min_length=1)


class DashboardListItem(DashboardModel):
    id: str
    name: str
    description: str | None
    project_id: str
    connection_name: str
    timezone: str
    current_version_id: str
    revision: int
    updated_at: datetime


class DashboardVersionInfo(DashboardModel):
    id: str
    ordinal: int
    content_hash: str
    commit_sha: str
    semantic_fingerprint: str
    created_at: datetime
    definition: DashboardDefinition


class DashboardDetail(DashboardModel):
    dashboard: DashboardListItem
    version: DashboardVersionInfo


class DashboardQueryRequest(DashboardModel):
    version_id: str | None = None
    refresh: bool = False


class DashboardQueryReceipt(DashboardModel):
    dashboard_result_id: str
    result_id: str
    execution_id: str
    columns: list[dict]
    rows: list[dict]
    row_count: int
    completeness: str
    result_time: datetime
    freshness_at: datetime | None
    sql_hash: str
    parameter_hash: str
    tables: list[str]
    semantic_definition: dict
    compiled_sql: str | None
    cache_state: str


class DashboardSemanticField(DashboardModel):
    field_id: str
    column: str
    logical_type: str
    description: str | None = None
    tests: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class DashboardSemanticMetric(DashboardSemanticField):
    aggregation: str
    label: str
    format: str | None = None
    approval_source: str
    human_verified: bool


class DashboardSemanticExplore(DashboardModel):
    name: str
    label: str
    relation: str
    description: str | None = None
    dimensions: list[DashboardSemanticField]
    metrics: list[DashboardSemanticMetric]
    joins: list[dict] = Field(default_factory=list)


class DashboardSemanticContext(DashboardModel):
    project_id: str
    commit_sha: str
    connection_name: str
    connection_type: str
    physical_schema_fingerprint: str
    semantic_fingerprint: str
    explores: list[DashboardSemanticExplore]
    verification_refs: list[str] = Field(default_factory=list)
    eval_refs: list[str] = Field(default_factory=list)
