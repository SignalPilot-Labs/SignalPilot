"""Single execution authority for REST, MCP, and the SignalPilot SDK.

The phases live in sibling modules:

- ``query_executor_types``: public error, context, and result types plus ``normalize_sql``.
- ``query_executor_route``: validation, plan requirement, prior-result reuse, size routing.
- ``query_executor_run``: cost estimate, approval reservation, connector execution.
- ``query_executor_persist``: execution rows, structured results, chat events.
"""

from __future__ import annotations

from typing import Any

from gateway.governance.bindings import BoundQuery
from gateway.governance.query_executor_persist import (
    _actual_scan_bytes,
    _json_safe,
    _logical_type,
    _stored_result_rows,
    build_columns,
    create_execution,
    fail_execution,
    persist_result,
)
from gateway.governance.query_executor_route import (
    prepare_query,
    redact_rows,
    resolve_plan,
    route_rows,
)
from gateway.governance.query_executor_run import run_query
from gateway.governance.query_executor_types import (
    GovernedQueryContext,
    GovernedQueryError,
    GovernedQueryResult,
    normalize_sql,
)
from gateway.store import Store

__all__ = [
    "GovernedQueryContext",
    "GovernedQueryError",
    "GovernedQueryExecutor",
    "GovernedQueryResult",
    "governed_query_executor",
    "normalize_sql",
    "_actual_scan_bytes",
    "_json_safe",
    "_logical_type",
    "_stored_result_rows",
]


class GovernedQueryExecutor:
    """Validate, estimate, execute, redact, bound, and persist one query."""

    def __init__(self) -> None:
        self._active_connectors: dict[str, Any] = {}

    async def cancel(self, execution_id: str) -> bool:
        connector = self._active_connectors.get(execution_id)
        return await connector.cancel_current_query() if connector is not None else False

    async def execute(
        self,
        store: Store,
        *,
        connection_name: str,
        sql: str,
        row_limit: int,
        timeout_seconds: int,
        context: GovernedQueryContext,
        parameters: list[Any] | None = None,
        bound_query: BoundQuery | None = None,
    ) -> GovernedQueryResult:
        org_id = store._require_org_id()
        prepared = await prepare_query(
            store,
            org_id=org_id,
            connection_name=connection_name,
            sql=sql,
            parameters=parameters,
            bound_query=bound_query,
        )
        persisted_plan, row_limit, reused = await resolve_plan(
            store,
            org_id=org_id,
            context=context,
            connection_name=connection_name,
            prepared=prepared,
            row_limit=row_limit,
        )
        if reused is not None:
            return reused
        execution = await create_execution(
            store,
            org_id=org_id,
            context=context,
            connection_name=connection_name,
            sql_hash=prepared.sql_hash,
            timeout_seconds=timeout_seconds,
        )
        outcome = await run_query(
            self,
            store,
            context=context,
            connection_name=connection_name,
            prepared=prepared,
            persisted_plan=persisted_plan,
            execution=execution,
            row_limit=row_limit,
            timeout_seconds=timeout_seconds,
        )
        redactor, rows = redact_rows(prepared.info, prepared.annotations, outcome.rows)
        routed = await route_rows(
            store,
            context=context,
            execution=execution,
            persisted_plan=persisted_plan,
            rows=rows,
            row_limit=row_limit,
            normalized_sql=prepared.normalized_sql,
            sql_hash=prepared.sql_hash,
            native_stats=outcome.native_stats,
            elapsed_ms=outcome.elapsed_ms,
            proposal_id=outcome.proposal_id,
        )
        columns = build_columns(routed.saved_rows)
        result_id = await persist_result(
            store,
            org_id=org_id,
            context=context,
            connection_name=connection_name,
            execution=execution,
            tables=prepared.tables,
            sql_hash=prepared.sql_hash,
            saved_rows=routed.saved_rows,
            serialized_rows=routed.serialized_rows,
            serialized_bytes=routed.serialized_bytes,
            columns=columns,
            completeness=routed.completeness,
            truncation_reason=routed.truncation_reason,
            query_row_count=routed.query_row_count,
            native_stats=outcome.native_stats,
            elapsed_ms=outcome.elapsed_ms,
            proposal_id=outcome.proposal_id,
        )
        estimate = outcome.estimate
        return GovernedQueryResult(
            execution_id=execution.id,
            result_id=result_id,
            rows=routed.saved_rows,
            row_count=len(routed.saved_rows),
            tables=prepared.tables,
            execution_ms=outcome.elapsed_ms,
            sql_hash=prepared.sql_hash,
            completeness=routed.completeness,
            truncation_reason=routed.truncation_reason,
            columns=columns,
            estimated_cost_usd=max(0.0, estimate.estimated_usd if estimate else 0.0),
            estimate_warning=estimate.warning if estimate else "Estimate unavailable",
            pii_redacted=list(redactor.last_redacted_columns or []),
        )

    _fail = staticmethod(fail_execution)


governed_query_executor = GovernedQueryExecutor()
