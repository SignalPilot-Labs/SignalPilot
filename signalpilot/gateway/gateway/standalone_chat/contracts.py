"""Versioned contracts for the enterprise standalone data-chat runtime.

These models describe durable gateway-owned records and public events. They do
not enable enterprise execution by themselves; rollout remains controlled by
the feature boundaries in :mod:`gateway.standalone_chat.config`.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSION = "enterprise-data-chat-v1"
DEFAULT_PER_QUERY_BUDGET_USD = Decimal("0.25")
DEFAULT_CHAT_BUDGET_USD = Decimal("1.00")

Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6)]


class StrictContract(BaseModel):
    """Base for persisted contracts: reject accidental or stale fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class QueryProposalStatus(StrEnum):
    proposed = "proposed"
    estimated = "estimated"
    waiting_for_approval = "waiting_for_approval"
    approved = "approved"
    declined = "declined"
    executing = "executing"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"


class EnterpriseRunStatus(StrEnum):
    queued = "queued"
    running = "running"
    waiting_for_user = "waiting_for_user"
    waiting_for_query_approval = "waiting_for_query_approval"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class QueryPath(StrEnum):
    sdk = "sdk"
    mcp = "mcp"
    direct_api = "direct_api"


class EstimateQuality(StrEnum):
    exact = "exact"
    approximate = "approximate"
    unknown = "unknown"
    conservative_fallback = "conservative_fallback"
    unavailable = "unavailable"


class QueryRoute(StrEnum):
    mcp = "mcp"
    notebook_sdk = "notebook_sdk"
    dataset_ref = "dataset_ref"
    aggregate_required = "aggregate_required"
    refuse = "refuse"


class ExecutionNeed(StrEnum):
    sql = "sql"
    python = "python"


class CompletenessState(StrEnum):
    complete = "complete"
    truncated = "truncated"
    unknown = "unknown"


class ApprovalScope(StrEnum):
    run_once = "run_once"
    current_chat = "current_chat"
    user_defaults = "user_defaults"


class ResultColumn(StrictContract):
    name: str = Field(min_length=1, max_length=256)
    logical_type: str = Field(min_length=1, max_length=100)
    nullable: bool


class Completeness(StrictContract):
    state: CompletenessState
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_truncation_reason(self) -> Completeness:
        if self.state == CompletenessState.truncated and not self.reason:
            raise ValueError("Truncated completeness requires a reason")
        if self.state == CompletenessState.complete and self.reason:
            raise ValueError("Complete data cannot have a truncation reason")
        return self


