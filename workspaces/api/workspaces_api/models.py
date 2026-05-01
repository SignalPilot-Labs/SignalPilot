"""SQLAlchemy 2.0 ORM models for the Workspaces API.

Schema: workspaces (set on Base.metadata in db.py).
All ForeignKey strings reference "workspaces.run.id" — the schema_translate_map
on the SQLite test engine rewrites these to unqualified at statement-prepare time.

Column types are deliberately portable (JSON not JSONB, Integer not BIGSERIAL)
so SQLite-backed unit tests work. The Alembic migration uses Postgres-native types.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from workspaces_api.db import Base

_JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Run(Base):
    __tablename__ = "run"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    inference_mode: Mapped[str] = mapped_column(String(50), nullable=False)
    dbt_proxy_host_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    events: Mapped[list[RunEvent]] = relationship(
        "RunEvent", back_populates="run", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[Approval]] = relationship(
        "Approval", back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("run_workspace_idx", "workspace_id", "created_at"),
        Index("run_state_idx", "state"),
    )


class RunEvent(Base):
    __tablename__ = "run_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.run.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(_JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[Run] = relationship("Run", back_populates="events")

    __table_args__ = (Index("run_event_run_idx", "run_id", "id"),)


class Approval(Base):
    __tablename__ = "approval"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.run.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_input: Mapped[dict] = mapped_column(_JSON_TYPE, nullable=False, default=dict)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[Run] = relationship("Run", back_populates="approvals")

    __table_args__ = (Index("approval_run_idx", "run_id"),)
