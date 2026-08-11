"""Public API contracts for standalone data chat and authenticated sharing."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .chat_reports import ReportReference

ChatRunStatus = Literal[
    "queued",
    "running",
    "waiting_for_user",
    "waiting_for_query_approval",
    "completed",
    "failed",
    "cancelled",
]
ChatEventType = Literal[
    "status",
    "progress",
    "text_delta",
    "tool_started",
    "tool_completed",
    "sql",
    "source",
    "intermediate_result",
    "clarification_requested",
    "artifact_created",
    "error",
    "query_proposed",
    "query_estimated",
    "query_approval_requested",
    "query_approved",
    "query_declined",
    "query_started",
    "query_progress",
    "query_completed",
    "query_cancelled",
    "plan_created",
    "route_selected",
    "notebook_started",
    "cell_executed",
    "runtime_result_created",
    "archive_completed",
    "kernel_stopped",
]
ArtifactKind = Literal["table", "chart", "report"]


class StrictChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StandaloneChatProject(BaseModel):
    id: str
    name: str
    display_name: str
    connection_name: str | None = None
    default_branch: str
    ready: bool
    readiness_message: str


class ChatBootstrapResponse(BaseModel):
    enabled: bool
    projects: list[StandaloneChatProject]
    selected_project_id: str | None
    is_admin: bool
    starter_questions: list[str] = Field(default_factory=list, min_length=0, max_length=4)
    default_per_query_budget_usd: float = 0.25
    default_chat_budget_usd: float = 1.0
    enterprise_features: dict[str, bool] = Field(default_factory=dict)


class StandaloneConversationCreate(StrictChatRequest):
    project_id: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=50_000)
    per_query_budget_usd: float = Field(default=0.25, ge=0)
    chat_budget_usd: float = Field(default=1.0, ge=0)

    @field_validator("project_id", "message")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value cannot be empty")
        return cleaned

    @model_validator(mode="after")
    def validate_budgets(self):
        if self.chat_budget_usd < self.per_query_budget_usd:
            raise ValueError("Chat budget must be at least the per-query budget")
        return self


class QueryApprovalDecision(StrictChatRequest):
    decision: Literal["approve", "decline"]
    scope: Literal["run_once", "current_chat", "user_defaults"] = "run_once"
    per_query_budget_usd: float | None = Field(default=None, ge=0)
    chat_budget_usd: float | None = Field(default=None, ge=0)


class StandaloneRunCreate(StrictChatRequest):
    message: str = Field(..., min_length=1, max_length=50_000)
    report_reference: ReportReference | None = None

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Message cannot be empty")
        return cleaned


class StandaloneConversationPatch(StrictChatRequest):
    title: str = Field(..., min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = " ".join(value.split()).strip()
        if not cleaned:
            raise ValueError("Title cannot be empty")
        return cleaned


class StandaloneClarificationCreate(StrictChatRequest):
    message: str = Field(..., min_length=1, max_length=50_000)

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Message cannot be empty")
        return cleaned


class ChatRunInfo(BaseModel):
    id: str
    conversation_id: str
    status: ChatRunStatus
    retry_of_run_id: str | None = None
    public_error_code: str | None = None
    public_error_message: str | None = None
    cancellation_requested_at: datetime | None = None
    created_at: datetime
    started_at: datetime | None = None
    terminal_at: datetime | None = None
    last_event_sequence: int
    runtime_archive_available: bool = False


class StandaloneMessageInfo(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    sequence: int
    created_at: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatRunEventInfo(BaseModel):
    run_id: str
    sequence: int
    type: ChatEventType
    payload: dict[str, Any]
    created_at: datetime


class ChatArtifactInfo(BaseModel):
    id: str
    run_id: str
    assistant_message_id: str | None = None
    kind: ArtifactKind
    filename: str
    mime_type: str
    snapshot: dict[str, Any]
    provenance: dict[str, Any] | None = None
    freshness_at: datetime | None = None
    assumptions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    parent_artifact_id: str | None = None
    saved_report_id: str | None = None
    saved_report_version_id: str | None = None
    saved_report_title: str | None = None
    report_action: Literal["create", "update", "open"] = "create"
    created_at: datetime
    download_formats: list[str]


class StandaloneConversationInfo(BaseModel):
    id: str
    project_id: str
    project_name: str | None = None
    branch: str
    title: str
    status: Literal["active", "archived"]
    created_at: float
    updated_at: float
    run_status: ChatRunStatus | None = None
    commit_sha: str | None = None
    per_query_budget_usd: float = 0.25
    chat_budget_usd: float = 1.0
    estimated_spend_usd: float = 0.0
    actual_spend_usd: float = 0.0
    reserved_spend_usd: float = 0.0


class StandaloneConversationDetail(BaseModel):
    conversation: StandaloneConversationInfo
    messages: list[StandaloneMessageInfo]
    artifacts: list[ChatArtifactInfo]
    current_run: ChatRunInfo | None = None
    run_events: list[ChatRunEventInfo] = Field(default_factory=list)


class ChatShareGrantInfo(BaseModel):
    token: str
    created_at: datetime


class SharedConversationInfo(BaseModel):
    title: str
    project_name: str | None = None
    created_at: float
    updated_at: float


class SharedMessageInfo(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    sequence: int
    created_at: float


class SharedChatArtifactInfo(BaseModel):
    id: str
    assistant_message_id: str | None = None
    kind: ArtifactKind
    filename: str
    mime_type: str
    snapshot: dict[str, Any]
    freshness_at: datetime | None = None
    assumptions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    created_at: datetime
    download_formats: list[str]


class SharedConversationDetail(BaseModel):
    conversation: SharedConversationInfo
    messages: list[SharedMessageInfo]
    artifacts: list[SharedChatArtifactInfo]
    shared_at: datetime


class ForkedConversationInfo(BaseModel):
    id: str


class ForkPreviewInfo(BaseModel):
    project_id: str
    project_name: str
    commit_sha: str
    per_query_budget_usd: float
    chat_budget_usd: float
    warehouse_cost_notice: str


class ForkConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: Literal[True]
    per_query_budget_usd: float = Field(ge=0)
    chat_budget_usd: float = Field(ge=0)
