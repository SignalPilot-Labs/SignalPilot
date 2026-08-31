"""Define chat conversation, message, run, artifact, and saved report models."""

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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import GatewayBase, TZDateTime

# Chat.


class GatewayChatConversation(GatewayBase):
    """Conversation header for per-user per-project chat."""

    __tablename__ = "gateway_chat_conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String)
    surface: Mapped[str] = mapped_column(String(20), nullable=False, default="notebook", server_default="notebook")
    # "user" (person-initiated) or "improvement" (system-initiated improvement run)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="user", server_default="user")
    branch: Mapped[str | None] = mapped_column(String(100))
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    per_query_budget_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.25, server_default="0.25")
    chat_budget_usd: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1.0")
    estimated_spend_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    actual_spend_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    reserved_spend_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    forked_from_conversation_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    internal_summary: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(200))
    agent_session_id: Mapped[str | None] = mapped_column(String)
    # Pointer to the conversation's analysis notebook. The chat worker writes
    # these fields when the agent starts or recovers the notebook. Null until
    # the first notebook start.
    notebook_session_id: Mapped[str | None] = mapped_column(String)
    notebook_kernel_session_id: Mapped[str | None] = mapped_column(String)
    notebook_path: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(50))
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_gw_conv_org_user", "org_id", "user_id"),
        Index("ix_gw_conv_org_proj", "org_id", "project_id"),
        Index("ix_gw_conv_updated", "org_id", "updated_at"),
        Index(
            "ix_gw_conv_standalone_history",
            "org_id",
            "user_id",
            "surface",
            "status",
            "updated_at",
        ),
    )


class GatewayChatMessage(GatewayBase):
    """Individual chat message within a conversation."""

    __tablename__ = "gateway_chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_gw_chat_conversation", "conversation_id", "sequence"),
        Index("ix_gw_chat_org_user_proj", "org_id", "user_id", "project_id"),
        Index("ix_gw_chat_org_created", "org_id", "created_at"),
        Index(
            "uq_gw_chat_message_idempotency",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class GatewayChatRun(GatewayBase):
    """Durable standalone-chat execution claimed by the chat worker."""

    __tablename__ = "gateway_chat_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    user_message_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued", server_default="queued")
    # Environment that created the run (SP_RUNTIME_ENV). Workers only claim runs
    # from their own environment; NULL rows are claimable by any worker.
    runtime_env: Mapped[str | None] = mapped_column(String(50))
    retry_of_run_id: Mapped[str | None] = mapped_column(String)
    execution_session_id: Mapped[str | None] = mapped_column(String)
    runtime_archive_id: Mapped[str | None] = mapped_column(String)
    execution_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    public_error_code: Mapped[str | None] = mapped_column(String(100))
    public_error_message: Mapped[str | None] = mapped_column(Text)
    # Operator-facing accounting from the agent SDK's result: total API cost
    # and the aggregate token usage dict (input/output/cache tokens) for the
    # turn. Never shown in the user UX.
    cost_usd: Mapped[float | None] = mapped_column(Float)
    usage_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    terminal_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        Index("ix_gw_chat_runs_queue", "status", "lease_expires_at", "created_at"),
        Index("ix_gw_chat_runs_owner", "org_id", "user_id", "conversation_id"),
        Index(
            "uq_gw_chat_run_nonterminal_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status IN ('queued','running','waiting_for_user','waiting_for_query_approval')"),
            sqlite_where=text("status IN ('queued','running','waiting_for_user','waiting_for_query_approval')"),
        ),
    )


class GatewayChatRunEvent(GatewayBase):
    """Author-visible, redacted event emitted by one standalone run."""

    __tablename__ = "gateway_chat_run_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_gw_chat_run_event_sequence"),
        Index("ix_gw_chat_run_events_owner", "org_id", "user_id", "run_id", "sequence"),
    )


class GatewayChatArtifact(GatewayBase):
    """Immutable standalone-chat artifact snapshot."""

    __tablename__ = "gateway_chat_artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    assistant_message_id: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    binary_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    storage_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="inline", server_default="inline")
    object_key: Mapped[str | None] = mapped_column(Text)
    source_object_key: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    provenance_json: Mapped[dict | None] = mapped_column(JSON)
    freshness_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    assumptions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    exclusions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    caveats: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    parent_artifact_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "kind",
            "filename",
            name="uq_gw_chat_artifact_publication",
        ),
        Index("ix_gw_chat_artifacts_owner", "org_id", "user_id", "conversation_id"),
        Index("ix_gw_chat_artifacts_run", "run_id", "created_at"),
    )


