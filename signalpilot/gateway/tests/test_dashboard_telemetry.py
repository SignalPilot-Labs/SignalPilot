"""Phase 7 closed dashboard telemetry and browser authorization contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api.dashboards import record_dashboard_client_telemetry
from gateway.dashboard import store as dashboard_store
from gateway.dashboard.domain import DashboardDefinition
from gateway.dashboard.telemetry import (
    DashboardTelemetryEvent,
    record_dashboard_event,
    validate_dashboard_telemetry,
)
from gateway.db.models import GatewayAuditLog, GatewayBase
from gateway.models.dashboards import DashboardClientTelemetryRequest

FIXTURE = Path(__file__).parents[2] / "web/dashboard/lightdash-contract/fixtures/five-components.json"


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


def _definition() -> DashboardDefinition:
    fixture = json.loads(FIXTURE.read_text())
    return DashboardDefinition.model_validate(
        {
            "schemaVersion": 1,
            "name": fixture["dashboard"]["name"],
            "description": fixture["dashboard"]["description"],
            "filters": fixture["dashboard"]["filters"],
            "tiles": fixture["dashboard"]["tiles"],
            "charts": fixture["charts"],
            "signalPilot": fixture["signalPilot"],
        }
    )


def _metadata(event: DashboardTelemetryEvent) -> dict:
    base = {"dashboard_id": "dashboard-1", "version_id": "version-1"}
    variants = {
        DashboardTelemetryEvent.OPENED: {},
        DashboardTelemetryEvent.RENDERED: {
            "open_instance_id": "open-1",
            "duration_ms": 15,
            "chart_count": 5,
        },
        DashboardTelemetryEvent.QUERY_COMPLETED: {
            "chart_id": "chart-1",
            "visualization_type": "line",
            "duration_ms": 12,
            "row_count": 90,
            "completeness": "complete",
            "cache_state": "fresh",
            "execution_id": "execution-1",
        },
        DashboardTelemetryEvent.CACHE_HIT: {
            "chart_id": "chart-1",
            "visualization_type": "line",
            "cache_state": "fresh",
        },
        DashboardTelemetryEvent.CACHE_MISS: {
            "chart_id": "chart-1",
            "visualization_type": "line",
            "cache_state": "cache_miss",
        },
        DashboardTelemetryEvent.AGENT_VALIDATION_FAILED: {
            "failure_code": "dashboard_time_series_window_required",
            "chart_id": "chart-1",
        },
        DashboardTelemetryEvent.QUERY_FAILURE: {
            "chart_id": "chart-1",
            "failure_code": "query_timeout",
            "incident_scope": "connection",
            "retryable": True,
            "correlation_id": "correlation-1",
            "cache_state": "no_usable_cache",
        },
        DashboardTelemetryEvent.DEGRADED_FALLBACK: {
            "chart_id": "chart-1",
            "failure_code": "query_timeout",
            "cache_state": "cached_source_unavailable",
            "cached_age_seconds": 30,
            "correlation_id": "correlation-1",
        },
        DashboardTelemetryEvent.RETRY_OUTCOME: {
            "outcome": "recovered",
            "correlation_id": "correlation-1",
        },
        DashboardTelemetryEvent.TILE_RENDER_FAILED: {
            "open_instance_id": "open-1",
            "chart_id": "chart-1",
            "visualization_type": "line",
            "failure_code": "render_error",
            "failure_fingerprint": "render-deadbeef",
        },
        DashboardTelemetryEvent.SAVED: {"chart_count": 5},
        DashboardTelemetryEvent.SHARED: {"visibility": "organization"},
        DashboardTelemetryEvent.FORKED: {
            "fork_dashboard_id": "dashboard-2",
            "fork_version_id": "version-2",
        },
        DashboardTelemetryEvent.ARCHIVED: {},
        DashboardTelemetryEvent.RESTORED: {},
        DashboardTelemetryEvent.EXPORTED: {"format": "html", "result_count": 5},
        DashboardTelemetryEvent.ANALYSIS_STARTED: {
            "chart_id": "chart-1",
            "conversation_id": "conversation-1",
        },
    }
    return {**base, **variants[event]}


@pytest.mark.parametrize("event", list(DashboardTelemetryEvent))
def test_every_required_dashboard_event_has_a_closed_positive_contract(
    event: DashboardTelemetryEvent,
) -> None:
    validated_event, metadata = validate_dashboard_telemetry(event, _metadata(event))
    assert validated_event == event
    assert metadata["dashboard_id"] == "dashboard-1"


@pytest.mark.parametrize(
    "sensitive",
    [
        {"sql": "select secret from payroll"},
        {"parameters": ["customer@example.com"]},
        {"rows": [{"password": "secret"}]},
        {"prompt": "show credentials"},
        {"connection_string": "mssql://user:password@host/db"},
        {"raw_exception": "password=secret"},
    ],
)
def test_telemetry_schema_rejects_extra_sensitive_fields(sensitive: dict) -> None:
    with pytest.raises(ValidationError):
        validate_dashboard_telemetry(
            DashboardTelemetryEvent.OPENED,
            {**_metadata(DashboardTelemetryEvent.OPENED), **sensitive},
        )


@pytest.mark.asyncio
async def test_browser_telemetry_is_authorized_and_deduplicated(
    db_session: AsyncSession,
) -> None:
    created = await dashboard_store.create_private_dashboard(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        definition=_definition(),
    )
    body = DashboardClientTelemetryRequest(
        event_type="dashboard_rendered",
        version_id=created.version.id,
        open_instance_id="open-1",
        duration_ms=20,
    )
    owner = SimpleNamespace(
        session=db_session,
        user_id="owner-a",
        _require_org_id=lambda: "org-a",
    )
    await record_dashboard_client_telemetry(created.dashboard.id, body, owner)
    await record_dashboard_client_telemetry(created.dashboard.id, body, owner)
    events = (
        await db_session.execute(
            select(GatewayAuditLog).where(
                GatewayAuditLog.event_type == DashboardTelemetryEvent.RENDERED.value
            )
        )
    ).scalars().all()
    assert len(events) == 1

    outsider = SimpleNamespace(
        session=db_session,
        user_id="owner-a",
        _require_org_id=lambda: "org-b",
    )
    with pytest.raises(HTTPException) as denied:
        await record_dashboard_client_telemetry(created.dashboard.id, body, outsider)
    assert denied.value.status_code == 404
    assert len(events) == 1


@pytest.mark.asyncio
async def test_telemetry_failure_is_best_effort(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "gateway.dashboard.telemetry.append_audit",
        AsyncMock(side_effect=RuntimeError("audit store unavailable")),
    )
    recorded = await record_dashboard_event(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        event_type=DashboardTelemetryEvent.OPENED,
        metadata=_metadata(DashboardTelemetryEvent.OPENED),
    )
    assert recorded is False


@pytest.mark.asyncio
async def test_audit_store_distinguishes_query_cache_fallback_and_retry_outcomes(
    db_session: AsyncSession,
) -> None:
    events = [
        DashboardTelemetryEvent.QUERY_COMPLETED,
        DashboardTelemetryEvent.CACHE_HIT,
        DashboardTelemetryEvent.CACHE_MISS,
        DashboardTelemetryEvent.DEGRADED_FALLBACK,
        DashboardTelemetryEvent.RETRY_OUTCOME,
    ]
    for event in events:
        assert await record_dashboard_event(
            db_session,
            org_id="org-a",
            user_id="owner-a",
            event_type=event,
            metadata=_metadata(event),
        )
    stored = set(
        (
            await db_session.execute(
                select(GatewayAuditLog.event_type).where(GatewayAuditLog.org_id == "org-a")
            )
        ).scalars()
    )
    assert stored == {event.value for event in events}
