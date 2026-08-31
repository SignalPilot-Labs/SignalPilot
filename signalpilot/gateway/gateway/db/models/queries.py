"""Define governed query, dashboard, runtime dataset, and trace models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import GatewayBase, TZDateTime


class GatewayGovernedQueryExecution(GatewayBase):
    """Durable identity and outcome for every governed database query."""

    __tablename__ = "gateway_governed_query_executions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String)
    conversation_id: Mapped[str | None] = mapped_column(String)
    run_id: Mapped[str | None] = mapped_column(String)
    project_id: Mapped[str | None] = mapped_column(String)
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    plan_id: Mapped[str | None] = mapped_column(String)
    query_path: Mapped[str] = mapped_column(String(30), nullable=False)
    sql_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    warehouse_query_id: Mapped[str | None] = mapped_column(String(500))
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float)
    actual_scan_bytes: Mapped[int | None] = mapped_column(BigInteger)
    actual_output_bytes: Mapped[int | None] = mapped_column(BigInteger)
    execution_ms: Mapped[float | None] = mapped_column(Float)
    row_count: Mapped[int | None] = mapped_column(Integer)
    completeness: Mapped[str | None] = mapped_column(String(20))
    truncation_reason: Mapped[str | None] = mapped_column(String(500))
    public_error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    terminal_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (
        Index("ix_gw_query_execution_scope", "org_id", "user_id", "created_at"),
        Index("ix_gw_query_execution_run", "org_id", "run_id", "created_at"),
        Index("ix_gw_query_execution_hash", "org_id", "connection_name", "sql_hash"),
    )


class GatewayStructuredQueryResult(GatewayBase):
    """Bounded gateway-owned rows and metadata from one governed execution."""

    __tablename__ = "gateway_structured_query_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id: Mapped[str | None] = mapped_column(String, unique=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String)
    conversation_id: Mapped[str | None] = mapped_column(String)
    run_id: Mapped[str | None] = mapped_column(String)
    columns_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    rows_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    preview_rows_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    storage_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="inline", server_default="inline")
    object_key: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    source_result_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    code_hash: Mapped[str | None] = mapped_column(String(64))
    result_origin: Mapped[str] = mapped_column(String(20), nullable=False, default="mcp", server_default="mcp")
    query_row_count: Mapped[int | None] = mapped_column(Integer)
    saved_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_completeness: Mapped[str] = mapped_column(String(20), nullable=False)
    result_completeness: Mapped[str] = mapped_column(String(20), nullable=False)
    display_completeness: Mapped[str] = mapped_column(String(20), nullable=False)
    truncation_reason: Mapped[str | None] = mapped_column(String(500))
    provenance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    freshness_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (Index("ix_gw_structured_result_owner", "org_id", "owner_user_id", "created_at"),)


class GatewayDashboard(GatewayBase):
    """Stable dashboard identity; content lives in immutable versions."""

    __tablename__ = "gateway_dashboards"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(String)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="private", server_default="private")
    parent_dashboard_id: Mapped[str | None] = mapped_column(String)
    parent_version_id: Mapped[str | None] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_gw_dashboards_private", "org_id", "owner_user_id", "updated_at"),
        Index("ix_gw_dashboards_visibility", "org_id", "visibility", "updated_at"),
        Index("ix_gw_dashboards_project", "org_id", "project_id"),
    )


class GatewayDashboardVersion(GatewayBase):
    """Immutable, normalized DashboardDefinition publication."""

    __tablename__ = "gateway_dashboard_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    dashboard_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    semantic_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    authoring_provenance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("dashboard_id", "ordinal", name="uq_gw_dashboard_version_ordinal"),
        UniqueConstraint("dashboard_id", "content_hash", name="uq_gw_dashboard_version_content"),
        Index("ix_gw_dashboard_versions_dashboard", "org_id", "dashboard_id", "ordinal"),
    )


class GatewayDashboardAuthoringSession(GatewayBase):
    """Private durable authoring conversation with one current unsaved draft."""

    __tablename__ = "gateway_dashboard_authoring_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id: Mapped[str] = mapped_column(String, nullable=False, default=lambda: str(uuid.uuid4()))
    dashboard_id: Mapped[str | None] = mapped_column(String)
    base_version_id: Mapped[str | None] = mapped_column(String)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    semantic_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    definition_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    operations_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    events_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    agent_runs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    confirmations_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    pending_custom_sql_chart_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    agent_run_id: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="preview", server_default="preview")
    requires_custom_sql_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    custom_sql_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applied_version_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    discarded_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (
        Index("ix_gw_dashboard_authoring_owner", "org_id", "owner_user_id", "created_at"),
        Index("ix_gw_dashboard_authoring_dashboard", "org_id", "dashboard_id", "created_at"),
        Index("ix_gw_dashboard_authoring_thread", "org_id", "owner_user_id", "thread_id", "created_at"),
    )


class GatewayDashboardResult(GatewayBase):
    """Dashboard-authorized pointer to one governed structured query result."""

    __tablename__ = "gateway_dashboard_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    dashboard_id: Mapped[str] = mapped_column(String, nullable=False)
    version_id: Mapped[str] = mapped_column(String, nullable=False)
    chart_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    execution_id: Mapped[str] = mapped_column(String, nullable=False)
    structured_result_id: Mapped[str] = mapped_column(String, nullable=False)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sql_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tables_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    semantic_definition_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    completeness: Mapped[str] = mapped_column(String(20), nullable=False)
    freshness_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_gw_dashboard_result_cache", "org_id", "dashboard_id", "version_id", "cache_key"),
        Index("ix_gw_dashboard_result_access", "org_id", "dashboard_id", "id"),
    )


class GatewayQueryPlan(GatewayBase):
    """Immutable route decision bound to SQL, policy, and one execution scope."""

    __tablename__ = "gateway_query_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String)
    conversation_id: Mapped[str | None] = mapped_column(String)
    run_id: Mapped[str | None] = mapped_column(String)
    project_id: Mapped[str | None] = mapped_column(String)
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    branch: Mapped[str | None] = mapped_column(String(100))
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    execution_need: Mapped[str] = mapped_column(String(20), nullable=False)
    normalized_sql: Mapped[str] = mapped_column(Text, nullable=False)
    sql_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    estimated_scan_rows: Mapped[int | None] = mapped_column(BigInteger)
    estimated_scan_bytes: Mapped[int | None] = mapped_column(BigInteger)
    estimated_output_rows: Mapped[int | None] = mapped_column(BigInteger)
    estimated_output_bytes: Mapped[int | None] = mapped_column(BigInteger)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    estimate_quality: Mapped[str] = mapped_column(String(20), nullable=False)
    route: Mapped[str] = mapped_column(String(30), nullable=False)
    route_reason: Mapped[str] = mapped_column(Text, nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    proposal_id: Mapped[str | None] = mapped_column(String)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    shadow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scout_row_limit: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (
        Index("ix_gw_query_plan_scope", "org_id", "user_id", "run_id", "created_at"),
        Index("ix_gw_query_plan_hash", "org_id", "connection_name", "sql_hash"),
    )


class GatewayRuntimeDataset(GatewayBase):
    """Opaque, expiring Parquet dataset produced by streamed governed execution."""

    __tablename__ = "gateway_runtime_datasets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    plan_id: Mapped[str] = mapped_column(String, nullable=False)
    query_execution_id: Mapped[str] = mapped_column(String, nullable=False)
    schema_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completeness: Mapped[str] = mapped_column(String(20), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "plan_id", name="uq_gw_runtime_dataset_plan"),
        Index("ix_gw_runtime_dataset_owner", "org_id", "owner_user_id", "run_id"),
        Index("ix_gw_runtime_dataset_expiry", "expires_at"),
    )


class GatewayChatRuntimeArchive(GatewayBase):
    """Owner-only static notebook snapshot retained after its kernel stops."""

    __tablename__ = "gateway_chat_runtime_archives"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    source_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    html_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured outputs snapshot (NotebookSessionV1). Nullable: legacy
    # archives and runs whose snapshot serialization failed have none.
    session_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    html_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    session_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (Index("ix_gw_chat_archive_owner", "org_id", "user_id", "run_id"),)


class GatewayChatObjectDeletion(GatewayBase):
    """Idempotent asynchronous deletion request for one conversation prefix."""

    __tablename__ = "gateway_chat_object_deletions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    object_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (Index("ix_gw_chat_object_deletion_pending", "status", "created_at"),)


class GatewayQueryProposal(GatewayBase):
    """Durable estimated SQL unit awaiting automatic or explicit approval."""

    __tablename__ = "gateway_query_proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    plan_id: Mapped[str | None] = mapped_column(String)
    query_path: Mapped[str] = mapped_column(String(30), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_sql: Mapped[str] = mapped_column(Text, nullable=False)
    sql_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    estimate_quality: Mapped[str] = mapped_column(String(30), nullable=False)
    estimate_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False, default="chat-budget-v1")
    reserved_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    terminal_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (
        UniqueConstraint("run_id", "sql_hash", name="uq_gw_query_proposal_run_hash"),
        Index("ix_gw_query_proposal_waiting", "org_id", "user_id", "status", "created_at"),
    )


class GatewayQueryApproval(GatewayBase):
    """Idempotent user decision bound to one exact proposed query."""

    __tablename__ = "gateway_query_approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    proposal_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    approver_user_id: Mapped[str] = mapped_column(String, nullable=False)
    approval_scope: Mapped[str] = mapped_column(String(30), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    sql_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    per_query_budget_usd: Mapped[float | None] = mapped_column(Float)
    chat_budget_usd: Mapped[float | None] = mapped_column(Float)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("proposal_id", "approver_user_id", name="uq_gw_query_approval_decision"),
        Index("ix_gw_query_approval_owner", "org_id", "approver_user_id", "created_at"),
    )


class GatewayChatTraceThread(GatewayBase):
    """Durable agent trace thread metadata for notebook-originated chats."""

    __tablename__ = "gateway_chat_trace_threads"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    thread_id: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    notebook_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notion_request_page_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notion_discussion_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("org_id", "thread_id", name="uq_gw_trace_thread_org"),
        Index("ix_gw_trace_threads_session_org", "org_id", "session_id", "updated_at"),
        Index("ix_gw_trace_threads_source_org", "org_id", "source", "updated_at"),
    )


class GatewayChatTraceEvent(GatewayBase):
    """Ordered trace event within a durable notebook chat thread."""

    __tablename__ = "gateway_chat_trace_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    thread_id: Mapped[str] = mapped_column(String, nullable=False)
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    tool_input_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    tool_call_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    is_error: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    turn: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("org_id", "thread_id", "idx", name="uq_gw_trace_event_org_idx"),
        Index("ix_gw_trace_events_thread_idx_org", "org_id", "thread_id", "idx"),
    )


class GatewayAnalysisTrail(GatewayBase):
    """Durable metadata for external-source notebook analyses."""

    __tablename__ = "gateway_analysis_trails"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(300), nullable=False)
    runtime_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    branch: Mapped[str] = mapped_column(String(100), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    notebook_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    latest_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_thread_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_request_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    analysis_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "source", "request_id", name="uq_gw_analysis_trail_request"),
        Index("ix_gw_analysis_trail_thread", "org_id", "thread_id"),
        Index("ix_gw_analysis_trail_project", "org_id", "project_id", "branch"),
        Index("ix_gw_analysis_trail_source_status", "org_id", "source", "status"),
    )

