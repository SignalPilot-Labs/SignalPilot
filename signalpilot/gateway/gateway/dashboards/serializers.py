"""Wire shapes for the dashboards API.

These match ``signalpilot/web/lib/api/dashboards.ts`` field for field. A test
parses the TypeScript types and asserts the key sets are identical; change
both sides together.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from gateway.db.models import (
    GatewayDashboardRefresh,
    GatewayPublishedDashboard,
    GatewayPublishedDashboardVersion,
)

from .schedule import ALLOWED_INTERVALS, DEFAULT_TIMEZONE, valid_anchor, valid_timezone
from .store import SLUG_RE, can_edit

Visibility = Literal["private", "org"]
RefreshMode = Literal["sql", "agent"]


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


# ── Requests ────────────────────────────────────────────────────────────────


class RefreshSettingsIn(BaseModel):
    interval_minutes: int | None = None
    anchor_time: str | None = None
    timezone: str = DEFAULT_TIMEZONE
    mode: RefreshMode = "sql"

    @field_validator("interval_minutes")
    @classmethod
    def _interval(cls, value: int | None) -> int | None:
        if value is not None and value not in ALLOWED_INTERVALS:
            raise ValueError(f"interval_minutes must be one of {list(ALLOWED_INTERVALS)} or null")
        return value

    @field_validator("anchor_time")
    @classmethod
    def _anchor(cls, value: str | None) -> str | None:
        if value is not None and not valid_anchor(value):
            raise ValueError("anchor_time must be HH:MM (24h)")
        return value.strip() if value else None

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        if not valid_timezone(value):
            raise ValueError("timezone must be an IANA zone name")
        return value.strip()


class PublishDashboardRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    visibility: Visibility
    refresh: RefreshSettingsIn
    notify_on_failure: bool = True
    target_dashboard_id: str | None = None

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        if not SLUG_RE.match(value.strip()):
            raise ValueError("slug must match ^[a-z0-9][a-z0-9-]{0,63}$")
        return value.strip()


class UpdateDashboardRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    visibility: Visibility | None = None
    refresh: RefreshSettingsIn | None = None
    notify_on_failure: bool | None = None


# ── Responses ───────────────────────────────────────────────────────────────


class RefreshSettingsOut(BaseModel):
    interval_minutes: int | None
    anchor_time: str | None
    timezone: str
    mode: RefreshMode


class PublishedDashboardOut(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None
    visibility: Visibility
    project_id: str | None
    created_by_user_id: str
    created_by_label: str
    source_conversation_id: str | None
    source_file_id: str | None
    current_version_id: str | None
    current_version_no: int | None
    chart_count: int
    refresh: RefreshSettingsOut
    notify_on_failure: bool
    next_refresh_at: str | None
    last_refresh_at: str | None
    last_refresh_status: Literal["succeeded", "failed", "skipped"] | None
    created_at: str
    updated_at: str
    archived_at: str | None
    can_edit: bool


class DashboardDatasetMetaOut(BaseModel):
    row_count: int
    byte_size: int
    filename: str


class DashboardVersionOut(BaseModel):
    id: str
    version_no: int
    produced_by: Literal["publish", "refresh", "restore"]
    producer_ref: str | None
    chart_count: int
    dataset_meta: dict[str, DashboardDatasetMetaOut]
    created_at: str


class DashboardRefreshOut(BaseModel):
    id: str
    mode: RefreshMode
    trigger: Literal["schedule", "manual"]
    status: Literal["queued", "running", "finalizing", "succeeded", "failed", "skipped"]
    scheduled_for: str | None
    started_at: str | None
    finished_at: str | None
    version_id: str | None
    run_id: str | None
    conversation_id: str | None
    error: str | None
    detail: dict[str, Any] | None
    created_at: str


def dashboard_out(
    row: GatewayPublishedDashboard,
    *,
    viewer_user_id: str,
    is_admin: bool,
    current_version_no: int | None,
) -> PublishedDashboardOut:
    editable = can_edit(row, viewer_user_id, is_admin=is_admin)
    return PublishedDashboardOut(
        id=row.id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        visibility=row.visibility,  # type: ignore[arg-type]
        project_id=row.project_id,
        created_by_user_id=row.created_by_user_id,
        # No user directory in the gateway (identity lives in Clerk), so the
        # id is the label. The web client can resolve it when it has a roster.
        created_by_label=row.created_by_user_id,
        source_conversation_id=row.source_conversation_id,
        source_file_id=row.source_file_id,
        current_version_id=row.current_version_id,
        current_version_no=current_version_no,
        chart_count=int(row.chart_count or 0),
        refresh=RefreshSettingsOut(
            interval_minutes=row.refresh_interval_minutes,
            anchor_time=row.refresh_anchor_time,
            timezone=row.refresh_timezone or DEFAULT_TIMEZONE,
            mode=row.refresh_mode,  # type: ignore[arg-type]
        ),
        notify_on_failure=bool(row.notify_on_failure),
        next_refresh_at=iso(row.next_refresh_at),
        last_refresh_at=iso(row.last_refresh_at),
        last_refresh_status=row.last_refresh_status,  # type: ignore[arg-type]
        created_at=iso(row.created_at) or "",
        updated_at=iso(row.updated_at) or "",
        archived_at=iso(row.archived_at),
        can_edit=editable,
    )


def version_out(row: GatewayPublishedDashboardVersion) -> DashboardVersionOut:
    meta = {
        str(name): DashboardDatasetMetaOut(
            row_count=int(value.get("row_count") or 0),
            byte_size=int(value.get("byte_size") or 0),
            filename=str(value.get("filename") or name),
        )
        for name, value in (row.dataset_meta or {}).items()
        if isinstance(value, dict)
    }
    return DashboardVersionOut(
        id=row.id,
        version_no=int(row.version_no),
        produced_by=row.produced_by,  # type: ignore[arg-type]
        producer_ref=row.producer_ref,
        chart_count=int(row.chart_count or 0),
        dataset_meta=meta,
        created_at=iso(row.created_at) or "",
    )


def refresh_out(row: GatewayDashboardRefresh) -> DashboardRefreshOut:
    return DashboardRefreshOut(
        id=row.id,
        mode=row.mode,  # type: ignore[arg-type]
        trigger=row.trigger,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        scheduled_for=iso(row.scheduled_for),
        started_at=iso(row.started_at),
        finished_at=iso(row.finished_at),
        version_id=row.version_id,
        run_id=row.run_id,
        conversation_id=row.conversation_id,
        error=row.error,
        detail=row.detail if isinstance(row.detail, dict) else None,
        created_at=iso(row.created_at) or "",
    )
