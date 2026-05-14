"""SQLAlchemy 2.0 ORM models for the dashboards schema.

Schema: workspaces (inherited from Base.metadata in db.py).
ForeignKey strings use "workspaces.chart.id" style — the schema_translate_map
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


class Chart(Base):
    __tablename__ = "chart"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    chart_type: Mapped[str] = mapped_column(String(50), nullable=False)
    echarts_option: Mapped[dict] = mapped_column(_JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    query: Mapped["ChartQuery | None"] = relationship(
        "ChartQuery", back_populates="chart", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (Index("chart_workspace_idx", "workspace_id", "created_at"),)


class ChartQuery(Base):
    __tablename__ = "chart_query"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chart_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.chart.id", ondelete="CASCADE"), nullable=False
    )
    connector_name: Mapped[str] = mapped_column(Text, nullable=False)
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict] = mapped_column(_JSON_TYPE, nullable=False, default=dict)
    refresh_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    chart: Mapped["Chart"] = relationship("Chart", back_populates="query")
    cache_entries: Mapped[list["ChartCache"]] = relationship(
        "ChartCache", back_populates="query_obj", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("chart_query_chart_idx", "chart_id", unique=True),)


class ChartCache(Base):
    __tablename__ = "chart_cache"

    cache_key: Mapped[str] = mapped_column(Text, primary_key=True)
    query_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.chart_query.id", ondelete="CASCADE"), nullable=False
    )
    result_json: Mapped[dict] = mapped_column(_JSON_TYPE, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    query_obj: Mapped["ChartQuery"] = relationship("ChartQuery", back_populates="cache_entries")

    __table_args__ = (Index("chart_cache_expires_idx", "expires_at"),)
