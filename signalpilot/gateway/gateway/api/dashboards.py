"""Private durable dashboard CRUD, semantic context, and governed chart queries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TypeVar

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from gateway.dashboard import store as dashboard_store
from gateway.dashboard.authoring import DashboardAuthoringAgent, materialize_agent_draft
from gateway.dashboard.cache import dashboard_query_cache_key
from gateway.dashboard.compiler import (
    DashboardCompileError,
    compile_custom_sql_query,
    compile_distinct_values_query,
    compile_metric_query,
)
from gateway.dashboard.confidence import semantic_query_signature
from gateway.dashboard.domain import DashboardDefinition, FieldTarget, FilterRule, SemanticChartQuery
from gateway.dashboard.operations import (
    canonicalize_dashboard_filter_targets,
    has_custom_sql,
    validate_dashboard_semantics,
    validate_time_series_default_windows,
)
from gateway.dashboard.semantic_resolver import DashboardSemanticError, DashboardSemanticResolver
from gateway.dashboard.telemetry import DashboardTelemetryEvent, record_dashboard_event
from gateway.db.models import (
    GatewayDashboard,
    GatewayDashboardResult,
    GatewayDashboardVersion,
    GatewayStructuredQueryResult,
    GatewayWorkspaceProject,
)
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
    DashboardAuthoringMessageRequest,
    DashboardAuthoringRequest,
    DashboardAuthoringSessionInfo,
    DashboardChartReference,
    DashboardClientTelemetryRequest,
    DashboardDetail,
    DashboardDistinctValuesRequest,
    DashboardDistinctValuesResponse,
    DashboardExportGrant,
    DashboardExportRequest,
    DashboardFailure,
    DashboardFailureCode,
    DashboardForkRequest,
    DashboardListItem,
    DashboardQueryReceipt,
    DashboardQueryRequest,
    DashboardSemanticContext,
    DashboardSuggestion,
    DashboardVisibilityRequest,
)
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.projects import evaluate_project_readiness
from gateway.store import org_secrets as org_secrets_store
from gateway.store import standalone_chat as chat_store
from gateway.verification import compare_columns

from .deps import StoreD

router = APIRouter(prefix="/api")
resolver = DashboardSemanticResolver()

DashboardResultT = TypeVar("DashboardResultT")


def _visualization_type(chart) -> str:
    if chart.visualization.type == "big_number":
        return "kpi"
    if chart.visualization.type == "table":
        return "table"
    return chart.visualization.config.seriesType


@dataclass
class _ConnectionFailureState:
    failure: DashboardFailure
    blocked_until: float
    retry_token: str | None
    consecutive_failures: int


class _DashboardConnectionRetryGate:
    """Deduplicate dashboard retries for one unavailable warehouse connection."""

    def __init__(self) -> None:
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._states: dict[tuple[str, str], _ConnectionFailureState] = {}

    async def run(
        self,
        *,
        org_id: str,
        connection_name: str,
        retry_token: str | None,
        operation: Callable[[], Awaitable[DashboardResultT]],
    ) -> tuple[DashboardResultT, bool]:
        key = (org_id, connection_name)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            state = self._states.get(key)
            recovering = state is not None
            now = time.monotonic()
            if state and state.blocked_until > now:
                is_new_manual_retry = retry_token is not None and retry_token != state.retry_token
                if not is_new_manual_retry:
                    raise _DashboardFailureRaised(state.failure)
            try:
                result = await operation()
            except _DashboardFailureRaised as exc:
                failure = exc.failure
                if failure.scope == "connection" and failure.retryable:
                    attempts = (state.consecutive_failures + 1) if state else 1
                    backoff = min(30, 2 ** min(attempts - 1, 4))
                    failure = failure.model_copy(update={"retry_after_seconds": backoff})
                    self._states[key] = _ConnectionFailureState(
                        failure=failure,
                        blocked_until=time.monotonic() + backoff,
                        retry_token=retry_token,
                        consecutive_failures=attempts,
                    )
                    raise _DashboardFailureRaised(failure) from exc
                raise
            self._states.pop(key, None)
            return result, recovering


class _DashboardFailureRaised(RuntimeError):
    def __init__(self, failure: DashboardFailure):
        super().__init__(failure.message)
        self.failure = failure


dashboard_connection_retry_gate = _DashboardConnectionRetryGate()


_FAILURE_MESSAGES: dict[DashboardFailureCode, str] = {
    "data_source_unavailable": "The data source is temporarily unavailable.",
    "authentication_rejected": "The data source rejected its saved credentials.",
    "query_timeout": "The data source did not finish the query in time.",
    "query_invalid": "This chart query is no longer valid for the data source.",
    "semantic_definition_invalid": "This chart's semantic definition is no longer valid.",
    "permission_denied": "You do not have permission to query this dashboard data.",
    "rate_limited": "Dashboard queries are temporarily rate limited.",
    "cancelled": "The dashboard query was cancelled.",
    "result_contract_mismatch": "The returned data does not match this chart's expected fields.",
    "stale_dashboard_version": "This dashboard version is no longer current.",
    "internal_error": "SignalPilot could not complete this dashboard query.",
}


def _failure_code(exc: BaseException) -> DashboardFailureCode:
    governed_code = exc.code if isinstance(exc, GovernedQueryError) else None
    if governed_code == "query_timeout":
        return "query_timeout"
    if governed_code == "query_cancelled" or isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    if governed_code in {"credentials_missing", "connection_not_found"}:
        return "authentication_rejected"
    if governed_code in {"query_blocked", "invalid_parameters"}:
        return "query_invalid"
    if governed_code in {"result_unavailable", "result_integrity_failed"}:
        return "result_contract_mismatch"

    status_code = exc.status_code if isinstance(exc, HTTPException) else None
    detail = exc.detail if isinstance(exc, HTTPException) else None
    detail_code = detail.get("code") if isinstance(detail, dict) else None
    if detail_code in {"semantic_context_changed", "stale_dashboard_version"}:
        return "stale_dashboard_version"
    if detail_code in {"dashboard_output_mismatch", "dashboard_time_series_truncated"}:
        return "result_contract_mismatch"
    if status_code == 403:
        return "permission_denied"
    if status_code == 429:
        return "rate_limited"
    if status_code == 409:
        return "stale_dashboard_version"
    if isinstance(exc, (DashboardCompileError, DashboardSemanticError)) or status_code == 422:
        return "semantic_definition_invalid"

    internal = str(exc).lower()
    if any(token in internal for token in ("login failed", "authentication", "password", "credentials")):
        return "authentication_rejected"
    if any(token in internal for token in ("permission denied", "access denied", "not authorized")):
        return "permission_denied"
    if "timeout" in internal or "timed out" in internal:
        return "query_timeout"
    if any(token in internal for token in ("connection refused", "unreachable", "network", "server is unavailable")):
        return "data_source_unavailable"
    if governed_code == "query_failed":
        if any(token in internal for token in ("syntax", "invalid column", "invalid object", "unknown column")):
            return "query_invalid"
        return "data_source_unavailable"
    return "internal_error"


def _dashboard_failure(
    exc: BaseException,
    *,
    connection_name: str,
    cache_fallback_available: bool = False,
) -> DashboardFailure:
    code = _failure_code(exc)
    retryable = code in {"data_source_unavailable", "query_timeout", "rate_limited", "internal_error"}
    scope = (
        "connection"
        if code in {"data_source_unavailable", "authentication_rejected", "query_timeout", "rate_limited"}
        else "dashboard"
        if code in {"permission_denied", "stale_dashboard_version", "internal_error"}
        else "chart"
    )
    return DashboardFailure(
        code=code,
        message=_FAILURE_MESSAGES[code],
        retryable=retryable,
        connection_name=connection_name,
        scope=scope,
        correlation_id=str(uuid.uuid4()),
        occurred_at=datetime.now(UTC),
        cache_fallback_available=cache_fallback_available,
    )


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
async def list_dashboards(
    store: StoreD,
    scope: str = "mine",
    search: str | None = None,
    include_archived: bool = False,
):
    if scope not in {"mine", "organization"}:
        raise HTTPException(status_code=422, detail="Dashboard scope must be mine or organization")
    return await dashboard_store.list_dashboards(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        scope=scope,
        search=search,
        include_archived=include_archived,
    )


@router.post(
    "/dashboards",
    response_model=DashboardDetail,
    status_code=201,
    dependencies=[RequireScope("write")],
)
async def create_dashboard(body: CreateDashboardRequest, store: StoreD):
    await _verified_context(store, body.definition)
    detail = await dashboard_store.create_private_dashboard(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        definition=body.definition,
    )
    await record_dashboard_event(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        event_type=DashboardTelemetryEvent.SAVED,
        connection_name=detail.dashboard.connection_name,
        metadata={
            "dashboard_id": detail.dashboard.id,
            "version_id": detail.version.id,
            "chart_count": len(detail.version.definition.charts),
        },
    )
    return detail


@router.get("/dashboards/{dashboard_id}", response_model=DashboardDetail, dependencies=[RequireScope("read")])
async def get_dashboard(dashboard_id: str, store: StoreD, version_id: str | None = None):
    detail = await dashboard_store.get_dashboard(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        dashboard_id=dashboard_id,
        version_id=version_id,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    await record_dashboard_event(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        event_type=DashboardTelemetryEvent.OPENED,
        connection_name=detail.dashboard.connection_name,
        metadata={
            "dashboard_id": detail.dashboard.id,
            "version_id": detail.version.id,
        },
    )
    return detail


@router.post(
    "/dashboards/{dashboard_id}/telemetry",
    status_code=204,
    dependencies=[RequireScope("read")],
)
async def record_dashboard_client_telemetry(
    dashboard_id: str,
    body: DashboardClientTelemetryRequest,
    store: StoreD,
) -> None:
    rows = await dashboard_store.get_dashboard_rows(
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
    if body.event_type == DashboardTelemetryEvent.RENDERED:
        if body.duration_ms is None or body.chart_id is not None or body.failure_fingerprint is not None:
            raise HTTPException(status_code=422, detail="Invalid dashboard render telemetry")
        dedupe_key = "render:" + hashlib.sha256(
            f"{dashboard_id}:{version.id}:{body.open_instance_id}".encode()
        ).hexdigest()
        metadata = {
            "dashboard_id": dashboard_id,
            "version_id": version.id,
            "open_instance_id": body.open_instance_id,
            "duration_ms": body.duration_ms,
            "chart_count": len(definition.charts),
            "dedupe_key": dedupe_key,
        }
        event = DashboardTelemetryEvent.RENDERED
    else:
        chart = next((item for item in definition.charts if item.id == body.chart_id), None)
        if chart is None or not body.failure_fingerprint or body.duration_ms is not None:
            raise HTTPException(status_code=422, detail="Invalid dashboard tile telemetry")
        dedupe_key = "tile:" + hashlib.sha256(
            (
                f"{dashboard_id}:{version.id}:{body.open_instance_id}:"
                f"{chart.id}:{body.failure_fingerprint}"
            ).encode()
        ).hexdigest()
        metadata = {
            "dashboard_id": dashboard_id,
            "version_id": version.id,
            "open_instance_id": body.open_instance_id,
            "chart_id": chart.id,
            "visualization_type": _visualization_type(chart),
            "failure_code": "render_error",
            "failure_fingerprint": body.failure_fingerprint,
            "dedupe_key": dedupe_key,
        }
        event = DashboardTelemetryEvent.TILE_RENDER_FAILED
    await record_dashboard_event(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        event_type=event,
        connection_name=dashboard.connection_name,
        metadata=metadata,
    )


@router.post(
    "/dashboards/{dashboard_id}/visibility",
    response_model=DashboardDetail,
    dependencies=[RequireScope("write")],
)
async def set_dashboard_visibility(dashboard_id: str, body: DashboardVisibilityRequest, store: StoreD):
    try:
        detail = await dashboard_store.set_dashboard_visibility(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            dashboard_id=dashboard_id,
            visibility=body.visibility,
        )
        await record_dashboard_event(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            event_type=DashboardTelemetryEvent.SHARED,
            connection_name=detail.dashboard.connection_name,
            metadata={
                "dashboard_id": detail.dashboard.id,
                "version_id": detail.version.id,
                "visibility": body.visibility,
            },
        )
        return detail
    except dashboard_store.DashboardNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Dashboard not found") from exc


@router.post(
    "/dashboards/{dashboard_id}/fork",
    response_model=DashboardDetail,
    status_code=201,
    dependencies=[RequireScope("write")],
)
async def fork_dashboard(dashboard_id: str, body: DashboardForkRequest, store: StoreD):
    try:
        detail = await dashboard_store.fork_dashboard(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            dashboard_id=dashboard_id,
            version_id=body.version_id,
        )
        await record_dashboard_event(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            event_type=DashboardTelemetryEvent.FORKED,
            connection_name=detail.dashboard.connection_name,
            metadata={
                "dashboard_id": dashboard_id,
                "version_id": body.version_id,
                "fork_dashboard_id": detail.dashboard.id,
                "fork_version_id": detail.version.id,
            },
        )
        return detail
    except dashboard_store.DashboardNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Dashboard not found") from exc


async def _set_archive(dashboard_id: str, archived: bool, store: StoreD):
    try:
        detail = await dashboard_store.set_dashboard_archived(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            dashboard_id=dashboard_id,
            archived=archived,
        )
        await record_dashboard_event(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            event_type=(DashboardTelemetryEvent.ARCHIVED if archived else DashboardTelemetryEvent.RESTORED),
            connection_name=detail.dashboard.connection_name,
            metadata={
                "dashboard_id": detail.dashboard.id,
                "version_id": detail.version.id,
            },
        )
        return detail
    except dashboard_store.DashboardNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Dashboard not found") from exc


@router.post(
    "/dashboards/{dashboard_id}/archive",
    response_model=DashboardDetail,
    dependencies=[RequireScope("write")],
)
async def archive_dashboard(dashboard_id: str, store: StoreD):
    return await _set_archive(dashboard_id, True, store)


@router.post(
    "/dashboards/{dashboard_id}/restore",
    response_model=DashboardDetail,
    dependencies=[RequireScope("write")],
)
async def restore_dashboard(dashboard_id: str, store: StoreD):
    return await _set_archive(dashboard_id, False, store)


@router.post(
    "/dashboards/{dashboard_id}/versions",
    response_model=DashboardDetail,
    status_code=201,
    dependencies=[RequireScope("write")],
)
async def create_dashboard_version(dashboard_id: str, body: CreateDashboardVersionRequest, store: StoreD):
    await _verified_context(store, body.definition)
    try:
        detail = await dashboard_store.create_dashboard_version(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            dashboard_id=dashboard_id,
            expected_current_version_id=body.expected_current_version_id,
            definition=body.definition,
        )
        await record_dashboard_event(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            event_type=DashboardTelemetryEvent.SAVED,
            connection_name=detail.dashboard.connection_name,
            metadata={
                "dashboard_id": detail.dashboard.id,
                "version_id": detail.version.id,
                "chart_count": len(detail.version.definition.charts),
            },
        )
        return detail
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
        definition = canonicalize_dashboard_filter_targets(definition, verified)
        validate_dashboard_semantics(definition, verified)
        validate_time_series_default_windows(definition, verified)
    except (DashboardCompileError, ValueError) as exc:
        await record_dashboard_event(
            store.session,
            org_id=org_id,
            user_id=user_id,
            event_type=DashboardTelemetryEvent.AGENT_VALIDATION_FAILED,
            connection_name=context.connection_name,
            metadata={
                "dashboard_id": dashboard_id or "draft:new",
                "version_id": base_version_id or "draft:new",
                "failure_code": (
                    "dashboard_time_series_window_required"
                    if getattr(exc, "code", None) == "dashboard_time_series_window_required"
                    else "dashboard_agent_draft_invalid"
                ),
            },
        )
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


@router.get(
    "/dashboard-authoring/sessions/{session_id}",
    response_model=DashboardAuthoringSessionInfo,
    dependencies=[RequireScope("write")],
)
async def get_dashboard_authoring_session(session_id: str, store: StoreD):
    row = await dashboard_store.get_authoring_session(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        session_id=session_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Dashboard authoring conversation not found")
    return dashboard_store.authoring_info(row)


@router.get(
    "/dashboards/{dashboard_id}/active-authoring-session",
    response_model=DashboardAuthoringSessionInfo | None,
    dependencies=[RequireScope("write")],
)
async def get_active_dashboard_authoring_session(dashboard_id: str, store: StoreD):
    rows = await dashboard_store.get_private_dashboard_rows(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        dashboard_id=dashboard_id,
    )
    if rows is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    row = await dashboard_store.get_active_authoring_session(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        dashboard_id=dashboard_id,
    )
    return dashboard_store.authoring_info(row) if row else None


@router.post(
    "/dashboard-authoring/sessions/{session_id}/messages",
    response_model=DashboardAuthoringSessionInfo,
    dependencies=[RequireScope("write")],
)
async def continue_dashboard_authoring_session(session_id: str, body: DashboardAuthoringMessageRequest, store: StoreD):
    org_id = store._require_org_id()
    user_id = _user_id(store)
    row = await dashboard_store.get_authoring_session(
        store.session, org_id=org_id, user_id=user_id, session_id=session_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Dashboard authoring conversation not found")
    if row.status not in {"preview", "applied", "discarded"}:
        raise HTTPException(status_code=409, detail="Dashboard authoring conversation is no longer active")
    resuming_saved_thread = row.status in {"applied", "discarded"}
    if not resuming_saved_thread and row.requires_custom_sql_confirmation and not row.custom_sql_confirmed:
        raise HTTPException(
            status_code=409,
            detail="Confirm or decline the pending custom SQL before refining this draft",
        )
    if resuming_saved_thread:
        if not row.dashboard_id:
            raise HTTPException(status_code=409, detail="Saved authoring thread has no dashboard")
        dashboard_rows = await dashboard_store.get_private_dashboard_rows(
            store.session,
            org_id=org_id,
            user_id=user_id,
            dashboard_id=row.dashboard_id,
        )
        if dashboard_rows is None:
            raise HTTPException(status_code=404, detail="Dashboard not found")
        _, current_version = dashboard_rows
        current_definition = DashboardDefinition.model_validate(current_version.definition_json)
        base_version_id = current_version.id
    else:
        current_definition = DashboardDefinition.model_validate(row.definition_json)
        base_version_id = row.base_version_id
    try:
        context = await _verified_context(store, current_definition)
        api_key = await org_secrets_store.resolve_anthropic_key(store.session, org_id)
        if not api_key:
            raise HTTPException(status_code=409, detail="Dashboard authoring requires the organization Anthropic key")
        agent = DashboardAuthoringAgent(api_key=api_key)
        draft = await agent.draft(prompt=body.prompt, context=context, base_definition=current_definition)
        definition = materialize_agent_draft(draft, base_definition=current_definition)
        verified = await _verified_context(store, definition)
        definition = canonicalize_dashboard_filter_targets(definition, verified)
        validate_dashboard_semantics(definition, verified)
        validate_time_series_default_windows(definition, verified)
    except HTTPException:
        raise
    except (DashboardCompileError, ValueError) as exc:
        await dashboard_store.record_authoring_failure(
            store.session,
            org_id=org_id,
            user_id=user_id,
            session_id=session_id,
            prompt=body.prompt,
            safe_message=f"That change could not be validated: {exc}",
        )
        await record_dashboard_event(
            store.session,
            org_id=org_id,
            user_id=user_id,
            event_type=DashboardTelemetryEvent.AGENT_VALIDATION_FAILED,
            connection_name=current_definition.signalPilot.connectionName,
            metadata={
                "dashboard_id": row.dashboard_id or f"draft:{row.id}",
                "version_id": base_version_id or f"draft:{row.id}",
                "failure_code": (
                    "dashboard_time_series_window_required"
                    if getattr(exc, "code", None) == "dashboard_time_series_window_required"
                    else "dashboard_agent_draft_invalid"
                ),
            },
        )
        raise HTTPException(status_code=422, detail=f"Agent draft rejected: {exc}") from exc
    previous_sql = {
        chart.id: chart.model_dump(mode="json") for chart in current_definition.charts if chart.query.kind == "sql"
    }
    changed_custom_sql_chart_ids = [
        chart.id
        for chart in definition.charts
        if chart.query.kind == "sql" and previous_sql.get(chart.id) != chart.model_dump(mode="json")
    ]
    authoring_kwargs = {
        "db": store.session,
        "org_id": org_id,
        "user_id": user_id,
        "definition": definition,
        "operations": [operation.model_dump(mode="json") for operation in draft.operations],
        "prompt": body.prompt,
        "summary": draft.summary,
        "agent_run_id": str(uuid.uuid4()),
        "model": agent.model,
        "requires_custom_sql_confirmation": bool(changed_custom_sql_chart_ids),
    }
    if resuming_saved_thread:
        return await dashboard_store.create_authoring_session(
            **authoring_kwargs,
            dashboard_id=row.dashboard_id,
            base_version_id=base_version_id,
            custom_sql_confirmed=False,
            thread_id=row.thread_id,
            prior_events=list(row.events_json or []),
            pending_custom_sql_chart_ids=changed_custom_sql_chart_ids,
        )
    return await dashboard_store.update_authoring_session_draft(
        **authoring_kwargs,
        session_id=session_id,
        pending_custom_sql_chart_ids=changed_custom_sql_chart_ids,
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
    "/dashboard-authoring/sessions/{session_id}/decline-custom-sql",
    response_model=DashboardAuthoringSessionInfo,
    dependencies=[RequireScope("write")],
)
async def decline_dashboard_authoring_custom_sql(session_id: str, store: StoreD):
    try:
        return await dashboard_store.decline_authoring_custom_sql(
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
    "/dashboard-authoring/sessions/{session_id}/discard",
    response_model=DashboardAuthoringSessionInfo,
    dependencies=[RequireScope("write")],
)
async def discard_dashboard_authoring_session(session_id: str, store: StoreD):
    try:
        return await dashboard_store.discard_authoring_session(
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
async def apply_dashboard_authoring_session(session_id: str, body: DashboardAuthoringApplyRequest, store: StoreD):
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
        validate_time_series_default_windows(definition, context)
        detail = await dashboard_store.apply_authoring_session(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            session_id=session_id,
            expected_current_version_id=body.expected_current_version_id,
            visible_complete_result_ids=body.visible_complete_result_ids,
        )
        await record_dashboard_event(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            event_type=DashboardTelemetryEvent.SAVED,
            connection_name=detail.dashboard.connection_name,
            metadata={
                "dashboard_id": detail.dashboard.id,
                "version_id": detail.version.id,
                "chart_count": len(detail.version.definition.charts),
                "authoring_session_id": session_id,
            },
        )
        return detail
    except dashboard_store.DashboardNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Dashboard authoring preview not found") from exc
    except dashboard_store.DashboardConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "stale_dashboard_version", "actual_current_version_id": exc.actual_current_version_id},
        ) from exc
    except (DashboardCompileError, dashboard_store.DashboardValidationError) as exc:
        await record_dashboard_event(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            event_type=DashboardTelemetryEvent.AGENT_VALIDATION_FAILED,
            connection_name=definition.signalPilot.connectionName,
            metadata={
                "dashboard_id": row.dashboard_id or f"draft:{row.id}",
                "version_id": row.base_version_id or f"draft:{row.id}",
                "failure_code": (
                    "dashboard_time_series_window_required"
                    if getattr(exc, "code", None) == "dashboard_time_series_window_required"
                    else "dashboard_apply_receipt_invalid"
                ),
            },
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _record_dashboard_failure(
    store: StoreD,
    *,
    dashboard_id: str,
    version_id: str,
    chart_id: str,
    failure: DashboardFailure,
    cached_result_time: datetime | None,
) -> None:
    cached_age_seconds = None
    if cached_result_time is not None:
        result_time = cached_result_time.replace(tzinfo=cached_result_time.tzinfo or UTC)
        cached_age_seconds = max(0, int((datetime.now(UTC) - result_time).total_seconds()))
    cache_state = "cached_after_refresh_failure" if failure.cache_fallback_available else "no_usable_cache"
    await record_dashboard_event(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        event_type=DashboardTelemetryEvent.QUERY_FAILURE,
        connection_name=failure.connection_name,
        metadata={
            "dashboard_id": dashboard_id,
            "version_id": version_id,
            "chart_id": chart_id,
            "failure_code": failure.code,
            "incident_scope": failure.scope,
            "retryable": failure.retryable,
            "correlation_id": failure.correlation_id,
            "cache_state": cache_state,
        },
    )
    await record_dashboard_event(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        event_type=DashboardTelemetryEvent.RETRY_OUTCOME,
        connection_name=failure.connection_name,
        metadata={
            "dashboard_id": dashboard_id,
            "version_id": version_id,
            "outcome": "failed",
            "failure_code": failure.code,
            "correlation_id": failure.correlation_id,
            "dedupe_key": f"retry:{failure.correlation_id}:failed",
        },
    )
    if failure.cache_fallback_available:
        await record_dashboard_event(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            event_type=DashboardTelemetryEvent.DEGRADED_FALLBACK,
            connection_name=failure.connection_name,
            metadata={
                "dashboard_id": dashboard_id,
                "version_id": version_id,
                "chart_id": chart_id,
                "failure_code": failure.code,
                "cache_state": cache_state,
                "cached_age_seconds": cached_age_seconds,
                "correlation_id": failure.correlation_id,
                "dedupe_key": f"fallback:{chart_id}:{failure.correlation_id}",
            },
        )


async def _record_dashboard_recovery(
    store: StoreD,
    *,
    dashboard_id: str,
    version_id: str,
    connection_name: str,
    correlation_id: str,
) -> None:
    await record_dashboard_event(
        store.session,
        org_id=store._require_org_id(),
        user_id=_user_id(store),
        event_type=DashboardTelemetryEvent.RETRY_OUTCOME,
        connection_name=connection_name,
        metadata={
            "dashboard_id": dashboard_id,
            "version_id": version_id,
            "outcome": "recovered",
            "correlation_id": correlation_id,
            "dedupe_key": f"retry:{correlation_id}:recovered",
        },
    )


async def _cached_receipt(
    store: StoreD,
    *,
    dashboard_id: str,
    version_id: str,
    chart_id: str,
    cache_key: str,
):
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
                GatewayDashboardResult.chart_id == chart_id,
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
        else "stale_refreshing",
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


def _reject_truncated_time_series(chart, completeness: str) -> None:
    visualization = chart.visualization
    if (
        completeness == "truncated"
        and visualization.type == "cartesian"
        and visualization.config.seriesType in {"line", "area"}
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "dashboard_time_series_truncated",
                "message": (
                    f"{chart.title} exceeds its {chart.query.limit:,}-row limit. "
                    "Narrow the date range or publish a dashboard version with a higher limit."
                ),
            },
        )


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
    query_started = time.monotonic()
    chart = next((item for item in parsed.charts if item.id == chart_id), None)
    if chart is None:
        raise HTTPException(status_code=404, detail="Chart not found")
    if chart.query.kind == "sql" and not custom_sql_confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "custom_sql_confirmation_required",
                "message": "Confirm custom SQL before preview execution",
            },
        )
    tile = _tile_for_chart(parsed, chart_id, body.tile_uuid)
    requested_filters = body.dashboard_filters
    if requested_filters is None:
        requested_filters = [
            rule for rule in parsed.filters.dimensions if rule.values or rule.operator in {"isNull", "notNull"}
        ]
    runtime_filters = _runtime_filters_for_tile(parsed, tile.uuid, chart, requested_filters)
    drill_dimensions, drill_filters = _drill_query_state(chart, body.drill_path)
    cache_key = dashboard_query_cache_key(
        version_id=query_version_id,
        chart=chart,
        tile_uuid=tile.uuid,
        requested_filters=requested_filters,
        drill_path=body.drill_path,
        dashboard_filters=parsed.filters,
    )
    cached = await _cached_receipt(
        store,
        dashboard_id=dashboard.id,
        version_id=query_version_id,
        chart_id=chart.id,
        cache_key=cache_key,
    )
    if not body.refresh:
        if cached is not None:
            _reject_truncated_time_series(chart, cached.completeness)
            await record_dashboard_event(
                store.session,
                org_id=store._require_org_id(),
                user_id=_user_id(store),
                event_type=DashboardTelemetryEvent.CACHE_HIT,
                connection_name=dashboard.connection_name,
                metadata={
                    "dashboard_id": dashboard.id,
                    "version_id": query_version_id,
                    "chart_id": chart.id,
                    "visualization_type": _visualization_type(chart),
                    "cache_state": cached.cache_state,
                },
            )
            await record_dashboard_event(
                store.session,
                org_id=store._require_org_id(),
                user_id=_user_id(store),
                event_type=DashboardTelemetryEvent.QUERY_COMPLETED,
                connection_name=dashboard.connection_name,
                metadata={
                    "dashboard_id": dashboard.id,
                    "version_id": query_version_id,
                    "chart_id": chart.id,
                    "visualization_type": _visualization_type(chart),
                    "duration_ms": (time.monotonic() - query_started) * 1000,
                    "row_count": cached.row_count,
                    "completeness": cached.completeness,
                    "cache_state": cached.cache_state,
                    "execution_id": cached.execution_id,
                },
            )
            return cached
    if cached is None:
        await record_dashboard_event(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            event_type=DashboardTelemetryEvent.CACHE_MISS,
            connection_name=dashboard.connection_name,
            metadata={
                "dashboard_id": dashboard.id,
                "version_id": query_version_id,
                "chart_id": chart.id,
                "visualization_type": _visualization_type(chart),
                "cache_state": "cache_miss",
            },
        )

    async def _run_live_query() -> DashboardQueryReceipt:
        try:
            context = await _verified_context(store, parsed)
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
            parameter_hash = hashlib.sha256(
                json.dumps(compiled.parameters, sort_keys=True, separators=(",", ":"), default=str).encode()
            ).hexdigest()
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
            _reject_truncated_time_series(chart, result.completeness)
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
            output_metadata = {str(column["name"]): column for column in compiled.output_columns}
            result_columns = [
                {**output_metadata.get(str(column.get("name")), {}), **column} for column in result_columns
            ]
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
                cache_state="fresh",
            )
        except asyncio.CancelledError:
            raise
        except _DashboardFailureRaised:
            raise
        except Exception as exc:
            raise _DashboardFailureRaised(_dashboard_failure(exc, connection_name=dashboard.connection_name)) from exc

    try:
        live, recovered = await dashboard_connection_retry_gate.run(
            org_id=store._require_org_id(),
            connection_name=dashboard.connection_name,
            retry_token=body.retry_token,
            operation=_run_live_query,
        )
        if recovered and body.retry_token:
            await _record_dashboard_recovery(
                store,
                dashboard_id=dashboard.id,
                version_id=query_version_id,
                connection_name=dashboard.connection_name,
                correlation_id=body.retry_token,
            )
        await record_dashboard_event(
            store.session,
            org_id=store._require_org_id(),
            user_id=_user_id(store),
            event_type=DashboardTelemetryEvent.QUERY_COMPLETED,
            connection_name=dashboard.connection_name,
            metadata={
                "dashboard_id": dashboard.id,
                "version_id": query_version_id,
                "chart_id": chart.id,
                "visualization_type": _visualization_type(chart),
                "duration_ms": (time.monotonic() - query_started) * 1000,
                "row_count": live.row_count,
                "completeness": live.completeness,
                "cache_state": live.cache_state,
                "execution_id": live.execution_id,
                "correlation_id": body.retry_token,
            },
        )
        return live
    except _DashboardFailureRaised as exc:
        failure = exc.failure.model_copy(update={"cache_fallback_available": cached is not None})
        await _record_dashboard_failure(
            store,
            dashboard_id=dashboard.id,
            version_id=query_version_id,
            chart_id=chart.id,
            failure=failure,
            cached_result_time=cached.result_time if cached else None,
        )
        if cached is not None:
            cache_state = (
                "cached_source_unavailable" if failure.scope == "connection" else "cached_after_refresh_failure"
            )
            return cached.model_copy(update={"cache_state": cache_state, "refresh_failure": failure})
        failure = failure.model_copy(update={"cache_state": "no_usable_cache"})
        status_code = {
            "permission_denied": 403,
            "rate_limited": 429,
            "stale_dashboard_version": 409,
            "query_timeout": 504,
            "data_source_unavailable": 503,
            "authentication_rejected": 503,
            "query_invalid": 422,
            "semantic_definition_invalid": 422,
            "result_contract_mismatch": 502,
            "cancelled": 409,
            "internal_error": 500,
        }[failure.code]
        raise HTTPException(
            status_code=status_code,
            detail=failure.model_dump(mode="json", exclude_none=True),
        ) from exc


@router.post(
    "/dashboards/{dashboard_id}/charts/{chart_id}/query",
    response_model=DashboardQueryReceipt,
    dependencies=[RequireScope("query")],
)
async def query_dashboard_chart(dashboard_id: str, chart_id: str, body: DashboardQueryRequest, store: StoreD):
    rows = await dashboard_store.get_dashboard_rows(
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
    rows = await dashboard_store.get_dashboard_rows(
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
    authorized = await dashboard_store.get_dashboard_rows(
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
        cache_state="fresh" if expires_at > datetime.now(UTC) else "stale_refreshing",
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
    rows = await dashboard_store.get_dashboard_rows(
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
    readiness = await evaluate_project_readiness(store.session, org_id=org_id, user_id=user_id, project=project)
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
    await record_dashboard_event(
        store.session,
        org_id=org_id,
        user_id=user_id,
        event_type=DashboardTelemetryEvent.ANALYSIS_STARTED,
        connection_name=dashboard.connection_name,
        metadata={
            "dashboard_id": dashboard_id,
            "version_id": version.id,
            "chart_id": chart.id,
            "conversation_id": conversation.id,
        },
    )
    return DashboardAnalyzeResponse(conversation_id=conversation.id, chart_reference=chart_reference)


@router.get(
    "/dashboards/{dashboard_id}/suggestions",
    response_model=list[DashboardSuggestion],
    dependencies=[RequireScope("read")],
)
async def suggest_organization_dashboards(dashboard_id: str, store: StoreD):
    org_id = store._require_org_id()
    rows = await dashboard_store.get_dashboard_rows(
        store.session, org_id=org_id, user_id=_user_id(store), dashboard_id=dashboard_id
    )
    if rows is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    _, target_version = rows
    target = DashboardDefinition.model_validate(target_version.definition_json)
    signatures = {
        semantic_query_signature(chart.query) for chart in target.charts if isinstance(chart.query, SemanticChartQuery)
    }
    if not signatures:
        return []
    candidates = (
        await store.session.execute(
            select(GatewayDashboard, GatewayDashboardVersion)
            .join(GatewayDashboardVersion, GatewayDashboardVersion.id == GatewayDashboard.current_version_id)
            .where(
                GatewayDashboard.org_id == org_id,
                GatewayDashboard.id != dashboard_id,
                GatewayDashboard.visibility == "organization",
                GatewayDashboard.archived_at.is_(None),
            )
        )
    ).all()
    suggestions: list[DashboardSuggestion] = []
    for dashboard, version in candidates:
        definition = DashboardDefinition.model_validate(version.definition_json)
        for chart in definition.charts:
            if (
                not isinstance(chart.query, SemanticChartQuery)
                or semantic_query_signature(chart.query) not in signatures
            ):
                continue
            freshness = (
                await store.session.execute(
                    select(GatewayDashboardResult.freshness_at)
                    .where(
                        GatewayDashboardResult.org_id == org_id,
                        GatewayDashboardResult.dashboard_id == dashboard.id,
                        GatewayDashboardResult.version_id == version.id,
                        GatewayDashboardResult.chart_id == chart.id,
                    )
                    .order_by(GatewayDashboardResult.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            suggestions.append(
                DashboardSuggestion(
                    dashboard_id=dashboard.id,
                    dashboard_name=dashboard.name,
                    version_id=version.id,
                    chart_id=chart.id,
                    chart_title=chart.title,
                    owner_user_id=dashboard.owner_user_id,
                    freshness_at=freshness,
                )
            )
    return suggestions


@router.post(
    "/dashboards/{dashboard_id}/exports/html",
    response_model=DashboardExportGrant,
    dependencies=[RequireScope("read")],
)
async def authorize_dashboard_html_export(dashboard_id: str, body: DashboardExportRequest, store: StoreD):
    org_id = store._require_org_id()
    rows = await dashboard_store.get_dashboard_rows(
        store.session,
        org_id=org_id,
        user_id=_user_id(store),
        dashboard_id=dashboard_id,
        version_id=body.version_id,
    )
    if rows is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    if not body.acknowledge_sensitive_data:
        raise HTTPException(
            status_code=422,
            detail="Confirm that the offline HTML contains the currently visible governed data",
        )
    result_ids = list(dict.fromkeys(body.dashboard_result_ids))
    authorized = list(
        (
            await store.session.execute(
                select(GatewayDashboardResult.id).where(
                    GatewayDashboardResult.id.in_(result_ids),
                    GatewayDashboardResult.org_id == org_id,
                    GatewayDashboardResult.dashboard_id == dashboard_id,
                    GatewayDashboardResult.version_id == body.version_id,
                )
            )
        ).scalars()
    )
    if len(authorized) != len(result_ids):
        raise HTTPException(status_code=404, detail="One or more dashboard results are not exportable")
    await record_dashboard_event(
        store.session,
        org_id=org_id,
        user_id=_user_id(store),
        event_type=DashboardTelemetryEvent.EXPORTED,
        connection_name=rows[0].connection_name,
        metadata={
            "dashboard_id": dashboard_id,
            "version_id": body.version_id,
            "result_count": len(authorized),
            "format": "html",
        },
    )
    return DashboardExportGrant(
        dashboard_id=dashboard_id,
        version_id=body.version_id,
        authorized_result_ids=authorized,
        warning="This offline file contains governed result data. Store and share it appropriately.",
    )
