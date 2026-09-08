"""Published dashboards: the org-scoped team gallery with versions and refreshes.

A chat writes ``artifacts/<name>.dashboard.json``. Publishing copies the spec
and its dataset files into dashboard-owned object keys and creates a
published dashboard with version 1. Every refresh or restore adds an
immutable version; ``current_version_id`` names the live one. A refresh that
fails validation never replaces the live version.

Schema changes go through Alembic (0028 introduced these tables). Keep the
column definitions here byte-identical to the migration; the parity test
diffs the two.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import GatewayBase, TZDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


def new_dashboard_id() -> str:
    return f"dash_{uuid.uuid4().hex}"


def new_version_id() -> str:
    return f"dver_{uuid.uuid4().hex}"


def new_refresh_id() -> str:
    return f"dref_{uuid.uuid4().hex}"


class GatewayPublishedDashboard(GatewayBase):
    """One dashboard in the team gallery. Independent of its source chat."""

    __tablename__ = "gateway_published_dashboards"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_dashboard_id)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String)
    # ^[a-z0-9][a-z0-9-]{0,63}$, unique per org.
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # private | org | link
    visibility: Mapped[str] = mapped_column(String(10), nullable=False, default="private", server_default="private")
    # Set when visibility == link. 32 url-safe characters, never hashed: the
    # token is the link and the owner can read it back.
    share_token: Mapped[str | None] = mapped_column(String(64))
    created_by_user_id: Mapped[str] = mapped_column(String, nullable=False)
    source_conversation_id: Mapped[str | None] = mapped_column(String)
    source_file_id: Mapped[str | None] = mapped_column(String)
    current_version_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey(
            "gateway_published_dashboard_versions.id",
            name="fk_gw_pubdash_current_version",
            ondelete="SET NULL",
            use_alter=True,
        ),
    )
    # null = off. Allowed: 15, 60, 120, 240, 480, 720, 1440.
    refresh_interval_minutes: Mapped[int | None] = mapped_column(Integer)
    # "HH:MM" 24h wall-clock in refresh_timezone.
    refresh_anchor_time: Mapped[str | None] = mapped_column(String(5))
    refresh_timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC", server_default="UTC")
    # sql | agent
    refresh_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="sql", server_default="sql")
    notify_on_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    next_refresh_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_refresh_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    # succeeded | failed | skipped
    last_refresh_status: Mapped[str | None] = mapped_column(String(10))
    chart_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, default=_utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, default=_utcnow, server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_gw_pubdash_org_slug"),
        UniqueConstraint("share_token", name="uq_gw_pubdash_share_token"),
        Index("ix_gw_pubdash_org", "org_id"),
        Index("ix_gw_pubdash_due", "next_refresh_at"),
    )


class GatewayPublishedDashboardVersion(GatewayBase):
    """An immutable snapshot: one spec object plus one object per file dataset."""

    __tablename__ = "gateway_published_dashboard_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_version_id)
    dashboard_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("gateway_published_dashboards.id", name="fk_gw_pubdash_version_dashboard", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    spec_key: Mapped[str] = mapped_column(Text, nullable=False)
    # {dataset name: object key}. Inline-row datasets are absent: they stay in the spec.
    dataset_keys: Mapped[dict] = mapped_column(JSON, nullable=False)
    # {dataset name: {row_count, byte_size, filename}}
    dataset_meta: Mapped[dict] = mapped_column(JSON, nullable=False)
    chart_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # publish | refresh | restore
    produced_by: Mapped[str] = mapped_column(String(10), nullable=False)
    # User id (publish, restore) or refresh id (refresh).
    producer_ref: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, default=_utcnow, server_default=func.now())

    __table_args__ = (UniqueConstraint("dashboard_id", "version_no", name="uq_gw_pubdash_version_no"),)


class GatewayDashboardRefresh(GatewayBase):
    """One refresh attempt, scheduled or manual, in sql or agent mode."""

    __tablename__ = "gateway_dashboard_refreshes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_refresh_id)
    dashboard_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("gateway_published_dashboards.id", name="fk_gw_pubdash_refresh_dashboard", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    # sql | agent
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    # schedule | manual
    trigger: Mapped[str] = mapped_column(String(10), nullable=False)
    # queued | running | succeeded | failed | skipped
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="queued", server_default="queued")
    scheduled_for: Mapped[datetime | None] = mapped_column(TZDateTime)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    version_id: Mapped[str | None] = mapped_column(String)
    # Chat run and conversation for agent mode.
    run_id: Mapped[str | None] = mapped_column(String)
    conversation_id: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text)
    # Per-dataset outcome and the notification record.
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, default=_utcnow, server_default=func.now())

    __table_args__ = (
        Index("ix_gw_pubdash_refresh_dashboard", "dashboard_id", "created_at"),
        Index("ix_gw_pubdash_refresh_org", "org_id"),
        Index("ix_gw_pubdash_refresh_status", "mode", "status"),
    )