class QueryScope(StrictContract):
    org_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    conversation_id: str = Field(min_length=1, max_length=200)
    run_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    commit_sha: str
    connection_id: str = Field(min_length=1, max_length=200)

    @field_validator("commit_sha")
    @classmethod
    def validate_commit_sha(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", normalized):
            raise ValueError("commit_sha must be a full 40-character Git SHA")
        return normalized


class QueryEstimate(StrictContract):
    estimated_cost_usd: Money
    quality: EstimateQuality
    estimated_rows: int | None = Field(default=None, ge=0)
    estimated_bytes: int | None = Field(default=None, ge=0)
    estimated_duration_ms: int | None = Field(default=None, ge=0)
    planner_cost: Decimal | None = Field(default=None, ge=0)
    warning: str | None = Field(default=None, max_length=500)
    native_cap: dict[str, Any] | None = None


class BudgetPolicy(StrictContract):
    per_query_budget_usd: Money = DEFAULT_PER_QUERY_BUDGET_USD
    chat_budget_usd: Money = DEFAULT_CHAT_BUDGET_USD

    @model_validator(mode="after")
    def chat_budget_covers_query_budget(self) -> BudgetPolicy:
        if self.chat_budget_usd < self.per_query_budget_usd:
            raise ValueError("chat_budget_usd must be at least per_query_budget_usd")
        return self


class BudgetLedger(StrictContract):
    policy: BudgetPolicy
    estimated_spend_usd: Money = Decimal("0")
    actual_spend_usd: Money = Decimal("0")
    reserved_spend_usd: Money = Decimal("0")

    @property
    def remaining_chat_budget_usd(self) -> Decimal:
        consumed = self.actual_spend_usd + self.reserved_spend_usd
        return max(Decimal("0"), self.policy.chat_budget_usd - consumed)


class QueryProposal(StrictContract):
    id: str = Field(min_length=1, max_length=200)
    scope: QueryScope
    path: QueryPath
    purpose: str = Field(min_length=1, max_length=2_000)
    normalized_sql: str = Field(min_length=1, max_length=1_000_000)
    sql_hash: str
    timeout_seconds: int = Field(gt=0, le=3_600)
    status: QueryProposalStatus = QueryProposalStatus.proposed
    estimate: QueryEstimate | None = None
    policy_version: str = Field(min_length=1, max_length=100)
    created_at: datetime

    @field_validator("sql_hash")
    @classmethod
    def validate_sql_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", normalized):
            raise ValueError("sql_hash must be a SHA-256 hex digest")
        return normalized

    @model_validator(mode="after")
    def estimated_states_require_estimate(self) -> QueryProposal:
        if self.status not in {QueryProposalStatus.proposed, QueryProposalStatus.declined} and self.estimate is None:
            raise ValueError(f"{self.status.value} query proposals require an estimate")
        return self


class QueryExecution(StrictContract):
    id: str = Field(min_length=1, max_length=200)
    proposal_id: str = Field(min_length=1, max_length=200)
    scope: QueryScope
    sql_hash: str
    timeout_seconds: int = Field(gt=0, le=3_600)
    warehouse_query_id: str | None = Field(default=None, max_length=500)
    result_id: str | None = Field(default=None, max_length=200)
    estimated_cost_usd: Money
    actual_cost_usd: Money | None = None
    started_at: datetime | None = None
    terminal_at: datetime | None = None

    _validate_sql_hash = field_validator("sql_hash")(QueryProposal.validate_sql_hash.__func__)


class ResultProvenance(StrictContract):
    query_execution_id: str = Field(min_length=1, max_length=200)
    sql_hash: str
    project_id: str = Field(min_length=1, max_length=200)
    commit_sha: str
    connection_id: str = Field(min_length=1, max_length=200)
    runtime_version: str = Field(min_length=1, max_length=200)
    plugin_version: str = Field(min_length=1, max_length=200)
    source_names: list[str] = Field(default_factory=list)
    model_names: list[str] = Field(default_factory=list)
    freshness_at: datetime | None = None

    _validate_sql_hash = field_validator("sql_hash")(QueryProposal.validate_sql_hash.__func__)
    _validate_commit_sha = field_validator("commit_sha")(QueryScope.validate_commit_sha.__func__)


class StructuredResult(StrictContract):
    id: str = Field(min_length=1, max_length=200)
    org_id: str = Field(min_length=1, max_length=200)
    owner_user_id: str = Field(min_length=1, max_length=200)
    columns: list[ResultColumn]
    query_row_count: int | None = Field(default=None, ge=0)
    saved_row_count: int = Field(ge=0)
    preview_rows: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    source_completeness: Completeness
    result_completeness: Completeness
    display_completeness: Completeness
    provenance: ResultProvenance
    created_at: datetime

    @model_validator(mode="after")
    def saved_rows_fit_known_query_rows(self) -> StructuredResult:
        if self.query_row_count is not None and self.saved_row_count > self.query_row_count:
            raise ValueError("saved_row_count cannot exceed query_row_count")
        return self


class QueryApproval(StrictContract):
    id: str = Field(min_length=1, max_length=200)
    proposal_id: str = Field(min_length=1, max_length=200)
    approver_user_id: str = Field(min_length=1, max_length=200)
    scope: ApprovalScope
    sql_hash: str
    connection_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    run_id: str = Field(min_length=1, max_length=200)
    approved_estimated_cost_usd: Money
    policy_version: str = Field(min_length=1, max_length=100)
    expires_at: datetime
    created_at: datetime

    _validate_sql_hash = field_validator("sql_hash")(QueryProposal.validate_sql_hash.__func__)


class ShareContract(StrictContract):
    conversation_id: str = Field(min_length=1, max_length=200)
    owner_user_id: str = Field(min_length=1, max_length=200)
    org_id: str = Field(min_length=1, max_length=200)
    authenticated: Literal[True] = True
    same_organization_only: Literal[True] = True
    completed_content_only: Literal[True] = True
    live_completed_updates: Literal[True] = True


class ForkContract(StrictContract):
    parent_conversation_id: str = Field(min_length=1, max_length=200)
    recipient_user_id: str = Field(min_length=1, max_length=200)
    org_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    commit_sha: str
    budget: BudgetPolicy
    confirmed_at: datetime
    fresh_sandbox_required: Literal[True] = True
    parent_snapshot_immutable: Literal[True] = True

    _validate_commit_sha = field_validator("commit_sha")(QueryScope.validate_commit_sha.__func__)


class QueryEventType(StrEnum):
    query_proposed = "query_proposed"
    query_estimated = "query_estimated"
    query_approval_requested = "query_approval_requested"
    query_approved = "query_approved"
    query_declined = "query_declined"
    query_started = "query_started"
    query_progress = "query_progress"
    query_completed = "query_completed"
    query_cancelled = "query_cancelled"


class QueryPublicEvent(StrictContract):
    contract_version: Literal["enterprise-data-chat-v1"] = CONTRACT_VERSION
    type: QueryEventType
    run_id: str = Field(min_length=1, max_length=200)
    proposal_id: str = Field(min_length=1, max_length=200)
    query_execution_id: str | None = Field(default=None, max_length=200)
    sequence: int = Field(ge=1)
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


def stable_sql_hash(normalized_sql: str) -> str:
    """Return the approval-binding hash for already-normalized SQL."""
    return hashlib.sha256(normalized_sql.encode("utf-8")).hexdigest()
