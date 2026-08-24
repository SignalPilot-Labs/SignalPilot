"""Private durable dashboard CRUD, semantic context, and governed chart queries."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from gateway.dashboard import store as dashboard_store
from gateway.dashboard.authoring import DashboardAuthoringAgent, materialize_agent_draft
from gateway.dashboard.compiler import (
    DashboardCompileError,
    compile_custom_sql_query,
    compile_distinct_values_query,
    compile_metric_query,
)
from gateway.dashboard.domain import DashboardDefinition, FieldTarget, FilterRule, SemanticChartQuery
from gateway.dashboard.operations import has_custom_sql, validate_dashboard_semantics
from gateway.dashboard.semantic_resolver import DashboardSemanticError, DashboardSemanticResolver
from gateway.db.models import GatewayDashboardResult, GatewayStructuredQueryResult, GatewayWorkspaceProject
from gateway.git.repos import branch_head_sha
from gateway.governance.query_executor import (
    GovernedQueryContext,
    GovernedQueryError,
    governed_query_executor,
)
from gateway.models.dashboards import (
    CreateDashboardRequest,
    CreateDashboardVersionRequest,
    DashboardAnalyzeRequest,
    DashboardAnalyzeResponse,
    DashboardAuthoringApplyRequest,
    DashboardAuthoringRequest,
    DashboardAuthoringSessionInfo,
    DashboardChartReference,
    DashboardDetail,
    DashboardDistinctValuesRequest,
    DashboardDistinctValuesResponse,
    DashboardListItem,
    DashboardQueryReceipt,
    DashboardQueryRequest,
    DashboardSemanticContext,
)
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.projects import evaluate_project_readiness
from gateway.store import org_secrets as org_secrets_store
from gateway.store import standalone_chat as chat_store
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
        if not isinstance(chart.query, SemanticChartQuery) and chart.query.connectionName != binding.connectionName:
            raise HTTPException(status_code=422, detail="Custom SQL connection does not match the dashboard")
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
        raise HTTPException(
            status_code=409,
            detail={
                "code": "stale_dashboard_version",
                "actual_current_version_id": exc.actual_current_version_id,
            },
        ) from exc
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


@router.post(
    "/dashboard-authoring/sessions",
    response_model=DashboardAuthoringSessionInfo,
    status_code=201,
    dependencies=[RequireScope("write")],
)
async def create_dashboard_authoring_session(body: DashboardAuthoringRequest, store: StoreD):
    org_id = store._require_org_id()
    user_id = _user_id(store)
    base_definition: DashboardDefinition | None = None
    dashboard_id = body.dashboard_id
    base_version_id = body.base_version_id
    if dashboard_id:
        rows = await dashboard_store.get_private_dashboard_rows(
            store.session,
            org_id=org_id,
            user_id=user_id,
            dashboard_id=dashboard_id,
            version_id=base_version_id,
        )
        if rows is None:
            raise HTTPException(status_code=404, detail="Dashboard not found")
        dashboard, base_version = rows
        if base_version.id != dashboard.current_version_id:
            raise HTTPException(status_code=409, detail="Authoring must start from the current immutable version")
        base_definition = DashboardDefinition.model_validate(base_version.definition_json)
        base_version_id = base_version.id
        project_id = dashboard.project_id
        commit_sha = base_version.commit_sha
    else:
        project_id = body.project_id
        commit_sha = body.commit_sha
        if not project_id:
            raise HTTPException(status_code=422, detail="New dashboard authoring requires project_id")
        if not commit_sha:
            project = (
                await store.session.execute(
                    select(GatewayWorkspaceProject).where(
                        GatewayWorkspaceProject.id == project_id,
                        GatewayWorkspaceProject.org_id == org_id,
                        GatewayWorkspaceProject.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if project is None:
                raise HTTPException(status_code=404, detail="Dashboard project not found")
            branch = body.branch or project.default_branch or "main"
            commit_sha = branch_head_sha(project.id, branch)
            if not commit_sha:
                raise HTTPException(status_code=409, detail="The selected project branch has no immutable head")
    try:
        context = await resolver.resolve(store, project_id=project_id, commit_sha=commit_sha)
    except DashboardSemanticError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    api_key = await org_secrets_store.resolve_anthropic_key(store.session, org_id)
    if not api_key:
        raise HTTPException(status_code=409, detail="Dashboard authoring requires the organization Anthropic key")
    agent = DashboardAuthoringAgent(api_key=api_key)
    try:
        draft = await agent.draft(prompt=body.prompt, context=context, base_definition=base_definition)
        definition = materialize_agent_draft(draft, base_definition=base_definition)
        if base_definition is None:
            binding = definition.signalPilot.model_copy(
                update={
                    "dashboardId": f"draft-{uuid.uuid4()}",
                    "projectId": context.project_id,
                    "connectionName": context.connection_name,
                    "commitSha": context.commit_sha,
                    "semanticFingerprint": context.semantic_fingerprint,
                    "timezone": body.timezone,
                }
            )
            charts = []
            for chart in definition.charts:
                query = chart.query
                if isinstance(query, SemanticChartQuery):
                    query = query.model_copy(update={"projectId": context.project_id, "commitSha": context.commit_sha})
                charts.append(chart.model_copy(update={"query": query}))
            definition = DashboardDefinition.model_validate(
                definition.model_copy(update={"signalPilot": binding, "charts": charts})
            )
        verified = await _verified_context(store, definition)
        validate_dashboard_semantics(definition, verified)
    except (DashboardCompileError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Agent draft rejected: {exc}") from exc
    custom_sql = has_custom_sql(definition)
    return await dashboard_store.create_authoring_session(
        store.session,
        org_id=org_id,
        user_id=user_id,
        dashboard_id=dashboard_id,
        base_version_id=base_version_id,
        definition=definition,
        operations=[operation.model_dump(mode="json") for operation in draft.operations],
        prompt=body.prompt,
        summary=draft.summary,
        agent_run_id=str(uuid.uuid4()),
        model=agent.model,
        requires_custom_sql_confirmation=custom_sql,
        custom_sql_confirmed=body.confirm_custom_sql,
    )


@router.post(
    "/dashboard-authoring/sessions/{session_id}/confirm-custom-sql",
    response_model=DashboardAuthoringSessionInfo,
    dependencies=[RequireScope("write")],
)
async def confirm_dashboard_authoring_custom_sql(session_id: str, store: StoreD):
    try:
        return await dashboard_store.confirm_authoring_custom_sql(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            session_id=session_id,
        )
    except dashboard_store.DashboardNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Dashboard authoring preview not found") from exc
    except dashboard_store.DashboardValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/dashboard-authoring/sessions/{session_id}/apply",
    response_model=DashboardDetail,
    status_code=201,
    dependencies=[RequireScope("write")],
)
async def apply_dashboard_authoring_session(
    session_id: str, body: DashboardAuthoringApplyRequest, store: StoreD
):
    row = await dashboard_store.get_authoring_session(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        session_id=session_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Dashboard authoring preview not found")
    definition = DashboardDefinition.model_validate(row.definition_json)
    context = await _verified_context(store, definition)
    try:
        validate_dashboard_semantics(definition, context)
        return await dashboard_store.apply_authoring_session(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            session_id=session_id,
            expected_current_version_id=body.expected_current_version_id,
            visible_complete_result_ids=body.visible_complete_result_ids,
        )
    except dashboard_store.DashboardNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Dashboard authoring preview not found") from exc
    except dashboard_store.DashboardConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "stale_dashboard_version", "actual_current_version_id": exc.actual_current_version_id},
        ) from exc
    except (DashboardCompileError, dashboard_store.DashboardValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _cached_receipt(store: StoreD, *, dashboard_id: str, version_id: str, cache_key: str):
    now = datetime.now(UTC)
    row = (
        await store.session.execute(
            select(GatewayDashboardResult, GatewayStructuredQueryResult)
            .join(
                GatewayStructuredQueryResult,
                GatewayStructuredQueryResult.id == GatewayDashboardResult.structured_result_id,
            )
            .where(
                GatewayDashboardResult.org_id == store._require_org_id(),
                GatewayDashboardResult.dashboard_id == dashboard_id,
                GatewayDashboardResult.version_id == version_id,
                GatewayDashboardResult.cache_key == cache_key,
            )
            .order_by(GatewayDashboardResult.created_at.desc())
            .limit(1)
        )
    ).one_or_none()
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
        cache_state="fresh"
        if dashboard_result.expires_at.replace(tzinfo=dashboard_result.expires_at.tzinfo or UTC) > now
        else "stale",
    )


def _tile_for_chart(definition: DashboardDefinition, chart_id: str, tile_uuid: str | None):
    tile = next(
        (
            item
            for item in definition.tiles
            if item.chartId == chart_id and (tile_uuid is None or item.uuid == tile_uuid)
        ),
        None,
    )
    if tile is None:
        raise HTTPException(status_code=422, detail="Chart tile does not match the dashboard version")
    return tile


def _runtime_filters_for_tile(definition: DashboardDefinition, tile_uuid: str, chart, requested) -> list[FilterRule]:
    saved_by_id = {rule.id: rule for rule in definition.filters.dimensions}
    runtime: list[FilterRule] = []
    for override in requested:
        saved = saved_by_id.get(override.id)
        if saved is None:
            raise HTTPException(status_code=422, detail=f"Unknown dashboard filter: {override.id}")
        explicit_target = (saved.tileTargets or {}).get(tile_uuid)
        if explicit_target is None:
            if not isinstance(chart.query, SemanticChartQuery) or saved.target.tableName != chart.query.exploreName:
                continue
            target = saved.target
        else:
            target = explicit_target
        if target is False:
            continue
        runtime.append(
            FilterRule(
                id=saved.id,
                operator=override.operator,
                values=override.values,
                target=FieldTarget(fieldId=target.fieldId),
                settings=override.settings,
            )
        )
    return runtime


def _drill_query_state(chart, drill_path):
    if not drill_path:
        return None, []
    if not isinstance(chart.query, SemanticChartQuery):
        raise HTTPException(status_code=422, detail="Custom SQL charts do not support semantic drill paths")
    configured = chart.signalPilot.drillDimensions or chart.signalPilot.tableGroups or []
    base = chart.query.dimensions[-1:]
    hierarchy = [*base, *(field for field in configured if field not in base)]
    if len(drill_path) >= len(hierarchy):
        raise HTTPException(status_code=422, detail="Drill path exceeds the configured hierarchy")
    filters: list[FilterRule] = []
    for index, step in enumerate(drill_path):
        if step.field_id != hierarchy[index]:
            raise HTTPException(status_code=422, detail="Drill path does not match the configured hierarchy")
        filters.append(
            FilterRule(
                id=f"drill-{index}",
                operator="equals",
                values=[step.value],
                target=FieldTarget(fieldId=step.field_id),
            )
        )
    return [hierarchy[len(drill_path)]], filters


async def _execute_dashboard_chart(
    *,
    dashboard,
    query_version_id: str,
    query_commit_sha: str,
    parsed: DashboardDefinition,
    chart_id: str,
    body: DashboardQueryRequest,
    store: StoreD,
    custom_sql_confirmed: bool = True,
) -> DashboardQueryReceipt:
    chart = next((item for item in parsed.charts if item.id == chart_id), None)
    if chart is None:
        raise HTTPException(status_code=404, detail="Chart not found")
    if chart.query.kind == "sql" and not custom_sql_confirmed:
        raise HTTPException(
            status_code=409,
            detail={"code": "custom_sql_confirmation_required", "message": "Confirm custom SQL before preview execution"},
        )
    tile = _tile_for_chart(parsed, chart_id, body.tile_uuid)
    context = await _verified_context(store, parsed)
    requested_filters = body.dashboard_filters
    if requested_filters is None:
        requested_filters = [
            rule for rule in parsed.filters.dimensions if rule.values or rule.operator in {"isNull", "notNull"}
        ]
    runtime_filters = _runtime_filters_for_tile(parsed, tile.uuid, chart, requested_filters)
    drill_dimensions, drill_filters = _drill_query_state(chart, body.drill_path)
    try:
        compiled = (
            compile_metric_query(
                chart.query,
                context,
                runtime_filters=[*runtime_filters, *drill_filters],
                drill_dimensions=drill_dimensions,
            )
            if isinstance(chart.query, SemanticChartQuery)
            else compile_custom_sql_query(
                chart.query,
                runtime_filters=runtime_filters,
                timezone=parsed.signalPilot.timezone,
            )
        )
    except DashboardCompileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    parameter_hash = hashlib.sha256(
        json.dumps(compiled.parameters, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    cache_key = hashlib.sha256(
        json.dumps(
            {
                "version_id": query_version_id,
                "chart_id": chart.id,
                "sql": compiled.sql,
                "parameters": compiled.parameters,
                "drill_path": [step.model_dump() for step in body.drill_path],
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()
    if not body.refresh:
        cached = await _cached_receipt(
            store, dashboard_id=dashboard.id, version_id=query_version_id, cache_key=cache_key
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
                commit_sha=query_commit_sha,
            ),
        )
    except GovernedQueryError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc
    stored = (
        await store.session.execute(
            select(GatewayStructuredQueryResult).where(
                GatewayStructuredQueryResult.id == result.result_id,
                GatewayStructuredQueryResult.org_id == store._require_org_id(),
            )
        )
    ).scalar_one()
    expected_outputs = [str(column["name"]) for column in compiled.output_columns]
    result_columns = result.columns
    if result.row_count == 0 and not result_columns:
        result_columns = compiled.output_columns
    output_check = compare_columns(expected_outputs, [str(column.get("name")) for column in result_columns])
    if not output_check.valid:
        raise HTTPException(
            status_code=500,
            detail={"code": "dashboard_output_mismatch", "missing_fields": output_check.missing},
        )
    stored.owner_user_id = None
    stored.result_origin = "dashboard"
    stored.columns_json = result_columns
    now = datetime.now(UTC)
    dashboard_result = GatewayDashboardResult(
        id=str(uuid.uuid4()),
        dashboard_id=dashboard.id,
        version_id=query_version_id,
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
        columns=result_columns,
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
    query_version_id = version.id
    query_commit_sha = version.commit_sha
    parsed = DashboardDefinition.model_validate(version.definition_json)
    if body.authoring_session_id:
        authoring = await dashboard_store.get_authoring_session(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            session_id=body.authoring_session_id,
        )
        if authoring is None or authoring.dashboard_id != dashboard.id or authoring.base_version_id != version.id:
            raise HTTPException(status_code=404, detail="Dashboard authoring preview not found")
        if authoring.status != "preview":
            raise HTTPException(status_code=409, detail="Dashboard authoring preview is no longer active")
        parsed = DashboardDefinition.model_validate(authoring.definition_json)
        query_version_id = f"draft:{authoring.id}"
        query_commit_sha = authoring.commit_sha
    return await _execute_dashboard_chart(
        dashboard=dashboard,
        query_version_id=query_version_id,
        query_commit_sha=query_commit_sha,
        parsed=parsed,
        chart_id=chart_id,
        body=body,
        store=store,
        custom_sql_confirmed=(not body.authoring_session_id or authoring.custom_sql_confirmed),
    )


@router.post(
    "/dashboard-authoring/sessions/{session_id}/charts/{chart_id}/query",
    response_model=DashboardQueryReceipt,
    dependencies=[RequireScope("query")],
)
async def query_new_dashboard_authoring_preview(
    session_id: str,
    chart_id: str,
    body: DashboardQueryRequest,
    store: StoreD,
):
    authoring = await dashboard_store.get_authoring_session(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        session_id=session_id,
    )
    if authoring is None or authoring.dashboard_id is not None or authoring.status != "preview":
        raise HTTPException(status_code=404, detail="New dashboard authoring preview not found")
    parsed = DashboardDefinition.model_validate(authoring.definition_json)
    dashboard = SimpleNamespace(
        id=f"draft:{authoring.id}",
        project_id=authoring.project_id,
        connection_name=authoring.connection_name,
    )
    return await _execute_dashboard_chart(
        dashboard=dashboard,
        query_version_id=f"draft:{authoring.id}",
        query_commit_sha=authoring.commit_sha,
        parsed=parsed,
        chart_id=chart_id,
        body=body,
        store=store,
        custom_sql_confirmed=authoring.custom_sql_confirmed,
    )


@router.post(
    "/dashboards/{dashboard_id}/filters/{filter_id}/values",
    response_model=DashboardDistinctValuesResponse,
    dependencies=[RequireScope("query")],
)
async def get_dashboard_filter_values(
    dashboard_id: str,
    filter_id: str,
    body: DashboardDistinctValuesRequest,
    store: StoreD,
):
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
    definition = DashboardDefinition.model_validate(version.definition_json)
    saved = next((item for item in definition.filters.dimensions if item.id == filter_id), None)
    if saved is None:
        raise HTTPException(status_code=404, detail="Dashboard filter not found")
    context = await _verified_context(store, definition)
    try:
        compiled = compile_distinct_values_query(
            explore_name=saved.target.tableName,
            field_id=saved.target.fieldId,
            context=context,
            search=body.search,
            limit=body.limit,
        )
        result = await governed_query_executor.execute(
            store,
            connection_name=dashboard.connection_name,
            sql=compiled.sql,
            parameters=compiled.parameters,
            row_limit=body.limit,
            timeout_seconds=30,
            context=GovernedQueryContext(
                path="dashboard",
                project_id=dashboard.project_id,
                commit_sha=version.commit_sha,
            ),
        )
    except (DashboardCompileError, GovernedQueryError) as exc:
        detail = {"code": exc.code, "message": str(exc)} if isinstance(exc, GovernedQueryError) else str(exc)
        raise HTTPException(status_code=422, detail=detail) from exc
    return DashboardDistinctValuesResponse(
        values=[row.get("value") for row in result.rows],
        execution_id=result.execution_id,
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


@router.post(
    "/dashboards/{dashboard_id}/charts/{chart_id}/analyze",
    response_model=DashboardAnalyzeResponse,
    status_code=201,
    dependencies=[RequireScope("write")],
)
async def analyze_dashboard_chart(
    dashboard_id: str,
    chart_id: str,
    body: DashboardAnalyzeRequest,
    store: StoreD,
):
    org_id = store._require_org_id()
    user_id = _user_id(store)
    rows = await dashboard_store.get_private_dashboard_rows(
        store.session,
        org_id=org_id,
        user_id=user_id,
        dashboard_id=dashboard_id,
        version_id=body.version_id,
    )
    if rows is None:
        raise HTTPException(status_code=404, detail="Dashboard chart not found")
    dashboard, version = rows
    definition = DashboardDefinition.model_validate(version.definition_json)
    chart = next((item for item in definition.charts if item.id == chart_id), None)
    if chart is None:
        raise HTTPException(status_code=404, detail="Dashboard chart not found")
    tile = _tile_for_chart(definition, chart_id, body.tile_uuid)
    result_row = (
        await store.session.execute(
            select(GatewayDashboardResult, GatewayStructuredQueryResult)
            .join(
                GatewayStructuredQueryResult,
                GatewayStructuredQueryResult.id == GatewayDashboardResult.structured_result_id,
            )
            .where(
                GatewayDashboardResult.id == body.dashboard_result_id,
                GatewayDashboardResult.dashboard_id == dashboard.id,
                GatewayDashboardResult.version_id == version.id,
                GatewayDashboardResult.chart_id == chart.id,
                GatewayDashboardResult.org_id == org_id,
            )
        )
    ).one_or_none()
    if result_row is None:
        raise HTTPException(status_code=404, detail="Exact dashboard result not found")
    dashboard_result, structured = result_row
    date_filters = [
        item.model_dump(mode="json")
        for item in body.dashboard_filters
        if item.operator in {"inBetween", "inThePast", "inTheCurrent", "inPeriodToDate"}
    ]
    receipt = {
        "execution_id": dashboard_result.execution_id,
        "sql_hash": dashboard_result.sql_hash,
        "parameter_hash": dashboard_result.parameter_hash,
        "tables": dashboard_result.tables_json,
        "completeness": dashboard_result.completeness,
        "freshness_at": dashboard_result.freshness_at,
        "result_time": dashboard_result.created_at,
    }
    chart_reference = DashboardChartReference(
        dashboard_id=dashboard.id,
        dashboard_version_id=version.id,
        tile_uuid=tile.uuid,
        chart_id=chart.id,
        dashboard_result_id=dashboard_result.id,
        execution_id=dashboard_result.execution_id,
        dashboard_filters=body.dashboard_filters,
        date_window={"filters": date_filters, "timezone": definition.signalPilot.timezone} if date_filters else None,
        drill_path=body.drill_path,
        selected_mark=body.selected_mark,
        semantic_references={
            "project_id": version.project_id,
            "commit_sha": version.commit_sha,
            "semantic_fingerprint": version.semantic_fingerprint,
            "chart_query": chart.query.model_dump(mode="json"),
            "semantic_definition": dashboard_result.semantic_definition_json,
        },
        receipt=receipt,
        result={
            "columns": structured.columns_json,
            "rows": structured.rows_json,
            "row_count": structured.saved_row_count,
            "completeness": structured.result_completeness,
        },
        provenance_ref=chart.signalPilot.provenanceRef,
    )
    project = (
        await store.session.execute(
            select(GatewayWorkspaceProject).where(
                GatewayWorkspaceProject.id == dashboard.project_id,
                GatewayWorkspaceProject.org_id == org_id,
                GatewayWorkspaceProject.status == "active",
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=409, detail="Dashboard project is unavailable for Data Chat")
    readiness = await evaluate_project_readiness(
        store.session, org_id=org_id, user_id=user_id, project=project
    )
    if not readiness.ready or not readiness.branch:
        raise HTTPException(status_code=409, detail="Dashboard project is not ready for Data Chat")
    conversation, _ = await chat_store.create_conversation_with_run(
        store.session,
        org_id=org_id,
        user_id=user_id,
        project=project,
        branch=readiness.branch,
        message=body.message,
        commit_sha=version.commit_sha,
        message_metadata={
            "dashboard_chart_reference": chart_reference.model_dump(mode="json"),
            "dashboard_analysis_read_only": True,
        },
    )
    return DashboardAnalyzeResponse(conversation_id=conversation.id, chart_reference=chart_reference)
