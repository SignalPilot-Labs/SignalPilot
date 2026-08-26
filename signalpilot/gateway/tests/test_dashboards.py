"""Phase 1 contracts for durable, governed, private dashboards."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api.dashboards import (
    _cached_receipt,
    _dashboard_failure,
    _DashboardConnectionRetryGate,
    _DashboardFailureRaised,
    _execute_dashboard_chart,
    _failure_code,
    _reject_truncated_time_series,
    dashboard_connection_retry_gate,
)
from gateway.dashboard import store as dashboard_store
from gateway.dashboard.cache import dashboard_query_cache_key
from gateway.dashboard.compiler import compile_custom_sql_query, compile_metric_query
from gateway.dashboard.confidence import dashboard_confidence_counts, semantic_query_signature
from gateway.dashboard.domain import AdHocSqlQuery, DashboardDefinition, FieldTarget, FilterRule, SemanticChartQuery
from gateway.dashboard.semantic_resolver import parse_approved_metrics, resolve_from_authorities
from gateway.db.models import GatewayBase, GatewayDashboardResult, GatewayStructuredQueryResult
from gateway.dbt.types import ColumnSpec, ModelInfo, ModelStatus, ProjectMap
from gateway.governance.query_executor import GovernedQueryError
from gateway.models.dashboards import DashboardQueryRequest

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
            ColumnSpec(name="customer", data_type="varchar", description="Customer"),
            ColumnSpec(name="ordered_at", data_type="datetime", description="Order timestamp"),
            ColumnSpec(name="revenue", data_type="decimal", description="Net revenue", tests=["not_null"]),
        ],
    )
    schema = {
        "dbo.orders": {
            "name": "orders",
            "schema": "dbo",
            "columns": [
                {"name": "region", "type": "varchar", "nullable": False},
                {"name": "customer", "type": "varchar", "nullable": False},
                {"name": "ordered_at", "type": "datetime", "nullable": False},
                {"name": "revenue", "type": "decimal", "nullable": False},
            ],
            "foreign_keys": [],
        }
    }
    metrics = parse_approved_metrics(
        {
            "dashboard_metrics": [
                {
                    "model": "orders",
                    "column": "revenue",
                    "aggregation": "sum",
                    "label": "Revenue",
                    "format": "currency:USD",
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
            ]
        }
    )
    return resolve_from_authorities(
        project_id="project-a",
        commit_sha="a" * 40,
        connection_name="warehouse",
        project_map=project_map,
        physical_schema=schema,
        semantic_model={
            "tables": {"dbo.orders": {"description": "Orders", "columns": {}}},
            "joins": [],
            "glossary": {},
        },
        approved_metrics=metrics,
    )


def _fixture_definition() -> DashboardDefinition:
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
    query = SemanticChartQuery.model_validate(
        {
            "kind": "semantic",
            "exploreName": "orders",
            "dimensions": ["orders.region"],
            "metrics": ["orders.revenue"],
            "filters": {
                "dimensions": {
                    "id": "root",
                    "and": [
                        {
                            "id": "region-filter",
                            "operator": "equals",
                            "values": ["North"],
                            "target": {"fieldId": "orders.region"},
                        }
                    ],
                },
                "metrics": None,
            },
            "sorts": [{"fieldId": "orders.revenue", "descending": True}],
            "limit": 100,
            "projectId": "project-a",
            "commitSha": "a" * 40,
        }
    )
    compiled = compile_metric_query(query, context)
    assert "FROM [dbo].[orders]" in compiled.sql
    assert "SUM([revenue]) AS [orders.revenue]" in compiled.sql
    assert "[region] = %s" in compiled.sql
    assert compiled.parameters == ["North"]
    assert "North" not in compiled.sql


def test_confidence_and_semantic_signatures_are_deterministic() -> None:
    definition = _fixture_definition()
    assert dashboard_confidence_counts(definition) == (5, 0)
    query = definition.charts[0].query
    assert isinstance(query, SemanticChartQuery)
    next_commit = query.model_copy(update={"commitSha": "b" * 40})
    other_project = query.model_copy(update={"projectId": "another-project"})
    assert semantic_query_signature(query) == semantic_query_signature(next_commit)
    assert semantic_query_signature(query) != semantic_query_signature(other_project)


def test_truncated_time_series_fails_closed_without_breaking_ranked_charts() -> None:
    definition = _fixture_definition()
    cartesian = next(chart for chart in definition.charts if chart.visualization.type == "cartesian")
    line = cartesian.model_copy(
        update={
            "visualization": cartesian.visualization.model_copy(
                update={"config": cartesian.visualization.config.model_copy(update={"seriesType": "line"})}
            )
        }
    )

    with pytest.raises(HTTPException) as raised:
        _reject_truncated_time_series(line, "truncated")
    assert raised.value.status_code == 422
    assert raised.value.detail["code"] == "dashboard_time_series_truncated"

    _reject_truncated_time_series(line, "complete")
    _reject_truncated_time_series(cartesian, "truncated")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("connection refused"), "data_source_unavailable"),
        (GovernedQueryError("credentials_missing", "hidden"), "authentication_rejected"),
        (GovernedQueryError("query_timeout", "hidden"), "query_timeout"),
        (GovernedQueryError("query_blocked", "hidden"), "query_invalid"),
        (HTTPException(status_code=422, detail="bad semantic field"), "semantic_definition_invalid"),
        (HTTPException(status_code=403, detail="hidden"), "permission_denied"),
        (HTTPException(status_code=429, detail="hidden"), "rate_limited"),
        (asyncio.CancelledError(), "cancelled"),
        (
            HTTPException(status_code=500, detail={"code": "dashboard_output_mismatch"}),
            "result_contract_mismatch",
        ),
        (
            HTTPException(status_code=409, detail={"code": "stale_dashboard_version"}),
            "stale_dashboard_version",
        ),
        (RuntimeError("unclassified failure"), "internal_error"),
    ],
)
def test_dashboard_failure_taxonomy_is_stable_and_safe(error: BaseException, expected: str) -> None:
    assert _failure_code(error) == expected
    failure = _dashboard_failure(error, connection_name="warehouse")
    assert failure.code == expected
    assert "hidden" not in failure.message
    assert "connection refused" not in failure.message


def test_cache_request_identity_is_exact_and_does_not_need_semantic_context() -> None:
    definition = _fixture_definition()
    chart = definition.charts[1]
    tile = definition.tiles[1]
    first = DashboardQueryRequest.model_validate(
        {
            "version_id": "version-1",
            "tile_uuid": tile.uuid,
            "dashboard_filters": [
                {"id": "b", "operator": "equals", "values": ["South"]},
                {"id": "a", "operator": "equals", "values": ["North"]},
            ],
            "drill_path": [{"field_id": "orders.region", "value": "North"}],
        }
    )
    reordered = first.model_copy(update={"dashboard_filters": list(reversed(first.dashboard_filters or []))})

    def key(body: DashboardQueryRequest, *, version_id: str = "version-1") -> str:
        return dashboard_query_cache_key(
            version_id=version_id,
            chart=chart,
            tile_uuid=tile.uuid,
            requested_filters=body.dashboard_filters or [],
            drill_path=body.drill_path,
            dashboard_filters=definition.filters,
        )

    assert key(first) == key(reordered)
    reordered_values = first.model_copy(
        update={
            "dashboard_filters": [
                (first.dashboard_filters or [])[0].model_copy(update={"values": ["South", "North"]}),
                (first.dashboard_filters or [])[1],
            ]
        }
    )
    same_values = first.model_copy(
        update={
            "dashboard_filters": [
                (first.dashboard_filters or [])[0].model_copy(update={"values": ["North", "South"]}),
                (first.dashboard_filters or [])[1],
            ]
        }
    )
    assert key(reordered_values) == key(same_values)
    assert key(first) != key(first, version_id="version-2")
    changed_filter = first.model_copy(
        update={
            "dashboard_filters": [
                (first.dashboard_filters or [])[0].model_copy(update={"values": ["East"]}),
                (first.dashboard_filters or [])[1],
            ]
        }
    )
    assert key(first) != key(changed_filter)
    changed_drill = first.model_copy(update={"drill_path": []})
    assert key(first) != key(changed_drill)


@pytest.mark.asyncio
async def test_exact_cached_result_returns_before_live_semantic_resolution(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    dashboard_connection_retry_gate._states.clear()
    definition = _fixture_definition()
    chart = definition.charts[0]
    tile = definition.tiles[0]
    body = DashboardQueryRequest(version_id="version-1", tile_uuid=tile.uuid)
    cache_key = dashboard_query_cache_key(
        version_id="version-1",
        chart=chart,
        tile_uuid=tile.uuid,
        requested_filters=[],
        drill_path=[],
        dashboard_filters=definition.filters,
    )
    stored = GatewayStructuredQueryResult(
        id="structured-1",
        execution_id="execution-1",
        org_id="org-a",
        owner_user_id=None,
        columns_json=[{"name": "orders.revenue", "logical_type": "number", "nullable": False}],
        rows_json=[{"orders.revenue": 1250}],
        preview_rows_json=[{"orders.revenue": 1250}],
        saved_row_count=1,
        source_completeness="complete",
        result_completeness="complete",
        display_completeness="complete",
        freshness_at=datetime.now(UTC),
    )
    cached = GatewayDashboardResult(
        id="dashboard-result-1",
        dashboard_id="dashboard-1",
        version_id="version-1",
        chart_id=chart.id,
        org_id="org-a",
        execution_id="execution-1",
        structured_result_id=stored.id,
        cache_key=cache_key,
        sql_hash="a" * 64,
        parameter_hash="b" * 64,
        tables_json=["dbo.orders"],
        semantic_definition_json={},
        completeness="complete",
        freshness_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    db_session.add_all([stored, cached])
    await db_session.commit()
    store = SimpleNamespace(session=db_session, user_id="user-a", _require_org_id=lambda: "org-a")

    async def unexpected_resolve(*args, **kwargs):
        raise AssertionError("live semantic resolution must not run on an exact cache hit")

    monkeypatch.setattr("gateway.api.dashboards.resolver.resolve", unexpected_resolve)
    receipt = await _execute_dashboard_chart(
        dashboard=SimpleNamespace(id="dashboard-1", connection_name="warehouse", project_id="project-1"),
        query_version_id="version-1",
        query_commit_sha="a" * 40,
        parsed=definition,
        chart_id=chart.id,
        body=body,
        store=store,
    )
    assert receipt.dashboard_result_id == cached.id
    assert receipt.cache_state == "fresh"

    async def unavailable_resolve(*args, **kwargs):
        raise RuntimeError("connection refused at warehouse.internal:1433 with token=must-not-leak")

    monkeypatch.setattr("gateway.api.dashboards.resolver.resolve", unavailable_resolve)
    degraded = await _execute_dashboard_chart(
        dashboard=SimpleNamespace(id="dashboard-1", connection_name="warehouse", project_id="project-1"),
        query_version_id="version-1",
        query_commit_sha="a" * 40,
        parsed=definition,
        chart_id=chart.id,
        body=body.model_copy(update={"refresh": True, "retry_token": "retry-1"}),
        store=store,
    )
    assert degraded.rows == stored.rows_json
    assert degraded.cache_state == "cached_source_unavailable"
    assert degraded.refresh_failure is not None
    assert degraded.refresh_failure.code == "data_source_unavailable"
    assert "must-not-leak" not in degraded.refresh_failure.message

    with pytest.raises(HTTPException) as cache_miss:
        await _execute_dashboard_chart(
            dashboard=SimpleNamespace(id="dashboard-1", connection_name="warehouse", project_id="project-1"),
            query_version_id="version-2",
            query_commit_sha="a" * 40,
            parsed=definition,
            chart_id=chart.id,
            body=body.model_copy(update={"version_id": "version-2"}),
            store=store,
        )
    assert cache_miss.value.status_code == 503
    assert cache_miss.value.detail["code"] == "data_source_unavailable"
    assert cache_miss.value.detail["cache_state"] == "no_usable_cache"
    assert (
        await _cached_receipt(
            SimpleNamespace(session=db_session, _require_org_id=lambda: "org-b"),
            dashboard_id="dashboard-1",
            version_id="version-1",
            chart_id=chart.id,
            cache_key=cache_key,
        )
        is None
    )
    dashboard_connection_retry_gate._states.clear()


@pytest.mark.asyncio
async def test_connection_retry_gate_deduplicates_outages_and_allows_one_new_retry() -> None:
    gate = _DashboardConnectionRetryGate()
    calls = 0
    source_failure = _dashboard_failure(RuntimeError("connection refused"), connection_name="warehouse")

    async def fail():
        nonlocal calls
        calls += 1
        raise _DashboardFailureRaised(source_failure)

    with pytest.raises(_DashboardFailureRaised):
        await gate.run(org_id="org-a", connection_name="warehouse", retry_token=None, operation=fail)
    with pytest.raises(_DashboardFailureRaised):
        await gate.run(org_id="org-a", connection_name="warehouse", retry_token=None, operation=fail)
    assert calls == 1

    with pytest.raises(_DashboardFailureRaised):
        await gate.run(org_id="org-a", connection_name="warehouse", retry_token="retry-1", operation=fail)
    with pytest.raises(_DashboardFailureRaised):
        await gate.run(org_id="org-a", connection_name="warehouse", retry_token="retry-1", operation=fail)
    assert calls == 2

    async def recover():
        return "fresh"

    result, recovered = await gate.run(
        org_id="org-a",
        connection_name="warehouse",
        retry_token="retry-2",
        operation=recover,
    )
    assert (result, recovered) == ("fresh", True)
    assert gate._states == {}


def test_compiler_supports_multiselect_absolute_dates_and_drill() -> None:
    context = _authorities()
    query = SemanticChartQuery.model_validate(
        {
            "kind": "semantic",
            "exploreName": "orders",
            "dimensions": ["orders.region"],
            "metrics": ["orders.revenue"],
            "filters": {},
            "sorts": [{"fieldId": "orders.region", "descending": False}],
            "limit": 100,
            "timezone": "America/Sao_Paulo",
            "projectId": "project-a",
            "commitSha": "a" * 40,
        }
    )
    compiled = compile_metric_query(
        query,
        context,
        runtime_filters=[
            FilterRule(
                id="regions", operator="equals", values=["North", "South"], target=FieldTarget(fieldId="orders.region")
            ),
            FilterRule(
                id="dates",
                operator="inBetween",
                values=["2026-08-01", "2026-09-01"],
                target=FieldTarget(fieldId="orders.ordered_at"),
            ),
            FilterRule(id="drill", operator="equals", values=["North"], target=FieldTarget(fieldId="orders.region")),
        ],
        drill_dimensions=["orders.customer"],
    )
    assert "[region] IN (%s, %s)" in compiled.sql
    assert "[ordered_at] >= %s AND [ordered_at] < %s" in compiled.sql
    assert "[customer] AS [orders.customer]" in compiled.sql
    assert "GROUP BY [customer]" in compiled.sql
    assert compiled.parameters == [
        "North",
        "South",
        datetime(2026, 8, 1, 3, 0, tzinfo=UTC),
        datetime(2026, 9, 1, 3, 0, tzinfo=UTC),
        "North",
    ]


def test_compiler_normalizes_relative_date_in_dashboard_timezone() -> None:
    context = _authorities()
    query = SemanticChartQuery.model_validate(
        {
            "kind": "semantic",
            "exploreName": "orders",
            "dimensions": [],
            "metrics": ["orders.revenue"],
            "filters": {},
            "sorts": [],
            "limit": 1,
            "timezone": "America/Sao_Paulo",
            "projectId": "project-a",
            "commitSha": "a" * 40,
        }
    )
    compiled = compile_metric_query(
        query,
        context,
        runtime_filters=[
            FilterRule.model_validate(
                {
                    "id": "mtd",
                    "operator": "inPeriodToDate",
                    "values": [],
                    "target": {"fieldId": "orders.ordered_at"},
                    "settings": {"unitOfTime": "months"},
                }
            )
        ],
        now=datetime(2026, 8, 24, 15, 0, tzinfo=UTC),
    )
    assert compiled.parameters[0] == datetime(2026, 8, 1, 3, 0, tzinfo=UTC)
    assert compiled.parameters[1] == datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
    assert compiled.output_columns == [
        {
            "name": "orders.revenue",
            "logical_type": "number",
            "nullable": True,
            "label": "Revenue",
            "format": "currency:USD",
            "currency_code": "USD",
        }
    ]


def test_custom_sql_filters_only_declared_output_bindings_with_bound_values() -> None:
    query = AdHocSqlQuery.model_validate(
        {
            "kind": "sql",
            "connectionName": "warehouse",
            "sqlTemplate": "SELECT region, revenue FROM dbo.orders",
            "parameterDefinitions": [],
            "outputBindings": [
                {"dashboardFieldId": "orders.region", "outputColumn": "region", "logicalType": "string"}
            ],
            "limit": 100,
        }
    )
    compiled = compile_custom_sql_query(
        query,
        runtime_filters=[
            FilterRule(id="region", operator="equals", values=["North"], target=FieldTarget(fieldId="orders.region"))
        ],
    )
    assert compiled.sql.endswith("WHERE ([sp_dashboard].[region] = %s)")
    assert "North" not in compiled.sql
    assert compiled.parameters == ["North"]
    assert compiled.output_columns == [
        {
            "name": "region",
            "logical_type": "string",
            "nullable": True,
            "label": "Region",
            "format": None,
            "currency_code": None,
        }
    ]


@pytest.mark.asyncio
async def test_private_dashboard_is_immutable_versioned_and_owner_scoped(db_session: AsyncSession) -> None:
    created = await dashboard_store.create_private_dashboard(
        db_session, org_id="org-a", user_id="owner-a", definition=_fixture_definition()
    )
    assert created.version.ordinal == 1
    assert created.version.definition.signalPilot.dashboardId == created.dashboard.id
    assert (
        await dashboard_store.get_private_dashboard(
            db_session, org_id="org-a", user_id="owner-b", dashboard_id=created.dashboard.id
        )
        is None
    )
    assert (
        await dashboard_store.get_private_dashboard(
            db_session, org_id="org-b", user_id="owner-a", dashboard_id=created.dashboard.id
        )
        is None
    )

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


@pytest.mark.asyncio
async def test_organization_visibility_fork_lineage_and_reversible_archive(db_session: AsyncSession) -> None:
    created = await dashboard_store.create_private_dashboard(
        db_session, org_id="org-a", user_id="owner-a", definition=_fixture_definition()
    )
    assert (
        await dashboard_store.get_dashboard(
            db_session, org_id="org-a", user_id="viewer-b", dashboard_id=created.dashboard.id
        )
        is None
    )

    shared = await dashboard_store.set_dashboard_visibility(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=created.dashboard.id,
        visibility="organization",
    )
    visible = await dashboard_store.get_dashboard(
        db_session, org_id="org-a", user_id="viewer-b", dashboard_id=created.dashboard.id
    )
    assert visible is not None
    assert visible.dashboard.is_owner is False
    assert shared.dashboard.high_confidence_charts == 5
    assert shared.dashboard.low_confidence_charts == 0

    owner_organization_view = await dashboard_store.list_dashboards(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        scope="organization",
    )
    assert [item.id for item in owner_organization_view] == [created.dashboard.id]
    assert owner_organization_view[0].is_owner is True

    forked = await dashboard_store.fork_dashboard(
        db_session,
        org_id="org-a",
        user_id="viewer-b",
        dashboard_id=created.dashboard.id,
        version_id=created.version.id,
    )
    assert forked.dashboard.visibility == "private"
    assert forked.dashboard.parent_dashboard_id == created.dashboard.id
    assert forked.dashboard.parent_version_id == created.version.id
    assert forked.version.definition.signalPilot.dashboardId == forked.dashboard.id

    archived = await dashboard_store.set_dashboard_archived(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=created.dashboard.id,
        archived=True,
    )
    assert archived.dashboard.archived_at is not None
    assert (
        await dashboard_store.get_dashboard(
            db_session, org_id="org-a", user_id="viewer-b", dashboard_id=created.dashboard.id
        )
        is None
    )
    restored = await dashboard_store.set_dashboard_archived(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=created.dashboard.id,
        archived=False,
    )
    assert restored.dashboard.archived_at is None
