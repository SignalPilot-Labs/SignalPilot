"""Closed, metadata-only telemetry for the dashboard release contract."""

from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayAuditLog
from gateway.models.audit import AuditEntry
from gateway.store.audit_log import append_audit

SafeId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")]
VisualizationType = Literal["kpi", "table", "bar", "line", "area"]
Completeness = Literal["complete", "truncated", "unknown"]
CacheState = Literal[
    "fresh",
    "cache_hit",
    "cache_miss",
    "stale_refreshing",
    "cached_source_unavailable",
    "cached_after_refresh_failure",
    "no_usable_cache",
]
FailureCode = Literal[
    "data_source_unavailable",
    "authentication_rejected",
    "query_timeout",
    "query_invalid",
    "semantic_definition_invalid",
    "permission_denied",
    "rate_limited",
    "cancelled",
    "result_contract_mismatch",
    "stale_dashboard_version",
    "internal_error",
]


class DashboardTelemetryEvent(StrEnum):
    OPENED = "dashboard_opened"
    RENDERED = "dashboard_rendered"
    QUERY_COMPLETED = "dashboard_query_completed"
    CACHE_HIT = "dashboard_cache_hit"
    CACHE_MISS = "dashboard_cache_miss"
    AGENT_VALIDATION_FAILED = "dashboard_agent_validation_failed"
    QUERY_FAILURE = "dashboard_query_failure"
    DEGRADED_FALLBACK = "dashboard_degraded_fallback"
    RETRY_OUTCOME = "dashboard_retry_outcome"
    TILE_RENDER_FAILED = "dashboard_tile_render_failed"
    SAVED = "dashboard_saved"
    SHARED = "dashboard_shared"
    FORKED = "dashboard_forked"
    ARCHIVED = "dashboard_archived"
    RESTORED = "dashboard_restored"
    EXPORTED = "dashboard_exported"
    ANALYSIS_STARTED = "dashboard_analysis_started"


class _Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dashboard_id: SafeId
    version_id: SafeId
    dedupe_key: SafeId | None = None


class OpenedMetadata(_Metadata):
    pass


class RenderedMetadata(_Metadata):
    open_instance_id: SafeId
    duration_ms: float = Field(ge=0, le=3_600_000)
    chart_count: int = Field(ge=1, le=100)


class QueryMetadata(_Metadata):
    chart_id: SafeId
    visualization_type: VisualizationType
    duration_ms: float = Field(ge=0, le=3_600_000)
    row_count: int = Field(ge=0, le=1_000_000)
    completeness: Completeness
    cache_state: CacheState
    execution_id: SafeId | None = None
    correlation_id: SafeId | None = None


class CacheMetadata(_Metadata):
    chart_id: SafeId
    visualization_type: VisualizationType
    cache_state: CacheState


class ValidationMetadata(_Metadata):
    failure_code: Literal[
        "dashboard_time_series_window_required",
        "dashboard_semantic_validation_failed",
        "dashboard_apply_receipt_invalid",
        "dashboard_agent_draft_invalid",
    ]
    chart_id: SafeId | None = None


class FailureMetadata(_Metadata):
    chart_id: SafeId | None = None
    failure_code: FailureCode
    incident_scope: Literal["chart", "connection", "dashboard"]
    retryable: bool
    correlation_id: SafeId
    cache_state: CacheState


class FallbackMetadata(_Metadata):
    chart_id: SafeId
    failure_code: FailureCode
    cache_state: Literal["cached_source_unavailable", "cached_after_refresh_failure"]
    cached_age_seconds: int | None = Field(default=None, ge=0)
    correlation_id: SafeId


class RetryMetadata(_Metadata):
    outcome: Literal["failed", "recovered", "deduplicated"]
    failure_code: FailureCode | None = None
    correlation_id: SafeId


class TileFailureMetadata(_Metadata):
    open_instance_id: SafeId
    chart_id: SafeId
    visualization_type: VisualizationType
    failure_code: Literal["render_error"]
    failure_fingerprint: SafeId


class SavedMetadata(_Metadata):
    chart_count: int = Field(ge=1, le=100)
    authoring_session_id: SafeId | None = None


class SharedMetadata(_Metadata):
    visibility: Literal["private", "organization"]


class ForkedMetadata(_Metadata):
    fork_dashboard_id: SafeId
    fork_version_id: SafeId


class ExportedMetadata(_Metadata):
    format: Literal["html"]
    result_count: int = Field(ge=1, le=100)


class AnalysisMetadata(_Metadata):
    chart_id: SafeId
    conversation_id: SafeId


_METADATA_MODELS: dict[DashboardTelemetryEvent, type[_Metadata]] = {
    DashboardTelemetryEvent.OPENED: OpenedMetadata,
    DashboardTelemetryEvent.RENDERED: RenderedMetadata,
    DashboardTelemetryEvent.QUERY_COMPLETED: QueryMetadata,
    DashboardTelemetryEvent.CACHE_HIT: CacheMetadata,
    DashboardTelemetryEvent.CACHE_MISS: CacheMetadata,
    DashboardTelemetryEvent.AGENT_VALIDATION_FAILED: ValidationMetadata,
    DashboardTelemetryEvent.QUERY_FAILURE: FailureMetadata,
    DashboardTelemetryEvent.DEGRADED_FALLBACK: FallbackMetadata,
    DashboardTelemetryEvent.RETRY_OUTCOME: RetryMetadata,
    DashboardTelemetryEvent.TILE_RENDER_FAILED: TileFailureMetadata,
    DashboardTelemetryEvent.SAVED: SavedMetadata,
    DashboardTelemetryEvent.SHARED: SharedMetadata,
    DashboardTelemetryEvent.FORKED: ForkedMetadata,
    DashboardTelemetryEvent.ARCHIVED: _Metadata,
    DashboardTelemetryEvent.RESTORED: _Metadata,
    DashboardTelemetryEvent.EXPORTED: ExportedMetadata,
    DashboardTelemetryEvent.ANALYSIS_STARTED: AnalysisMetadata,
}


def validate_dashboard_telemetry(
    event_type: DashboardTelemetryEvent | str,
    metadata: dict,
) -> tuple[DashboardTelemetryEvent, dict]:
    event = DashboardTelemetryEvent(event_type)
    validated = _METADATA_MODELS[event].model_validate(metadata)
    return event, validated.model_dump(mode="json", exclude_none=True)


async def record_dashboard_event(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str | None,
    event_type: DashboardTelemetryEvent | str,
    metadata: dict,
    connection_name: str | None = None,
) -> bool:
    """Record one validated event. Persistence failure never changes the operation."""

    try:
        event, payload = validate_dashboard_telemetry(event_type, metadata)
        dedupe_key = payload.get("dedupe_key")
        if dedupe_key:
            recent = (
                await db.execute(
                    select(GatewayAuditLog.metadata_json)
                    .where(
                        GatewayAuditLog.org_id == org_id,
                        GatewayAuditLog.event_type == event.value,
                    )
                    .order_by(GatewayAuditLog.timestamp.desc())
                    .limit(100)
                )
            ).scalars()
            if any((item or {}).get("dedupe_key") == dedupe_key for item in recent):
                return False
        await append_audit(
            db,
            org_id=org_id,
            user_id=user_id,
            entry=AuditEntry(
                id=str(uuid.uuid4()),
                timestamp=time.time(),
                event_type=event.value,
                connection_name=connection_name,
                rows_returned=payload.get("row_count"),
                duration_ms=payload.get("duration_ms"),
                metadata=payload,
            ),
        )
        return True
    except Exception:
        return False
