"""Phase 1 contracts for durable, governed, private dashboards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.dashboard import store as dashboard_store
from gateway.dashboard.compiler import compile_metric_query
from gateway.dashboard.domain import DashboardDefinition, SemanticChartQuery
from gateway.dashboard.semantic_resolver import parse_approved_metrics, resolve_from_authorities
from gateway.db.models import GatewayBase
from gateway.dbt.types import ColumnSpec, ModelInfo, ModelStatus, ProjectMap

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


def _authorities():
    project_map = ProjectMap(project_name="pilot", project_dir="/immutable")
    project_map.models["orders"] = ModelInfo(
        name="orders",
        status=ModelStatus.COMPLETE,
        description="Governed orders mart",
        columns=[
            ColumnSpec(name="region", data_type="varchar", description="Sales region"),
            ColumnSpec(name="revenue", data_type="decimal", description="Net revenue", tests=["not_null"]),
        ],
    )
    schema = {
        "dbo.orders": {
            "name": "orders",
            "schema": "dbo",
            "columns": [
                {"name": "region", "type": "varchar", "nullable": False},
                {"name": "revenue", "type": "decimal", "nullable": False},
            ],
            "foreign_keys": [],
        }
    }
    metrics = parse_approved_metrics({"dashboard_metrics": [
        {
            "model": "orders",
            "column": "revenue",
            "aggregation": "sum",
            "label": "Revenue",
            "approved": True,
            "approval_source": "pilot-owner",
        },
        {
            "model": "orders",
            "column": "revenue",
            "aggregation": "average",
            "label": "Unapproved average",
            "approved": False,
        },
    ]})
    return resolve_from_authorities(
        project_id="project-a",
        commit_sha="a" * 40,
        connection_name="warehouse",
        project_map=project_map,
        physical_schema=schema,
        semantic_model={"tables": {"dbo.orders": {"description": "Orders", "columns": {}}}, "joins": [], "glossary": {}},
        approved_metrics=metrics,
    )


def _fixture_definition() -> DashboardDefinition:
    fixture = json.loads(FIXTURE.read_text())
    return DashboardDefinition.model_validate({
        "schemaVersion": 1,
        "name": fixture["dashboard"]["name"],
        "description": fixture["dashboard"]["description"],
        "filters": fixture["dashboard"]["filters"],
        "tiles": fixture["dashboard"]["tiles"],
        "charts": fixture["charts"],
        "signalPilot": fixture["signalPilot"],
    })


def test_resolver_projects_existing_authorities_and_only_explicit_metrics() -> None:
    context = _authorities()
    assert context.connection_type == "mssql"
    assert len(context.semantic_fingerprint) == 64
    assert context.explores[0].relation == "dbo.orders"
    assert [metric.label for metric in context.explores[0].metrics] == ["Revenue"]
    assert context.explores[0].metrics[0].human_verified is True
    assert context.verification_refs == ["schema:orders:verified"]


def test_compiler_binds_values_and_emits_supported_mssql_aggregation() -> None:
    context = _authorities()
    query = SemanticChartQuery.model_validate({
        "kind": "semantic",
        "exploreName": "orders",
        "dimensions": ["orders.region"],
        "metrics": ["orders.revenue"],
        "filters": {"dimensions": {"id": "root", "and": [{
            "id": "region-filter",
            "operator": "equals",
            "values": ["North"],
            "target": {"fieldId": "orders.region"},
        }]}, "metrics": None},
        "sorts": [{"fieldId": "orders.revenue", "descending": True}],
        "limit": 100,
        "projectId": "project-a",
        "commitSha": "a" * 40,
    })
    compiled = compile_metric_query(query, context)
    assert "FROM [dbo].[orders]" in compiled.sql
    assert "SUM([revenue]) AS [orders.revenue]" in compiled.sql
    assert "[region] = %s" in compiled.sql
    assert compiled.parameters == ["North"]
    assert "North" not in compiled.sql


@pytest.mark.asyncio
async def test_private_dashboard_is_immutable_versioned_and_owner_scoped(db_session: AsyncSession) -> None:
    created = await dashboard_store.create_private_dashboard(
        db_session, org_id="org-a", user_id="owner-a", definition=_fixture_definition()
    )
    assert created.version.ordinal == 1
    assert created.version.definition.signalPilot.dashboardId == created.dashboard.id
    assert await dashboard_store.get_private_dashboard(
        db_session, org_id="org-a", user_id="owner-b", dashboard_id=created.dashboard.id
    ) is None
    assert await dashboard_store.get_private_dashboard(
        db_session, org_id="org-b", user_id="owner-a", dashboard_id=created.dashboard.id
    ) is None

    changed = created.version.definition.model_copy(update={"name": "Updated governed dashboard"})
    updated = await dashboard_store.create_dashboard_version(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=created.dashboard.id,
        expected_current_version_id=created.version.id,
        definition=changed,
    )
    assert updated.version.ordinal == 2
    assert updated.dashboard.current_version_id == updated.version.id
    original = await dashboard_store.get_private_dashboard(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=created.dashboard.id,
        version_id=created.version.id,
    )
    assert original is not None
    assert original.version.definition.name != updated.version.definition.name

    with pytest.raises(dashboard_store.DashboardConflictError):
        await dashboard_store.create_dashboard_version(
            db_session,
            org_id="org-a",
            user_id="owner-a",
            dashboard_id=created.dashboard.id,
            expected_current_version_id=created.version.id,
            definition=changed.model_copy(update={"name": "Stale write"}),
        )
