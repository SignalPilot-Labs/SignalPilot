"""HTTP-level dashboard role and non-disclosure matrix."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api.dashboards import router
from gateway.api.deps import get_store
from gateway.dashboard import store as dashboard_store
from gateway.dashboard.cache import dashboard_query_cache_key
from gateway.dashboard.domain import DashboardDefinition
from gateway.db.models import (
    GatewayAuditLog,
    GatewayBase,
    GatewayDashboardResult,
    GatewayStructuredQueryResult,
)
from gateway.security.scope_guard import _resolve_user_id
from gateway.store.store import Store

FIXTURE = Path(__file__).parents[2] / "web/dashboard/lightdash-contract/fixtures/five-components.json"
IDENTITY = {"org_id": "org-a", "user_id": "owner-a"}


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


@pytest_asyncio.fixture
async def http_matrix():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        created = await dashboard_store.create_private_dashboard(
            session,
            org_id="org-a",
            user_id="owner-a",
            definition=_definition(),
        )
        definition = created.version.definition
        chart = next(item for item in definition.charts if item.id == "chart-kpi")
        tile = next(item for item in definition.tiles if item.chartId == chart.id)
        structured = GatewayStructuredQueryResult(
            id="structured-http",
            execution_id="execution-http",
            org_id="org-a",
            owner_user_id=None,
            columns_json=[
                {
                    "name": "orders.revenue",
                    "logical_type": "number",
                    "nullable": False,
                }
            ],
            rows_json=[{"orders.revenue": 1250}],
            preview_rows_json=[{"orders.revenue": 1250}],
            source_result_ids_json=[],
            result_origin="dashboard",
            query_row_count=1,
            saved_row_count=1,
            source_completeness="complete",
            result_completeness="complete",
            display_completeness="complete",
            provenance_json={},
        )
        result = GatewayDashboardResult(
            id="dashboard-result-http",
            dashboard_id=created.dashboard.id,
            version_id=created.version.id,
            chart_id=chart.id,
            org_id="org-a",
            execution_id="execution-http",
            structured_result_id=structured.id,
            cache_key=dashboard_query_cache_key(
                version_id=created.version.id,
                chart=chart,
                tile_uuid=tile.uuid,
                requested_filters=[],
                drill_path=[],
                dashboard_filters=definition.filters,
            ),
            sql_hash="s" * 64,
            parameter_hash="p" * 64,
            tables_json=["dbo.orders"],
            semantic_definition_json={"metrics": [{"field_id": "orders.revenue"}]},
            completeness="complete",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        session.add_all([structured, result])
        await session.commit()

        app = FastAPI()
        app.include_router(router)

        async def fake_user_id() -> str:
            return IDENTITY["user_id"]

        async def fake_store() -> Store:
            return Store(
                session,
                org_id=IDENTITY["org_id"],
                user_id=IDENTITY["user_id"],
            )

        app.dependency_overrides[_resolve_user_id] = fake_user_id
        app.dependency_overrides[get_store] = fake_store
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, session, created
    await engine.dispose()


def _as(org_id: str, user_id: str) -> None:
    IDENTITY.update(org_id=org_id, user_id=user_id)


@pytest.mark.asyncio
async def test_http_role_matrix_and_denials_disclose_no_dashboard_data(http_matrix) -> None:
    client, session, created = http_matrix
    dashboard_id = created.dashboard.id
    version_id = created.version.id

    _as("org-a", "owner-a")
    assert (await client.get(f"/api/dashboards/{dashboard_id}")).status_code == 200

    _as("org-a", "viewer-a")
    private = await client.get(f"/api/dashboards/{dashboard_id}")
    assert private.status_code == 404

    _as("org-b", "outsider-b")
    outsider = await client.get(f"/api/dashboards/{dashboard_id}")
    assert outsider.status_code == 404
    assert "orders.revenue" not in outsider.text

    _as("org-a", "owner-a")
    shared = await client.post(
        f"/api/dashboards/{dashboard_id}/visibility",
        json={"visibility": "organization"},
    )
    assert shared.status_code == 200

    _as("org-a", "viewer-a")
    visible = await client.get(f"/api/dashboards/{dashboard_id}")
    assert visible.status_code == 200
    assert visible.json()["dashboard"]["is_owner"] is False
    owner_only = await client.post(
        f"/api/dashboards/{dashboard_id}/visibility",
        json={"visibility": "private"},
    )
    assert owner_only.status_code == 404
    assert (await client.post(f"/api/dashboards/{dashboard_id}/archive")).status_code == 404
    authoring = await client.post(
        "/api/dashboard-authoring/sessions",
        json={
            "prompt": "Change the dashboard",
            "dashboard_id": dashboard_id,
            "base_version_id": version_id,
        },
    )
    assert authoring.status_code == 404

    fork = await client.post(
        f"/api/dashboards/{dashboard_id}/fork",
        json={"version_id": version_id},
    )
    assert fork.status_code == 201
    forked = fork.json()
    assert forked["dashboard"]["visibility"] == "private"
    assert forked["dashboard"]["parent_dashboard_id"] == dashboard_id
    assert forked["dashboard"]["parent_version_id"] == version_id

    query = await client.post(
        f"/api/dashboards/{dashboard_id}/charts/chart-kpi/query",
        json={"version_id": version_id, "tile_uuid": "tile-kpi", "dashboard_filters": []},
    )
    assert query.status_code == 200
    assert query.json()["cache_state"] == "fresh"
    assert query.json()["rows"] == [{"orders.revenue": 1250}]
    assert query.json()["compiled_sql"] is None

    exact_data = await client.get(
        f"/api/dashboards/{dashboard_id}/charts/chart-kpi/data",
        params={"dashboard_result_id": "dashboard-result-http"},
    )
    assert exact_data.status_code == 200
    export = await client.post(
        f"/api/dashboards/{dashboard_id}/exports/html",
        json={
            "version_id": version_id,
            "dashboard_result_ids": ["dashboard-result-http"],
            "acknowledge_sensitive_data": True,
        },
    )
    assert export.status_code == 200
    assert export.json()["authorized_result_ids"] == ["dashboard-result-http"]

    _as("org-b", "outsider-b")
    denied_urls = [
        await client.post(
            f"/api/dashboards/{dashboard_id}/charts/chart-kpi/query",
            json={"version_id": version_id, "tile_uuid": "tile-kpi"},
        ),
        await client.get(
            f"/api/dashboards/{dashboard_id}/charts/chart-kpi/data",
            params={"dashboard_result_id": "dashboard-result-http"},
        ),
        await client.post(
            f"/api/dashboards/{dashboard_id}/exports/html",
            json={
                "version_id": version_id,
                "dashboard_result_ids": ["dashboard-result-http"],
                "acknowledge_sensitive_data": True,
            },
        ),
        await client.post(
            f"/api/dashboards/{dashboard_id}/charts/chart-kpi/analyze",
            json={
                "version_id": version_id,
                "tile_uuid": "tile-kpi",
                "dashboard_result_id": "dashboard-result-http",
                "message": "Analyze this change",
            },
        ),
    ]
    assert {response.status_code for response in denied_urls} == {404}
    denied_text = " ".join(response.text for response in denied_urls)
    for secret in ["orders.revenue", "1250", "dashboard-result-http", "dbo.orders"]:
        assert secret not in denied_text

    _as("org-a", "owner-a")
    archived = await client.post(f"/api/dashboards/{dashboard_id}/archive")
    assert archived.status_code == 200
    restored = await client.post(f"/api/dashboards/{dashboard_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["dashboard"]["archived_at"] is None

    lifecycle_events = set(
        (
            await session.execute(
                select(GatewayAuditLog.event_type).where(GatewayAuditLog.org_id == "org-a")
            )
        ).scalars()
    )
    assert {
        "dashboard_opened",
        "dashboard_shared",
        "dashboard_forked",
        "dashboard_cache_hit",
        "dashboard_query_completed",
        "dashboard_exported",
        "dashboard_archived",
        "dashboard_restored",
    } <= lifecycle_events

    await session.rollback()
