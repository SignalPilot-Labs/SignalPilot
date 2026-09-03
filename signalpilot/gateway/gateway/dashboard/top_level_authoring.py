"""Model-free services for run-scoped, skill-driven dashboard authoring."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.dashboard import store as dashboard_store
from gateway.dashboard.authoring import compact_semantic_projection
from gateway.dashboard.domain import ChartDefinition, DashboardDefinition
from gateway.dashboard.operations import (
    apply_dashboard_operations,
    canonicalize_dashboard_filter_targets,
    canonicalize_dashboard_time_series_defaults,
    has_custom_sql,
    validate_dashboard_semantics,
    validate_time_series_default_windows,
)
from gateway.dashboard.progressive_authoring import (
    assemble_dashboard_definition,
    validate_chart_for_intent,
    validate_dashboard_plan,
)
from gateway.db.models import GatewayDashboardAuthoringSession
from gateway.models.dashboards import (
    DASHBOARD_AUTHORING_CONTRACT_VERSION,
    DashboardAuthoringSessionInfo,
    DashboardAuthoringToolResult,
    DashboardAuthoringValidationIssue,
    DashboardChartIntent,
    DashboardPlan,
    DashboardSemanticContext,
)


class AuthoringContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _payload_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _last_run_matches(
    session: GatewayDashboardAuthoringSession,
    *,
    phase: str,
    payload_hash: str,
) -> bool:
    runs = list(session.agent_runs_json or [])
    return bool(runs and runs[-1].get("phase") == phase and runs[-1].get("payload_hash") == payload_hash)


def require_contract(version: str) -> None:
    if version != DASHBOARD_AUTHORING_CONTRACT_VERSION:
        raise AuthoringContractError(
            "authoring_contract_version_mismatch",
            f"Dashboard authoring requires contract {DASHBOARD_AUTHORING_CONTRACT_VERSION}",
        )


def _counts(session: DashboardAuthoringSessionInfo) -> tuple[int, int, int]:
    required = {draft.chart_id for draft in session.chart_drafts if draft.intent.required}
    ready = {draft.chart_id for draft in session.chart_drafts if draft.status == "ready"}
    failed = {draft.chart_id for draft in session.chart_drafts if draft.status == "failed"}
    return len(required), len(required & ready), len(required & failed)


def tool_result(
    session: DashboardAuthoringSessionInfo,
    *,
    status: str | None = None,
    chart_id: str | None = None,
    changed_ids: list[str] | None = None,
    issues: list[DashboardAuthoringValidationIssue] | None = None,
    semantic_context: dict[str, Any] | None = None,
    include_session: bool = False,
) -> DashboardAuthoringToolResult:
    expected, ready, failed = _counts(session)
    return DashboardAuthoringToolResult(
        status=status or session.status,
        authoring_session_id=session.id,
        plan_revision=session.plan_revision,
        draft_revision=session.draft_revision,
        expected_count=expected,
        ready_count=ready,
        failed_count=failed,
        chart_id=chart_id,
        changed_ids=changed_ids or [],
        validation_issues=issues or [],
        semantic_context=semantic_context,
        session=session if include_session else None,
    )


def begin_result(
    session: DashboardAuthoringSessionInfo,
    context: DashboardSemanticContext,
) -> DashboardAuthoringToolResult:
    projection = compact_semantic_projection(context)
    projection["authoring_limits"] = {
        "max_parallel_charts": 5,
        "max_chart_attempts": 2,
        "max_charts": 30,
        "supported_visualizations": ["kpi", "table", "bar", "line", "area"],
        "custom_sql_requires_confirmation": True,
    }
    projection["stable_ids"] = {
        "charts": [chart.id for chart in session.definition.charts] if session.definition else [],
        "tiles": [tile.uuid for tile in session.definition.tiles] if session.definition else [],
        "filters": [rule.id for rule in session.definition.filters.dimensions] if session.definition else [],
    }
    projection["current_plan"] = (
        session.plan.model_dump(mode="json", by_alias=True, exclude_none=True) if session.plan else None
    )
    return tool_result(session, semantic_context=projection, include_session=True)


def _allowed_alternatives(
    message: str,
    *,
    context: DashboardSemanticContext,
    intent: DashboardChartIntent | None = None,
) -> list[str]:
    explore = next(
        (item for item in context.explores if intent and item.name == intent.explore_name),
        None,
    )
    if "metric" in message.lower() and explore:
        return [metric.field_id for metric in explore.metrics[:20]]
    if "dimension" in message.lower() and explore:
        return [field.field_id for field in explore.dimensions[:20]]
    if "explore" in message.lower():
        return [item.name for item in context.explores[:20]]
    return []


def validation_issue(
    exc: BaseException,
    *,
    context: DashboardSemanticContext,
    intent: DashboardChartIntent | None = None,
) -> DashboardAuthoringValidationIssue:
    message = str(exc)[:1000] or "Dashboard payload failed governed validation"
    lowered = message.lower()
    code = (
        "unknown_semantic_field"
        if "unknown" in lowered and ("field" in lowered or "metric" in lowered or "dimension" in lowered)
        else "dashboard_time_window_required"
        if "bounded date filter" in lowered or "time-series" in lowered
        else "dashboard_payload_invalid"
    )
    return DashboardAuthoringValidationIssue(
        code=code,
        path=f"charts.{intent.chart_id}" if intent else "plan",
        message=message,
        allowed_alternatives=_allowed_alternatives(message, context=context, intent=intent),
    )


async def accept_plan(
    db: AsyncSession,
    *,
    session: GatewayDashboardAuthoringSession,
    context: DashboardSemanticContext,
    plan: DashboardPlan,
    expected_plan_revision: int,
    tool_call_id: str | None,
) -> DashboardAuthoringToolResult:
    validate_dashboard_plan(plan, context)
    plan_payload = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    payload_hash = _payload_hash(plan_payload)
    if session.plan_json == plan_payload and _last_run_matches(
        session,
        phase="plan",
        payload_hash=payload_hash,
    ):
        return tool_result(dashboard_store.authoring_info(session))
    if session.plan_revision != expected_plan_revision:
        raise AuthoringContractError("stale_plan_revision", "Dashboard plan revision is stale")
    if session.status != "planning":
        raise AuthoringContractError("dashboard_plan_frozen", "Dashboard plan can no longer be replaced")
    updated = await dashboard_store.accept_top_level_dashboard_plan(
        db,
        session=session,
        plan=plan,
        expected_plan_revision=expected_plan_revision,
        tool_call_id=tool_call_id,
        payload_hash=payload_hash,
    )
    return tool_result(updated)


async def accept_chart(
    db: AsyncSession,
    *,
    session: GatewayDashboardAuthoringSession,
    context: DashboardSemanticContext,
    plan_revision: int,
    chart_id: str,
    chart: ChartDefinition,
    tool_call_id: str | None,
) -> DashboardAuthoringToolResult:
    if session.plan_revision != plan_revision or not session.plan_json:
        raise AuthoringContractError("stale_plan_revision", "Dashboard plan revision is stale")
    plan = DashboardPlan.model_validate(session.plan_json)
    intent = next((item for item in plan.intents if item.chart_id == chart_id), None)
    if intent is None:
        raise AuthoringContractError("unknown_chart_intent", "Dashboard chart intent not found")
    draft = next((item for item in session.chart_drafts if item.chart_id == chart_id), None)
    if draft is None:
        raise AuthoringContractError("unknown_chart_intent", "Dashboard chart intent not found")
    payload_hash = dashboard_store.top_level_chart_payload_hash(chart)
    if draft.payload_hash != payload_hash and draft.attempt_count >= 2:
        raise AuthoringContractError("chart_repair_limit_reached", "Dashboard chart repair limit reached")
    if draft.status == "ready" and draft.payload_hash != payload_hash:
        raise AuthoringContractError("validated_chart_frozen", "A validated chart cannot be replaced in the same plan")
    try:
        validate_chart_for_intent(
            chart,
            intent=intent,
            plan=plan,
            context=context,
            timezone=plan.timezone,
        )
    except ValueError as exc:
        issue = validation_issue(exc, context=context, intent=intent)
        updated = await dashboard_store.record_top_level_dashboard_chart(
            db,
            session=session,
            chart_id=chart_id,
            chart=chart,
            status="failed",
            validation_outcome={
                "message": issue.message,
                "issues": [issue.model_dump(mode="json")],
            },
            tool_call_id=tool_call_id,
        )
        return tool_result(updated, status="rejected", chart_id=chart_id, issues=[issue])
    ready_charts = [
        ChartDefinition.model_validate(draft.definition_json)
        for draft in session.chart_drafts
        if draft.status == "ready" and draft.definition_json and draft.chart_id != chart_id
    ]
    ready_charts.append(chart)
    partial = assemble_dashboard_definition(
        plan=plan,
        charts=ready_charts,
        context=context,
        timezone=plan.timezone,
    )
    updated = await dashboard_store.record_top_level_dashboard_chart(
        db,
        session=session,
        chart_id=chart_id,
        chart=chart,
        status="ready",
        validation_outcome={"accepted": True},
        tool_call_id=tool_call_id,
        partial_definition=partial,
    )
    return tool_result(updated, status="ready", chart_id=chart_id)


async def apply_operations(
    db: AsyncSession,
    *,
    session: GatewayDashboardAuthoringSession,
    context: DashboardSemanticContext,
    expected_draft_revision: int,
    operations: list[dict[str, Any]],
    tool_call_id: str | None,
) -> DashboardAuthoringToolResult:
    payload_hash = _payload_hash(
        {
            "expected_draft_revision": expected_draft_revision,
            "operations": operations,
        }
    )
    if _last_run_matches(session, phase="operations", payload_hash=payload_hash):
        return tool_result(
            dashboard_store.authoring_info(session),
            changed_ids=_changed_ids(operations),
        )
    if session.draft_revision != expected_draft_revision:
        raise AuthoringContractError("stale_draft_revision", "Dashboard draft revision is stale")
    if session.definition_json is None:
        raise AuthoringContractError("dashboard_draft_incomplete", "Dashboard has no validated draft to refine")
    current = DashboardDefinition.model_validate(session.definition_json)
    candidate = apply_dashboard_operations(current, operations)
    candidate = canonicalize_dashboard_filter_targets(candidate, context)
    candidate = canonicalize_dashboard_time_series_defaults(candidate, context)
    validate_dashboard_semantics(candidate, context)
    validate_time_series_default_windows(candidate, context)
    current_sql = {chart.id: chart.model_dump(mode="json") for chart in current.charts if chart.query.kind == "sql"}
    changed_sql = [
        chart.id
        for chart in candidate.charts
        if chart.query.kind == "sql" and current_sql.get(chart.id) != chart.model_dump(mode="json")
    ]
    now = datetime.now(UTC)
    session.definition_json = candidate.model_dump(mode="json", by_alias=True, exclude_none=True)
    session.operations_json = [*(session.operations_json or []), *operations]
    session.draft_revision += 1
    session.status = "building"
    session.requires_custom_sql_confirmation = bool(changed_sql)
    session.custom_sql_confirmed = False if changed_sql else session.custom_sql_confirmed
    session.pending_custom_sql_chart_ids_json = changed_sql
    session.updated_at = now
    session.agent_runs_json = [
        *(session.agent_runs_json or []),
        {
            "id": tool_call_id or str(uuid.uuid4()),
            "phase": "operations",
            "payload_hash": payload_hash,
            "changed_ids": _changed_ids(operations),
            "created_at": now.isoformat(),
        },
    ]
    await db.commit()
    await db.refresh(session, ["chart_drafts"])
    updated = dashboard_store.authoring_info(session)
    return tool_result(updated, changed_ids=_changed_ids(operations))


def _changed_ids(operations: list[dict[str, Any]]) -> list[str]:
    keys = ("chart_id", "tile_uuid")
    return list(dict.fromkeys(str(operation[key]) for operation in operations for key in keys if operation.get(key)))


async def finalize_preview(
    db: AsyncSession,
    *,
    session: GatewayDashboardAuthoringSession,
    context: DashboardSemanticContext,
    plan_revision: int,
    expected_draft_revision: int,
    tool_call_id: str | None,
) -> DashboardAuthoringToolResult:
    payload_hash = _payload_hash(
        {
            "plan_revision": plan_revision,
            "expected_draft_revision": expected_draft_revision,
        }
    )
    if session.status == "preview" and _last_run_matches(
        session,
        phase="finalize",
        payload_hash=payload_hash,
    ):
        return tool_result(
            dashboard_store.authoring_info(session),
            status="preview_ready",
            include_session=True,
        )
    if session.plan_revision != plan_revision:
        raise AuthoringContractError("stale_plan_revision", "Dashboard plan revision is stale")
    if session.draft_revision != expected_draft_revision:
        raise AuthoringContractError("stale_draft_revision", "Dashboard draft revision is stale")
    if session.plan_json:
        plan = DashboardPlan.model_validate(session.plan_json)
        required_ids = {intent.chart_id for intent in plan.intents if intent.required}
        ready_charts = [
            ChartDefinition.model_validate(draft.definition_json)
            for draft in session.chart_drafts
            if draft.status == "ready" and draft.definition_json
        ]
        ready_ids = {chart.id for chart in ready_charts}
        if required_ids - ready_ids:
            raise AuthoringContractError(
                "required_charts_incomplete",
                "Every required dashboard chart must validate before finalization",
            )
        definition = assemble_dashboard_definition(
            plan=plan,
            charts=ready_charts,
            context=context,
            timezone=plan.timezone,
            deterministic_fallback=True,
        )
    elif session.definition_json:
        definition = DashboardDefinition.model_validate(session.definition_json)
    else:
        raise AuthoringContractError("dashboard_draft_incomplete", "Dashboard draft is incomplete")
    validate_dashboard_semantics(definition, context)
    validate_time_series_default_windows(definition, context)
    custom_sql = has_custom_sql(definition)
    session.requires_custom_sql_confirmation = custom_sql and not session.custom_sql_confirmed
    if session.requires_custom_sql_confirmation:
        session.pending_custom_sql_chart_ids_json = [
            chart.id for chart in definition.charts if chart.query.kind == "sql"
        ]
    updated = await dashboard_store.finalize_progressive_authoring_session(
        db,
        org_id=session.org_id,
        user_id=session.owner_user_id,
        session_id=session.id,
        definition=definition,
        status="preview",
        summary=f"Preview ready with {len(definition.charts)} charts.",
        phase="ready",
        run_provenance={
            "id": tool_call_id or str(uuid.uuid4()),
            "phase": "finalize",
            "payload_hash": payload_hash,
            "plan_revision": session.plan_revision,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    return tool_result(updated, status="preview_ready", include_session=True)
