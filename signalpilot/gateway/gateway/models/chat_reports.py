"""Public contracts for the Data Chat artifact library and saved reports."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ArtifactKind = Literal["table", "chart", "report"]
ReportAction = Literal["create", "update", "open"]
FreshnessState = Literal["fresh", "changes_detected", "unknown"]
RefreshState = Literal[
    "refreshing",
    "update_available",
    "failed",
    "current",
]


class StrictReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportReference(StrictReportRequest):
    report_id: str = Field(min_length=1, max_length=100)
    version_id: str = Field(min_length=1, max_length=100)


class ReportMention(BaseModel):
    report_id: str
    title: str
    kind: ArtifactKind
    project_id: str
    current_version_id: str


class ReportMentionCollection(BaseModel):
    items: list[ReportMention] = Field(default_factory=list)


class ReportCatalogCard(BaseModel):
    report_id: str
    title: str
    artifact_kind: ArtifactKind
    original_business_request: str
    main_output_fields: list[str] = Field(default_factory=list)
    query_purposes: list[str] = Field(default_factory=list)
    referenced_models: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    current_version_id: str
    current_version: int
    freshness_state: FreshnessState
    freshness_at: datetime | None = None
    updated_at: datetime


class ReportCatalogPage(BaseModel):
    items: list[ReportCatalogCard] = Field(default_factory=list)
    next_cursor: str | None = None
    catalog_revision: str
    total_reports: int
    proactive_creation_allowed: bool


class ReportContextMessage(BaseModel):
    request: str
    answer: str
    source_thread_id: str
    source_run_id: str


class ReportVersionTimelineItem(BaseModel):
    version_id: str
    version: int
    artifact_id: str
    artifact_kind: ArtifactKind
    artifact_filename: str
    source_thread_id: str
    source_thread_title: str
    source_run_id: str
    published_at: datetime


class ReportHistoricalQuery(BaseModel):
    source_run_id: str
    purpose: str
    normalized_sql: str
    referenced_models: list[str] = Field(default_factory=list)


class ReportContextPackage(BaseModel):
    report_id: str
    title: str
    artifact_kind: ArtifactKind
    project_id: str
    current_version_id: str
    current_version: int
    creation: ReportContextMessage
    current: ReportContextMessage
    version_timeline: list[ReportVersionTimelineItem]
    current_artifact: dict[str, Any]
    historical_queries: list[ReportHistoricalQuery]
    dbt_commit_sha: str | None = None
    freshness_state: FreshnessState
    freshness_at: datetime | None = None
    assumptions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class ReportSuggestion(BaseModel):
    action: ReportAction
    artifact_id: str
    title: str
    reason: str
    report_id: str | None = None
    expected_current_version_id: str | None = None
    catalog_revision: str | None = None


class ReportSuggestionApprovalResult(BaseModel):
    status: Literal["created", "updated", "existing", "opened"]
    report_id: str
    version_id: str


class PromoteArtifactRequest(StrictReportRequest):
    artifact_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        title = " ".join(value.split()).strip()
        if not title:
            raise ValueError("Title cannot be empty")
        return title


class PublishReportVersionRequest(StrictReportRequest):
    artifact_id: str = Field(min_length=1, max_length=100)
    expected_current_version_id: str = Field(min_length=1, max_length=100)


class LibraryArtifactHistoryItem(BaseModel):
    id: str
    kind: ArtifactKind
    filename: str
    created_at: datetime
    freshness_state: FreshnessState
    freshness_at: datetime | None = None
    freshness_checked_at: datetime
    saved_report_id: str | None = None
    saved_version_id: str | None = None
    snapshot: dict[str, Any]
    download_formats: list[str]


class LibraryArtifact(LibraryArtifactHistoryItem):
    project_id: str | None = None
    project_name: str | None = None
    original_thread_id: str
    original_thread_title: str
    history: list[LibraryArtifactHistoryItem] = Field(default_factory=list)


class LibraryReport(BaseModel):
    id: str
    report_id: str | None = None
    title: str
    kind: ArtifactKind
    filename: str
    is_shared: bool
    project_id: str | None = None
    project_name: str | None = None
    original_thread_id: str | None = None
    original_thread_title: str | None = None
    version_id: str
    version_ordinal: int
    freshness_state: FreshnessState
    freshness_at: datetime | None = None
    freshness_checked_at: datetime
    updated_at: datetime
    snapshot: dict[str, Any]
    download_url: str


class LibraryCollection(BaseModel):
    items: list[LibraryArtifact] | list[LibraryReport]
    next_cursor: str | None = None


class LibraryFacets(BaseModel):
    artifact_types: list[str] = Field(default_factory=list)
    projects: list[dict[str, str]] = Field(default_factory=list)
    original_threads: list[dict[str, str]] = Field(default_factory=list)


class ChatLibraryResponse(BaseModel):
    artifacts: LibraryCollection
    reports: LibraryCollection
    facets: LibraryFacets


class SavedVersionInfo(BaseModel):
    id: str
    ordinal: int
    kind: ArtifactKind
    filename: str
    content_hash: str
    freshness_state: FreshnessState
    freshness_at: datetime | None = None
    freshness_checked_at: datetime
    dbt_commit_sha: str | None = None
    schema_fingerprint: str | None = None
    published_at: datetime
    snapshot: dict[str, Any]
    download_url: str


class ReportRefreshInfo(BaseModel):
    id: str
    base_version_id: str
    status: RefreshState
    drift_state: Literal["none", "drift", "unknown"]
    explanation: str
    checked_at: datetime
    run_id: str | None = None
    conversation_id: str | None = None
    candidate_artifact_ids: list[str] = Field(default_factory=list)


class SavedReportDetail(BaseModel):
    id: str
    title: str
    kind: ArtifactKind
    project_id: str
    project_name: str | None = None
    original_thread_id: str
    original_thread_title: str
    current_version_id: str
    revision: int
    created_at: datetime
    updated_at: datetime
    current_version: SavedVersionInfo
    versions: list[SavedVersionInfo]
    active_share_version_ids: list[str] = Field(default_factory=list)
    refresh: ReportRefreshInfo | None = None


class PromotionResult(BaseModel):
    status: Literal["created", "existing", "updated"]
    report_id: str
    version_id: str


class VersionPublishResult(BaseModel):
    status: Literal["created", "existing"]
    report_id: str
    version_id: str
    current_version_id: str


class RefreshCreateResult(BaseModel):
    refresh_id: str
    report_id: str
    version_id: str
    conversation_id: str
    run_id: str | None = None
    status: RefreshState
    drift_state: Literal["none", "drift", "unknown"]
    explanation: str
    checked_at: datetime


class ReportShareGrantInfo(BaseModel):
    token: str
    version_id: str
    created_at: datetime


class SharedVersionInfo(BaseModel):
    id: str
    ordinal: int
    kind: ArtifactKind
    filename: str
    freshness_state: FreshnessState
    freshness_at: datetime | None = None
    freshness_checked_at: datetime
    published_at: datetime
    snapshot: dict[str, Any]
    download_url: str


class SharedSavedReport(BaseModel):
    title: str
    kind: ArtifactKind
    version: SharedVersionInfo
    shared_at: datetime
