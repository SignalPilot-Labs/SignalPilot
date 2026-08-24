"""Private durable dashboard CRUD, semantic context, and governed chart queries."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from gateway.dashboard import store as dashboard_store
from gateway.dashboard.compiler import DashboardCompileError, compile_metric_query
from gateway.dashboard.domain import DashboardDefinition, SemanticChartQuery
from gateway.dashboard.semantic_resolver import DashboardSemanticError, DashboardSemanticResolver
from gateway.db.models import GatewayDashboardResult, GatewayStructuredQueryResult
from gateway.governance.query_executor import (
    GovernedQueryContext,
    GovernedQueryError,
    governed_query_executor,
)
from gateway.models.dashboards import (
    CreateDashboardRequest,
    CreateDashboardVersionRequest,
    DashboardDetail,
    DashboardListItem,
    DashboardQueryReceipt,
    DashboardQueryRequest,
    DashboardSemanticContext,
)
from gateway.security.scope_guard import RequireScope
from gateway.verification import compare_columns

from .deps import StoreD

router = APIRouter(prefix="/api")
resolver = DashboardSemanticResolver()


def _user_id(store: StoreD) -> str:
    return store.user_id or "local"


async def _verified_context(store: StoreD, definition: DashboardDefinition) -> DashboardSemanticContext:
    binding = definition.signalPilot
    try:
        context = await resolver.resolve(store, project_id=binding.projectId, commit_sha=binding.commitSha)
    except DashboardSemanticError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if context.connection_name != binding.connectionName:
        raise HTTPException(status_code=422, detail="Dashboard connection does not match the project")
    if context.semantic_fingerprint != binding.semanticFingerprint:
        raise HTTPException(
            status_code=409,
            detail={"code": "semantic_context_changed", "actual_semantic_fingerprint": context.semantic_fingerprint},
        )
    for chart in definition.charts:
        if isinstance(chart.query, SemanticChartQuery) and (
            chart.query.projectId != binding.projectId or chart.query.commitSha != binding.commitSha
        ):
            raise HTTPException(status_code=422, detail="Chart semantic binding does not match the dashboard")
    return context


@router.get("/dashboards", response_model=list[DashboardListItem], dependencies=[RequireScope("read")])
async def list_dashboards(store: StoreD):
    return await dashboard_store.list_private_dashboards(
        store.session, org_id=store._require_org_id(), user_id=_user_id(store)
    )


@router.post(
    "/dashboards",
    response_model=DashboardDetail,
    status_code=201,
    dependencies=[RequireScope("write")],
)
async def create_dashboard(body: CreateDashboardRequest, store: StoreD):
    await _verified_context(store, body.definition)
    return await dashboard_store.create_private_dashboard(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        definition=body.definition,
    )


@router.get("/dashboards/{dashboard_id}", response_model=DashboardDetail, dependencies=[RequireScope("read")])
async def get_dashboard(dashboard_id: str, store: StoreD, version_id: str | None = None):
    detail = await dashboard_store.get_private_dashboard(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        dashboard_id=dashboard_id,
        version_id=version_id,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return detail


@router.post(
    "/dashboards/{dashboard_id}/versions",
    response_model=DashboardDetail,
    status_code=201,
    dependencies=[RequireScope("write")],
)
async def create_dashboard_version(dashboard_id: str, body: CreateDashboardVersionRequest, store: StoreD):
    await _verified_context(store, body.definition)
    try:
        return await dashboard_store.create_dashboard_version(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            dashboard_id=dashboard_id,
            expected_current_version_id=body.expected_current_version_id,
            definition=body.definition,
        )
    except dashboard_store.DashboardNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Dashboard not found") from exc
    except dashboard_store.DashboardConflictError as exc:
        raise HTTPException(status_code=409, detail={
            "code": "stale_dashboard_version",
            "actual_current_version_id": exc.actual_current_version_id,
        }) from exc
    except dashboard_store.DashboardValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/dashboard-semantic-context",
    response_model=DashboardSemanticContext,
    dependencies=[RequireScope("read")],
)
async def get_dashboard_semantic_context(project_id: str, commit_sha: str, store: StoreD):
    try:
        return await resolver.resolve(store, project_id=project_id, commit_sha=commit_sha)
    except DashboardSemanticError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _cached_receipt(store: StoreD, *, dashboard_id: str, version_id: str, cache_key: str):
    now = datetime.now(UTC)
    row = (await store.session.execute(
        select(GatewayDashboardResult, GatewayStructuredQueryResult)
        .join(GatewayStructuredQueryResult, GatewayStructuredQueryResult.id == GatewayDashboardResult.structured_result_id)
        .where(
            GatewayDashboardResult.org_id == store._require_org_id(),
            GatewayDashboardResult.dashboard_id == dashboard_id,
            GatewayDashboardResult.version_id == version_id,
            GatewayDashboardResult.cache_key == cache_key,
            GatewayDashboardResult.expires_at > now,
        )
        .order_by(GatewayDashboardResult.created_at.desc())
        .limit(1)
    )).one_or_none()
    if row is None:
        return None
    dashboard_result, stored = row
    return DashboardQueryReceipt(
        dashboard_result_id=dashboard_result.id,
        result_id=stored.id,
        execution_id=dashboard_result.execution_id,
        columns=stored.columns_json,
        rows=stored.rows_json,
        row_count=stored.saved_row_count,
        completeness=dashboard_result.completeness,
        result_time=dashboard_result.created_at,
        freshness_at=dashboard_result.freshness_at,
        sql_hash=dashboard_result.sql_hash,
        parameter_hash=dashboard_result.parameter_hash,
        tables=dashboard_result.tables_json,
        semantic_definition=dashboard_result.semantic_definition_json,
        compiled_sql=None,
        cache_state="fresh",
    )


@router.post(
    "/dashboards/{dashboard_id}/charts/{chart_id}/query",
    response_model=DashboardQueryReceipt,
    dependencies=[RequireScope("query")],
)
async def query_dashboard_chart(dashboard_id: str, chart_id: str, body: DashboardQueryRequest, store: StoreD):
    rows = await dashboard_store.get_private_dashboard_rows(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        dashboard_id=dashboard_id,
        version_id=body.version_id,
    )
    if rows is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    dashboard, version = rows
    parsed = DashboardDefinition.model_validate(version.definition_json)
    chart = next((item for item in parsed.charts if item.id == chart_id), None)
    if chart is None:
        raise HTTPException(status_code=404, detail="Chart not found")
    if not isinstance(chart.query, SemanticChartQuery):
        raise HTTPException(status_code=422, detail="Custom SQL dashboards require the Phase 3 confirmation flow")
    context = await _verified_context(store, parsed)
    try:
        compiled = compile_metric_query(chart.query, context)
    except DashboardCompileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    parameter_hash = hashlib.sha256(
        json.dumps(compiled.parameters, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    cache_key = hashlib.sha256(
        json.dumps({
            "version_id": version.id,
            "chart_id": chart.id,
            "sql": compiled.sql,
            "parameters": compiled.parameters,
        }, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    if not body.refresh:
        cached = await _cached_receipt(
            store, dashboard_id=dashboard.id, version_id=version.id, cache_key=cache_key
        )
        if cached is not None:
            return cached.model_copy(update={"compiled_sql": compiled.sql})
    try:
        result = await governed_query_executor.execute(
            store,
            connection_name=dashboard.connection_name,
            sql=compiled.sql,
            parameters=compiled.parameters,
            row_limit=chart.query.limit,
            timeout_seconds=60,
            context=GovernedQueryContext(
                path="dashboard",
                project_id=dashboard.project_id,
                commit_sha=version.commit_sha,
            ),
        )
    except GovernedQueryError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc
    stored = (await store.session.execute(select(GatewayStructuredQueryResult).where(
        GatewayStructuredQueryResult.id == result.result_id,
        GatewayStructuredQueryResult.org_id == store._require_org_id(),
    ))).scalar_one()
    expected_outputs = [*chart.query.dimensions, *chart.query.metrics]
    output_check = compare_columns(expected_outputs, [str(column.get("name")) for column in result.columns])
    if not output_check.valid:
        raise HTTPException(
            status_code=500,
            detail={"code": "dashboard_output_mismatch", "missing_fields": output_check.missing},
        )
    # Dashboard ownership is intentionally distinct from the generic
    # owner_user_id result endpoint. Only this dashboard-authorized join reads it.
    stored.owner_user_id = None
    stored.result_origin = "dashboard"
    now = datetime.now(UTC)
    dashboard_result = GatewayDashboardResult(
        id=str(uuid.uuid4()),
        dashboard_id=dashboard.id,
        version_id=version.id,
        chart_id=chart.id,
        org_id=store._require_org_id(),
        execution_id=result.execution_id,
        structured_result_id=result.result_id,
        cache_key=cache_key,
        sql_hash=result.sql_hash,
        parameter_hash=parameter_hash,
        tables_json=result.tables,
        semantic_definition_json=compiled.semantic_definition,
        completeness=result.completeness,
        freshness_at=stored.freshness_at,
        expires_at=now + timedelta(minutes=5),
    )
    store.session.add(dashboard_result)
    await store.session.commit()
    await store.session.refresh(dashboard_result)
    return DashboardQueryReceipt(
        dashboard_result_id=dashboard_result.id,
        result_id=result.result_id,
        execution_id=result.execution_id,
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        completeness=result.completeness,
        result_time=dashboard_result.created_at,
        freshness_at=dashboard_result.freshness_at,
        sql_hash=result.sql_hash,
        parameter_hash=parameter_hash,
        tables=result.tables,
        semantic_definition=compiled.semantic_definition,
        compiled_sql=compiled.sql,
        cache_state="miss" if not body.refresh else "refreshed",
    )


@router.get(
    "/dashboards/{dashboard_id}/charts/{chart_id}/data",
    response_model=DashboardQueryReceipt,
    dependencies=[RequireScope("read")],
)
async def get_dashboard_chart_data(
    dashboard_id: str,
    chart_id: str,
    dashboard_result_id: str,
    store: StoreD,
):
    authorized = await dashboard_store.get_private_dashboard_rows(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        dashboard_id=dashboard_id,
    )
    if authorized is None:
        raise HTTPException(status_code=404, detail="Dashboard result not found")
    row = (
        await store.session.execute(
            select(GatewayDashboardResult, GatewayStructuredQueryResult)
            .join(
                GatewayStructuredQueryResult,
                GatewayStructuredQueryResult.id == GatewayDashboardResult.structured_result_id,
            )
            .where(
                GatewayDashboardResult.id == dashboard_result_id,
                GatewayDashboardResult.dashboard_id == dashboard_id,
                GatewayDashboardResult.chart_id == chart_id,
                GatewayDashboardResult.org_id == store._require_org_id(),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Dashboard result not found")
    dashboard_result, stored = row
    expires_at = dashboard_result.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return DashboardQueryReceipt(
        dashboard_result_id=dashboard_result.id,
        result_id=stored.id,
        execution_id=dashboard_result.execution_id,
        columns=stored.columns_json,
        rows=stored.rows_json,
        row_count=stored.saved_row_count,
        completeness=dashboard_result.completeness,
        result_time=dashboard_result.created_at,
        freshness_at=dashboard_result.freshness_at,
        sql_hash=dashboard_result.sql_hash,
        parameter_hash=dashboard_result.parameter_hash,
        tables=dashboard_result.tables_json,
        semantic_definition=dashboard_result.semantic_definition_json,
        compiled_sql=None,
        cache_state="fresh" if expires_at > datetime.now(UTC) else "stale",
    )
