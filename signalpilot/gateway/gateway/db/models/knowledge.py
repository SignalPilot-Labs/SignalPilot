"""Define API key, knowledge base, schema watch, and report models."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import GatewayBase


class GatewayApiKey(GatewayBase):
    __tablename__ = "gateway_api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    key_hash: Mapped[str] = mapped_column(String, nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str | None] = mapped_column(String)
    last_used_at: Mapped[str | None] = mapped_column(String)
    expires_at: Mapped[str | None] = mapped_column(String, nullable=True)
    # The evaluation binding limits this key to one run and one task.
    # The credential stores the warehouse pin and the proposed document overlay.
    # Request headers cannot define this boundary because the agent controls them.
    eval_run_id: Mapped[str | None] = mapped_column(String(64))
    eval_task_id: Mapped[str | None] = mapped_column(String(200))
    eval_connection: Mapped[str | None] = mapped_column(String(64))
    eval_doc_ids: Mapped[list | None] = mapped_column(JSON)

    __table_args__ = (
        Index("ix_gw_api_keys_org", "org_id"),
        Index("ix_gw_api_keys_hash", "key_hash"),
    )


class GatewayKnowledgeDoc(GatewayBase):
    """Knowledge Base documents: org/project/connection-scoped markdown docs."""

    __tablename__ = "gateway_knowledge_docs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    proposed_by_agent: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("idx_knowledge_org_scope", "org_id", "scope", "scope_ref"),
        Index("idx_knowledge_org_status", "org_id", "status"),
        Index("idx_knowledge_org_cat", "org_id", "category"),
    )


class GatewayKnowledgeRetrieval(GatewayBase):
    """Per-retrieval event log: which docs agents actually pull, and how.

    Written fire-and-forget from the hot paths (get_knowledge /
    search_knowledge / REST search). Feeds the retrieval heat-map UI and the
    KB Reflector's usage signal. Pruned after ~90 days by the sync loop.
    """

    __tablename__ = "gateway_knowledge_retrievals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    doc_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    query: Mapped[str | None] = mapped_column(String(300), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ts: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("idx_knowledge_retr_org_doc_ts", "org_id", "doc_id", "ts"),
        Index("idx_knowledge_retr_org_ts", "org_id", "ts"),
    )


class GatewaySchemaWatch(GatewayBase):
    """Scheduled schema-diff watch: introspect a connection on an interval and
    open a GitHub PR documenting any structural drift.

    The last snapshot is stored inline (schema JSON + fingerprint) so diffs
    survive gateway restarts: unlike the in-memory schema_cache history.
    """

    __tablename__ = "gateway_schema_watches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    connection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_s: Mapped[int] = mapped_column(Integer, nullable=False, default=86400)
    github_repo: Mapped[str] = mapped_column(String(200), nullable=False)  # owner/name
    github_base_branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_run_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_change_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_pr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "connection_name", "github_repo", name="uq_gw_schema_watch"),
        Index("idx_schema_watch_org", "org_id"),
    )


class GatewayReport(GatewayBase):
    """Rendered HTML reports: org-scoped, optionally grouped by project (scope_ref)."""

    __tablename__ = "gateway_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    scope_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="report", server_default="report")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    data_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    proposed_by_agent: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("idx_reports_org_created", "org_id", "created_at"),
        Index("idx_reports_org_scope", "org_id", "scope_ref"),
        Index("idx_reports_org_kind", "org_id", "kind", "created_at"),
    )


class GatewayKnowledgeEdit(GatewayBase):
    """Edit history for Knowledge Base documents."""

    __tablename__ = "gateway_knowledge_edits"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    doc_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    body_before: Mapped[str] = mapped_column(Text, nullable=False)
    bytes_before: Mapped[int] = mapped_column(Integer, nullable=False)
    edited_at: Mapped[float] = mapped_column(Float, nullable=False)
    edited_by: Mapped[str | None] = mapped_column(String, nullable=True)
    edit_kind: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        Index("idx_knowledge_edits_doc", "doc_id", "edited_at"),
        Index("idx_knowledge_edits_org", "org_id"),
    )
