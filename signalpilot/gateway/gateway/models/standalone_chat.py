"""Public API contracts for standalone data chat and authenticated sharing."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from gateway.standalone_chat.config import CHAT_EFFORT_IDS, CHAT_MODEL_IDS

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
    "runtime_boot",
    "steering_queued",
    "steering_picked_up",
    "steering_not_delivered",
    "text_delta",
    "thinking_delta",
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
    "files_changed",
    "files_archived",
]

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
    available_models: list[dict[str, str]] = Field(default_factory=list)
    default_model: str
    available_efforts: list[dict[str, str]] = Field(default_factory=list)
    default_effort: str = "medium"
    enterprise_features: dict[str, bool] = Field(default_factory=dict)


class StandaloneConversationCreate(StrictChatRequest):
    project_id: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=50_000)
    per_query_budget_usd: float = Field(default=0.25, ge=0)
    chat_budget_usd: float = Field(default=1.0, ge=0)
    model: str | None = Field(default=None, max_length=50)
    effort: str | None = Field(default=None, max_length=20)
    report_reference: ReportReference | None = None

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

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value is not None and value not in CHAT_MODEL_IDS:
            raise ValueError("Unsupported chat model")
        return value

    @field_validator("effort")
    @classmethod
    def validate_effort(cls, value: str | None) -> str | None:
        if value is not None and value not in CHAT_EFFORT_IDS:
            raise ValueError("Unsupported thinking level")
        return value


class StandaloneConversationModelUpdate(StrictChatRequest):
    model: str = Field(..., min_length=1, max_length=50)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if value not in CHAT_MODEL_IDS:
            raise ValueError("Unsupported chat model")
        return value


class StandaloneConversationEffortUpdate(StrictChatRequest):
    effort: str = Field(..., min_length=1, max_length=20)

    @field_validator("effort")
    @classmethod
    def validate_effort(cls, value: str) -> str:
        if value not in CHAT_EFFORT_IDS:
            raise ValueError("Unsupported thinking level")
        return value


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


class StandaloneSteeringCreate(StandaloneClarificationCreate):
    """A follow-up instruction queued onto an in-progress run."""


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


class StandaloneConversationInfo(BaseModel):
    id: str
    project_id: str
    project_name: str | None = None
    branch: str
    title: str
    status: Literal["active", "archived"]
    origin: str = "user"
    created_at: float
    updated_at: float
    run_status: ChatRunStatus | None = None
    commit_sha: str | None = None
    model: str
    effort: str = "medium"
    per_query_budget_usd: float = 0.25
    chat_budget_usd: float = 1.0
    estimated_spend_usd: float = 0.0
    actual_spend_usd: float = 0.0
    reserved_spend_usd: float = 0.0


class StandaloneConversationDetail(BaseModel):
    conversation: StandaloneConversationInfo
    messages: list[StandaloneMessageInfo]
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


class SharedConversationDetail(BaseModel):
    conversation: SharedConversationInfo
    messages: list[SharedMessageInfo]
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