class GatewayChatShareGrant(GatewayBase):
    """Revocable same-organization access grant for one standalone chat."""

    __tablename__ = "gateway_chat_share_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (
        Index(
            "uq_gw_chat_share_active_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
            sqlite_where=text("state = 'active'"),
        ),
        Index(
            "ix_gw_chat_share_lookup",
            "org_id",
            "token_hash",
            "state",
        ),
        Index(
            "ix_gw_chat_share_owner",
            "org_id",
            "owner_user_id",
            "conversation_id",
            "state",
        ),
    )


class GatewaySavedReport(GatewayBase):
    """Stable, owner-scoped Data Chat report identity."""

    __tablename__ = "gateway_saved_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    original_conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_gw_saved_reports_owner", "org_id", "owner_user_id", "updated_at"),
        Index("ix_gw_saved_reports_conversation", "org_id", "owner_user_id", "original_conversation_id"),
        Index("ix_gw_saved_reports_project", "org_id", "owner_user_id", "project_id"),
    )


class GatewaySavedReportVersion(GatewayBase):
    """Immutable content publication for one Data Chat report."""

    __tablename__ = "gateway_saved_report_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_artifact_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    freshness_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unknown", server_default="unknown"
    )
    freshness_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    freshness_checked_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    dbt_commit_sha: Mapped[str | None] = mapped_column(String(40))
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64))
    retention_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    published_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source_artifact_id", name="uq_gw_saved_report_version_artifact"),
        UniqueConstraint(
            "org_id",
            "owner_user_id",
            "kind",
            "content_hash",
            name="uq_gw_saved_report_version_owner_content",
        ),
        UniqueConstraint("report_id", "ordinal", name="uq_gw_saved_report_version_ordinal"),
        Index("ix_gw_saved_report_versions_report", "report_id", "ordinal"),
        Index("ix_gw_saved_report_versions_owner", "org_id", "owner_user_id", "published_at"),
    )


class GatewayReportRefresh(GatewayBase):
    """Server-owned refresh lineage from a fixed version into one chat run."""

    __tablename__ = "gateway_report_refreshes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id: Mapped[str] = mapped_column(String, nullable=False)
    base_version_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False)
    original_conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    drift_state: Mapped[str] = mapped_column(String(20), nullable=False)
    drift_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    run_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    candidate_artifact_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (
        UniqueConstraint("run_id", name="uq_gw_report_refresh_run"),
        Index("ix_gw_report_refresh_owner", "org_id", "owner_user_id", "report_id", "created_at"),
        Index("ix_gw_report_refresh_status", "status", "updated_at"),
    )


class GatewayReportShareGrant(GatewayBase):
    """Revocable same-organization link pinned to one immutable version."""

    __tablename__ = "gateway_report_share_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    version_id: Mapped[str] = mapped_column(String, nullable=False)
    report_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (
        Index(
            "uq_gw_report_share_active_version",
            "version_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
            sqlite_where=text("state = 'active'"),
        ),
        Index("ix_gw_report_share_lookup", "org_id", "token_hash", "state"),
        Index("ix_gw_report_share_owner", "org_id", "owner_user_id", "report_id", "state"),
    )


class GatewayReportShareAccess(GatewayBase):
    """A recipient's remembered discovery of one active fixed-version grant."""

    __tablename__ = "gateway_report_share_access"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    grant_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    recipient_user_id: Mapped[str] = mapped_column(String, nullable=False)
    first_opened_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    last_opened_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("grant_id", "recipient_user_id", name="uq_gw_report_share_access_recipient"),
        Index("ix_gw_report_share_access_recipient", "org_id", "recipient_user_id", "last_opened_at"),
    )


class GatewayChatStarterCache(GatewayBase):
    """Four starter prompts cached by project metadata checksum."""

    __tablename__ = "gateway_chat_starter_cache"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    metadata_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    questions_json: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "project_id",
            "metadata_checksum",
            name="uq_gw_chat_starters_checksum",
        ),
        Index("ix_gw_chat_starters_project", "org_id", "project_id"),
    )


class GatewayChatUserPreference(GatewayBase):
    """Per-user default selection for the standalone chat surface."""

    __tablename__ = "gateway_chat_user_preferences"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    default_chat_project_id: Mapped[str | None] = mapped_column(String)
    default_per_query_budget_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.25, server_default="0.25"
    )
    default_chat_budget_usd: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1.0")
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_gw_chat_user_preference"),)

