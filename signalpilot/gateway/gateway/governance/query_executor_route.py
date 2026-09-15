"""Route decisions for the governed query executor: validation, plans, reuse, size limits."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from gateway.billing.emitters.queries import emit_query_credit
from gateway.connectors.registry import get_connector_dialect
from gateway.db.models import GatewayGovernedQueryExecution, GatewayStructuredQueryResult
from gateway.engine import sqlglot_dialect, validate_sql
from gateway.governance.annotations import load_annotations
from gateway.governance.bindings import BoundQuery, BoundQueryError
from gateway.governance.pii import PIIRedactor
from gateway.governance.query_executor_persist import (
    _actual_scan_bytes,
    _json_safe,
    _stored_result_rows,
    actual_cost_usd,
)
from gateway.governance.query_executor_types import (
    GovernedQueryContext,
    GovernedQueryError,
    GovernedQueryResult,
    normalize_sql,
)
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.standalone_chat.query_approvals import reconcile_reservation
from gateway.store import Store
from gateway.store import standalone_chat as chat_store


@dataclass
class PreparedQuery:
    """Validated, bound, and hashed query ready for routing."""

    info: Any
    annotations: Any
    bound_query: BoundQuery
    governance_sql: str
    parameter_sentinels: Any
    rendered_sql: str
    dialect: str | None
    tables: list[str]
    normalized_sql: str
    sql_hash: str


async def prepare_query(
    store: Store,
    *,
    org_id: str,
    connection_name: str,
    sql: str,
    parameters: list[Any] | None,
    bound_query: BoundQuery | None,
) -> PreparedQuery:
    info = await store.get_connection(connection_name)
    if info is None:
        raise GovernedQueryError("connection_not_found", "Connection not found")

    settings = await store.load_settings()
    annotations = load_annotations(org_id, connection_name)
    blocked_tables = list(annotations.blocked_tables)
    if settings.blocked_tables:
        blocked_tables.extend(table for table in settings.blocked_tables if table not in blocked_tables)

    try:
        connector_dialect = get_connector_dialect(info.db_type)
        connection_db_type = str(getattr(info.db_type, "value", info.db_type)).lower()
        if bound_query is None:
            bound_query = BoundQuery.from_legacy(
                sql=sql,
                parameters=list(parameters or []),
                db_type=connection_db_type,
                parameter_style=connector_dialect.parameter_style,
            )
        elif bound_query.db_type != connection_db_type:
            raise BoundQueryError("Bound query database type does not match the connection")
        rendered_query = bound_query.render()
        governance_sql, parameter_sentinels = bound_query.governance_sql()
    except (BoundQueryError, ValueError) as exc:
        raise GovernedQueryError("invalid_parameters", str(exc)) from exc
    dialect = sqlglot_dialect(info.db_type)
    validation = validate_sql(governance_sql, blocked_tables=blocked_tables or None, dialect=dialect)
    if not validation.ok:
        raise GovernedQueryError("query_blocked", validation.blocked_reason or "Query blocked")

    normalized_sql = normalize_sql(governance_sql, dialect)
    sql_hash = hashlib.sha256(normalized_sql.encode()).hexdigest()
    return PreparedQuery(
        info=info,
        annotations=annotations,
        bound_query=bound_query,
        governance_sql=governance_sql,
        parameter_sentinels=parameter_sentinels,
        rendered_sql=rendered_query.sql,
        dialect=dialect,
        tables=validation.tables,
        normalized_sql=normalized_sql,
        sql_hash=sql_hash,
    )


async def resolve_plan(
    store: Store,
    *,
    org_id: str,
    context: GovernedQueryContext,
    connection_name: str,
    prepared: PreparedQuery,
    row_limit: int,
) -> tuple[Any, int, GovernedQueryResult | None]:
    """Require a persisted plan for chat runs and reuse a prior completed result.

    Returns ``(persisted_plan, row_limit, reused_result)``.
    """
    persisted_plan = None
    if not (context.run_id and (context.plan_id or enterprise_chat_feature_flags().size_router)):
        return persisted_plan, row_limit, None
    if not context.plan_id:
        raise GovernedQueryError("plan_required", "Chat query execution requires a valid plan_id")
    from gateway.governance.query_planner import QueryPlanError, require_execution_plan

    try:
        persisted_plan = await require_execution_plan(
            store,
            plan_id=context.plan_id,
            sql=prepared.rendered_sql,
            connection_name=connection_name,
            context=context,
            allowed_routes={"mcp"} if context.path == "mcp" else {"notebook_sdk"},
        )
    except QueryPlanError as exc:
        raise GovernedQueryError(exc.code, str(exc)) from exc
    if persisted_plan.scout_row_limit:
        row_limit = persisted_plan.scout_row_limit
    elif context.path == "mcp":
        row_limit = 10_000
    else:
        row_limit = 100_000
    persisted_plan.used_at = datetime.now(UTC)
    prior = (
        await store.session.execute(
            select(GatewayGovernedQueryExecution, GatewayStructuredQueryResult)
            .join(
                GatewayStructuredQueryResult,
                GatewayStructuredQueryResult.execution_id == GatewayGovernedQueryExecution.id,
            )
            .where(
                GatewayGovernedQueryExecution.org_id == org_id,
                GatewayGovernedQueryExecution.user_id == store.user_id,
                GatewayGovernedQueryExecution.run_id == context.run_id,
                GatewayGovernedQueryExecution.connection_name == connection_name,
                GatewayGovernedQueryExecution.sql_hash == prepared.sql_hash,
                GatewayGovernedQueryExecution.query_path == context.path,
                GatewayGovernedQueryExecution.status == "completed",
            )
            .order_by(GatewayGovernedQueryExecution.terminal_at.desc())
            .limit(1)
        )
    ).one_or_none()
    if prior is None:
        return persisted_plan, row_limit, None
    prior_execution, prior_result = prior
    prior_rows = await _stored_result_rows(prior_result)
    await store.session.commit()
    await chat_store.append_event(
        store.session,
        run_id=context.run_id,
        event_type="query_completed",
        payload={
            "execution_id": prior_execution.id,
            "result_id": prior_result.id,
            "plan_id": context.plan_id,
            "reused": True,
            "row_count": prior_result.saved_row_count,
            "completeness": prior_result.result_completeness,
        },
    )
    reused = GovernedQueryResult(
        execution_id=prior_execution.id,
        result_id=prior_result.id,
        rows=prior_rows,
        row_count=prior_result.saved_row_count,
        tables=list((prior_result.provenance_json or {}).get("tables") or []),
        execution_ms=0.0,
        sql_hash=prepared.sql_hash,
        completeness=prior_result.result_completeness,
        truncation_reason=prior_result.truncation_reason,
        columns=prior_result.columns_json,
        estimated_cost_usd=persisted_plan.estimated_cost_usd,
        estimate_warning=None,
        pii_redacted=list((prior_result.provenance_json or {}).get("pii_redacted") or []),
    )
    return persisted_plan, row_limit, reused


def redact_rows(info: Any, annotations: Any, rows: list[dict[str, Any]]) -> tuple[PIIRedactor, list[dict[str, Any]]]:
    redactor = PIIRedactor()
    if info.pii_enabled and info.pii_rules:
        for column, rule in info.pii_rules.items():
            redactor.add_rule(column, rule)
    for column, rule in annotations.pii_columns.items():
        redactor.add_rule(column, rule)
    if redactor.has_rules():
        rows = redactor.redact_rows(rows)
    return redactor, rows


@dataclass
class RoutedRows:
    """Rows admitted past the route limits, with their completeness verdict."""

    saved_rows: list[dict[str, Any]]
    serialized_rows: list[dict[str, Any]]
    serialized_bytes: bytes
    completeness: str
    truncation_reason: str | None
    query_row_count: int | None


async def _reject_route(
    store: Store,
    *,
    context: GovernedQueryContext,
    execution: GatewayGovernedQueryExecution,
    cost_usd: float,
    proposal_id: str | None,
    event_payload: dict[str, Any] | None,
) -> None:
    await emit_query_credit(store.session, execution)
    await store.session.commit()
    if proposal_id:
        await reconcile_reservation(
            store.session,
            proposal_id=proposal_id,
            actual_cost_usd=cost_usd,
            completed=True,
        )
    if event_payload is not None:
        await chat_store.append_event(
            store.session,
            run_id=context.run_id,
            event_type="query_completed",
            payload=event_payload,
        )


async def route_rows(
    store: Store,
    *,
    context: GovernedQueryContext,
    execution: GatewayGovernedQueryExecution,
    persisted_plan: Any,
    rows: list[dict[str, Any]],
    row_limit: int,
    normalized_sql: str,
    sql_hash: str,
    native_stats: dict[str, Any],
    elapsed_ms: float,
    proposal_id: str | None,
) -> RoutedRows:
    """Apply the sentinel row limit, the completeness verdict, and the 10 MiB result cap."""
    sentinel_found = len(rows) > row_limit
    saved_rows = rows[:row_limit]
    if (
        sentinel_found
        and context.run_id
        and enterprise_chat_feature_flags().size_router
        and not (persisted_plan and persisted_plan.scout_row_limit)
    ):
        route_code = "runtime_required" if context.path == "mcp" else "aggregate_required"
        cost_usd = actual_cost_usd(native_stats, elapsed_ms)
        execution.status = "failed"
        execution.public_error_code = route_code
        execution.actual_cost_usd = cost_usd
        execution.actual_scan_bytes = _actual_scan_bytes(native_stats)
        execution.execution_ms = elapsed_ms
        execution.row_count = row_limit
        execution.completeness = "truncated"
        execution.truncation_reason = f"actual output exceeded the {row_limit}-row route limit"
        execution.terminal_at = datetime.now(UTC)
        await _reject_route(
            store,
            context=context,
            execution=execution,
            cost_usd=cost_usd,
            proposal_id=proposal_id,
            event_payload={
                "execution_id": execution.id,
                "plan_id": context.plan_id,
                "status": "rejected",
                "error_code": route_code,
                "actual_rows_exceeded": row_limit,
            },
        )
        raise GovernedQueryError(
            route_code,
            "Actual MCP output requires the notebook SDK; create a fresh plan"
            if route_code == "runtime_required"
            else "Actual output exceeds Track A; aggregate, filter, segment, or narrow the query",
        )
    explicit_limit = bool(re.search(r"\bLIMIT\s+\d+", normalized_sql, flags=re.IGNORECASE))
    if persisted_plan and persisted_plan.scout_row_limit:
        completeness = "unknown"
        truncation_reason = "1,000-row scouting result; full-source completeness is unknown"
        query_row_count = None
    elif sentinel_found:
        completeness = "truncated"
        truncation_reason = f"result exceeded the {row_limit}-row governed limit"
        query_row_count = None
    elif explicit_limit:
        completeness = "unknown"
        truncation_reason = "query contains an explicit LIMIT without proof of full-source completeness"
        query_row_count = len(saved_rows)
    else:
        completeness = "complete"
        truncation_reason = None
        query_row_count = len(saved_rows)

    serialized_rows = _json_safe(saved_rows)
    serialized_bytes = json.dumps(serialized_rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(serialized_bytes) > 10 * 1024 * 1024:
        cost_usd = actual_cost_usd(native_stats, elapsed_ms)
        execution.status = "failed"
        route_code = (
            "runtime_required"
            if context.run_id and context.path == "mcp" and enterprise_chat_feature_flags().size_router
            else "aggregate_required"
            if context.run_id and enterprise_chat_feature_flags().size_router
            else "result_too_large"
        )
        execution.public_error_code = route_code
        execution.actual_cost_usd = cost_usd
        execution.actual_scan_bytes = _actual_scan_bytes(native_stats)
        execution.actual_output_bytes = len(serialized_bytes)
        execution.execution_ms = elapsed_ms
        execution.row_count = len(saved_rows)
        execution.completeness = completeness
        execution.terminal_at = datetime.now(UTC)
        await _reject_route(
            store,
            context=context,
            execution=execution,
            cost_usd=cost_usd,
            proposal_id=proposal_id,
            event_payload=(
                {
                    "execution_id": execution.id,
                    "proposal_id": proposal_id,
                    "sql_hash": sql_hash,
                    "status": "rejected",
                    "error_code": route_code,
                }
                if context.run_id
                else None
            ),
        )
        raise GovernedQueryError(
            route_code,
            "Governed result exceeds 10 MiB; aggregate, filter, segment, or narrow the query",
        )
    return RoutedRows(
        saved_rows=saved_rows,
        serialized_rows=serialized_rows,
        serialized_bytes=serialized_bytes,
        completeness=completeness,
        truncation_reason=truncation_reason,
        query_row_count=query_row_count,
    )
