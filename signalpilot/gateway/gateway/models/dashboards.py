"""Public API contracts for durable governed dashboards."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gateway.dashboard.domain import (
    ChartDefinition,
    DashboardDefinition,
    DashboardFilterRule,
    FilterOperator,
    FilterSettings,
    Scalar,
)


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
    retry_token: str | None = Field(default=None, min_length=1, max_length=100)
    tile_uuid: str | None = None
    dashboard_filters: list[DashboardRuntimeFilter] | None = None
    drill_path: list[DashboardDrillStep] = Field(default_factory=list)


class DashboardClientTelemetryRequest(DashboardModel):
    event_type: Literal["dashboard_rendered", "dashboard_tile_render_failed"]
    version_id: str = Field(min_length=1, max_length=200)
    open_instance_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
    duration_ms: float | None = Field(default=None, ge=0, le=3_600_000)
    chart_id: str | None = Field(default=None, min_length=1, max_length=200)
    failure_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$",
    )


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


type DashboardFailureCode = Literal[
    "data_source_unavailable",
    "authentication_rejected",
    "query_timeout",
    "query_invalid",
    "semantic_definition_invalid",
    "permission_denied",
    "rate_limited",
    "cancelled",
    "result_contract_mismatch",
    "stale_dashboard_version",
    "internal_error",
]


class DashboardFailure(DashboardModel):
    code: DashboardFailureCode
    message: str
    retryable: bool
    connection_name: str | None = None
    scope: Literal["connection", "chart", "dashboard"]
    correlation_id: str
    occurred_at: datetime
    cache_fallback_available: bool = False
    cache_state: Literal["no_usable_cache"] | None = None
    retry_after_seconds: int | None = Field(default=None, ge=1, le=300)


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
    connection_type: str | None = None
    cache_state: Literal[
        "fresh",
        "stale_refreshing",
        "cached_source_unavailable",
        "cached_after_refresh_failure",
    ]
    refresh_failure: DashboardFailure | None = None


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


class DashboardProvisionalLayout(DashboardModel):
    x: int = Field(ge=0, le=35)
    y: int = Field(ge=0)
    w: int = Field(ge=1, le=36)
    h: int = Field(ge=1)


class DashboardChartIntent(DashboardModel):
    chart_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
    tile_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
    label: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    required_concepts: list[str] = Field(min_length=1, max_length=20)
    explore_name: str = Field(min_length=1, max_length=200)
    dimensions: list[str] = Field(default_factory=list, max_length=20)
    metrics: list[str] = Field(min_length=1, max_length=20)
    section: str = Field(min_length=1, max_length=120)
    order: int = Field(ge=0)
    layout: DashboardProvisionalLayout
    visualization: Literal["kpi", "table", "bar", "line", "area"]
    shared_filter_ids: list[str] = Field(default_factory=list, max_length=20)
    required: bool = True


class DashboardPlan(DashboardModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    intents: list[DashboardChartIntent] = Field(min_length=1, max_length=30)
    filters: list[DashboardFilterRule] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_stable_ids_and_layout(self) -> DashboardPlan:
        chart_ids = [intent.chart_id for intent in self.intents]
        tile_ids = [intent.tile_id for intent in self.intents]
        orders = [intent.order for intent in self.intents]
        filter_ids = [rule.id for rule in self.filters]
        if len(chart_ids) != len(set(chart_ids)):
            raise ValueError("Dashboard plan chart IDs must be unique")
        if len(tile_ids) != len(set(tile_ids)):
            raise ValueError("Dashboard plan tile IDs must be unique")
        if len(orders) != len(set(orders)):
            raise ValueError("Dashboard plan chart order must be unique")
        if len(filter_ids) != len(set(filter_ids)):
            raise ValueError("Dashboard plan filter IDs must be unique")
        known_filters = set(filter_ids)
        for intent in self.intents:
            if intent.layout.x + intent.layout.w > 36:
                raise ValueError(f"Dashboard plan tile exceeds the grid: {intent.tile_id}")
            unknown = set(intent.shared_filter_ids) - known_filters
            if unknown:
                raise ValueError(f"Dashboard plan references an unknown shared filter: {sorted(unknown)[0]}")
        return self


class DashboardChartDraftInfo(DashboardModel):
    chart_id: str
    ordinal: int
    intent: DashboardChartIntent
    status: Literal["pending", "running", "ready", "failed"]
    attempt_count: int = Field(ge=0, le=2)
    definition: ChartDefinition | None = None
    safe_error: str | None = None
    model_usage: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


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
    thread_id: str
    conversation_id: str | None = None
    dashboard_id: str | None
    base_version_id: str | None
    applied_version_id: str | None = None
    definition: DashboardDefinition | None
    plan: DashboardPlan | None = None
    expected_chart_count: int = 0
    chart_drafts: list[DashboardChartDraftInfo] = Field(default_factory=list)
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
