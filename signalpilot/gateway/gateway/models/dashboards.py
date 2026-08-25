"""Public API contracts for durable governed dashboards."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from gateway.dashboard.domain import DashboardDefinition, FilterOperator, FilterSettings, Scalar


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
    visibility: Literal["private", "organization"]
    owner_user_id: str
    is_owner: bool
    archived_at: datetime | None
    parent_dashboard_id: str | None
    parent_version_id: str | None
    high_confidence_charts: int = 0
    low_confidence_charts: int = 0
    updated_at: datetime


class DashboardVersionInfo(DashboardModel):
    id: str
    ordinal: int
    content_hash: str
    commit_sha: str
    semantic_fingerprint: str
    created_at: datetime
    definition: DashboardDefinition
    authoring_provenance: dict[str, Any] = Field(default_factory=dict)


class DashboardDetail(DashboardModel):
    dashboard: DashboardListItem
    version: DashboardVersionInfo


class DashboardVisibilityRequest(DashboardModel):
    visibility: Literal["private", "organization"]


class DashboardForkRequest(DashboardModel):
    version_id: str


class DashboardExportRequest(DashboardModel):
    version_id: str
    dashboard_result_ids: list[str] = Field(min_length=1, max_length=100)
    dashboard_filters: list[DashboardRuntimeFilter] = Field(default_factory=list)
    drill_paths: dict[str, list[DashboardDrillStep]] = Field(default_factory=dict)
    acknowledge_sensitive_data: bool = False


class DashboardExportGrant(DashboardModel):
    dashboard_id: str
    version_id: str
    authorized_result_ids: list[str]
    warning: str


class DashboardSuggestion(DashboardModel):
    dashboard_id: str
    dashboard_name: str
    version_id: str
    chart_id: str
    chart_title: str
    owner_user_id: str
    confidence: Literal["high"] = "high"
    freshness_at: datetime | None = None


class DashboardQueryRequest(DashboardModel):
    version_id: str | None = None
    authoring_session_id: str | None = None
    refresh: bool = False
    tile_uuid: str | None = None
    dashboard_filters: list[DashboardRuntimeFilter] | None = None
    drill_path: list[DashboardDrillStep] = Field(default_factory=list)


class DashboardRuntimeFilter(DashboardModel):
    id: str = Field(min_length=1)
    operator: FilterOperator
    values: list[Scalar] | None = None
    settings: FilterSettings | None = None


class DashboardDrillStep(DashboardModel):
    field_id: str = Field(min_length=1)
    value: Scalar


class DashboardDistinctValuesRequest(DashboardModel):
    version_id: str | None = None
    search: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=100, ge=1, le=100)


class DashboardDistinctValuesResponse(DashboardModel):
    values: list[Scalar]
    execution_id: str


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
    label: str | None = None
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


class DashboardAuthoringRequest(DashboardModel):
    prompt: str = Field(min_length=1, max_length=50_000)
    dashboard_id: str | None = None
    base_version_id: str | None = None
    project_id: str | None = None
    commit_sha: str | None = Field(default=None, min_length=40, max_length=40)
    branch: str | None = Field(default=None, min_length=1, max_length=100)
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    confirm_custom_sql: bool = False


class DashboardAuthoringMessageRequest(DashboardModel):
    prompt: str = Field(min_length=1, max_length=50_000)


class DashboardAuthoringEvent(DashboardModel):
    id: str
    sequence: int
    kind: Literal["user", "assistant", "progress", "validation", "confirmation", "system"]
    status: Literal["info", "success", "error", "pending"] = "info"
    message: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class DashboardAuthoringSessionInfo(DashboardModel):
    id: str
    dashboard_id: str | None
    base_version_id: str | None
    definition: DashboardDefinition
    operations: list[dict[str, Any]]
    summary: str
    agent_run_id: str
    model: str
    status: str
    requires_custom_sql_confirmation: bool
    custom_sql_confirmed: bool
    custom_sql_chart_ids: list[str] = Field(default_factory=list)
    draft_revision: int = 1
    events: list[DashboardAuthoringEvent] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class DashboardAuthoringApplyRequest(DashboardModel):
    expected_current_version_id: str | None = None
    visible_complete_result_ids: list[str] = Field(default_factory=list, max_length=100)


class DashboardChartReference(DashboardModel):
    dashboard_id: str
    dashboard_version_id: str
    tile_uuid: str
    chart_id: str
    dashboard_result_id: str
    execution_id: str
    dashboard_filters: list[DashboardRuntimeFilter] = Field(default_factory=list)
    date_window: dict[str, Any] | None = None
    drill_path: list[DashboardDrillStep] = Field(default_factory=list)
    selected_mark: dict[str, Any] = Field(default_factory=dict)
    semantic_references: dict[str, Any]
    receipt: dict[str, Any]
    result: dict[str, Any]
    provenance_ref: str


class DashboardAnalyzeRequest(DashboardModel):
    version_id: str
    tile_uuid: str
    dashboard_result_id: str
    dashboard_filters: list[DashboardRuntimeFilter] = Field(default_factory=list)
    drill_path: list[DashboardDrillStep] = Field(default_factory=list)
    selected_mark: dict[str, Any] = Field(default_factory=dict)
    message: str = Field(min_length=1, max_length=50_000)


class DashboardAnalyzeResponse(DashboardModel):
    conversation_id: str
    chart_reference: DashboardChartReference
