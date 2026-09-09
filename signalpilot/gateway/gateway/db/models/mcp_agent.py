"""Durable MCP agent threads, separate from mutable public agent-run CRUD."""

from sqlalchemy import JSON, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import GatewayBase


class MCPAgentThread(GatewayBase):
    __tablename__ = "gateway_mcp_agent_threads"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    runtime_env: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    lease_expires_at: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    enqueued_at: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retained_until: Mapped[float] = mapped_column(Float, nullable=False)
    client_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    request: Mapped[dict] = mapped_column(JSON, nullable=False)
    history: Mapped[list] = mapped_column(JSON, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    snapshot_key: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        Index("ix_mcp_agent_owner", "org_id", "user_id"),
        UniqueConstraint("org_id", "user_id", "client_request_id", name="uq_mcp_agent_request"),
    )


class MCPAgentEvent(GatewayBase):
    __tablename__ = "gateway_mcp_agent_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    __table_args__ = (Index("ix_mcp_agent_events_run", "org_id", "run_id", "sequence", unique=True),)
