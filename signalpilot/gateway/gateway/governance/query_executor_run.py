"""Execution phase of the governed query executor: estimate, approve, run on the connector."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from gateway.billing.emitters.queries import emit_query_credit
from gateway.connectors.health_monitor import health_monitor
from gateway.connectors.pool_manager import pool_manager
from gateway.db.models import GatewayGovernedQueryExecution
from gateway.engine import inject_limit
from gateway.governance.bindings import BoundQueryError
from gateway.governance.cost_estimator import CostEstimate, CostEstimator
from gateway.governance.query_executor_persist import fail_execution
from gateway.governance.query_executor_route import PreparedQuery
from gateway.governance.query_executor_types import (
    GATEWAY_DB_UNAVAILABLE,
    GATEWAY_DB_UNAVAILABLE_MESSAGE,
    GovernedQueryContext,
    GovernedQueryError,
)
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.standalone_chat.query_approvals import (
    reconcile_reservation,
    reserve_or_request_approval,
)
from gateway.store import Store
from gateway.store import standalone_chat as chat_store

if TYPE_CHECKING:
    from gateway.governance.query_executor import GovernedQueryExecutor

# Warehouse connectors never raise SQLAlchemy errors; only the gateway's own
# session does. So a DBAPIError inside the execution block means SignalPilot's
# database dropped, not the customer's warehouse.
_GATEWAY_DB_ERRORS: tuple[type[BaseException], ...] = (DBAPIError, OperationalError, InterfaceError)


def is_gateway_db_error(exc: BaseException) -> bool:
    return isinstance(exc, _GATEWAY_DB_ERRORS)


def _failure_status(code: str) -> str:
    if code == "query_cancelled":
        return "cancelled"
    if code == "query_timeout":
        return "timed_out"
    return "failed"


async def record_execution_failure(
    executor: GovernedQueryExecutor,
    store: Store,
    execution: GatewayGovernedQueryExecution,
    exc: Exception,
    *,
    context: GovernedQueryContext,
    connection_name: str,
    db_type: Any,
    elapsed_ms: float,
    proposal_id: str | None,
    sql_hash: str,
) -> GovernedQueryError:
    """Persist a failed execution and return the public error to raise.

    The chat event carries ``status`` (``failed``, ``cancelled`` or
    ``timed_out``) and, for a gateway database outage, ``retryable: true``.
    """
    if is_gateway_db_error(exc):
        code = GATEWAY_DB_UNAVAILABLE
        explicitly_cancelled = False
    else:
        health_monitor.record(connection_name, elapsed_ms, False, type(exc).__name__, db_type)
        with suppress(Exception):
            await store.session.refresh(execution)
        explicitly_cancelled = execution.status == "cancelled"
        code = (
            "query_cancelled"
            if explicitly_cancelled
            else "query_timeout"
            if "timeout" in str(exc).lower()
            else "query_failed"
        )
    with suppress(Exception):
        await executor.cancel(execution.id)
    execution.execution_ms = elapsed_ms
    with suppress(Exception):
        if not explicitly_cancelled:
            await fail_execution(store, execution, code)
        else:
            await store.session.commit()
    if context.run_id:
        payload: dict[str, Any] = {
            "execution_id": execution.id,
            "proposal_id": proposal_id,
            "sql_hash": sql_hash,
            "status": _failure_status(code),
            "error_code": code,
        }
        if code == GATEWAY_DB_UNAVAILABLE:
            payload["retryable"] = True
        with suppress(Exception):
            await chat_store.append_event(
                store.session,
                run_id=context.run_id,
                event_type="query_cancelled" if code in {"query_timeout", "query_cancelled"} else "query_completed",
                payload=payload,
            )
    if proposal_id:
        with suppress(Exception):
            await reconcile_reservation(
                store.session,
                proposal_id=proposal_id,
                actual_cost_usd=None,
                completed=False,
            )
    if code == GATEWAY_DB_UNAVAILABLE:
        return GovernedQueryError(code, GATEWAY_DB_UNAVAILABLE_MESSAGE, retryable=True)
    if code == "query_cancelled":
        return GovernedQueryError(code, "Query cancelled")
    if code == "query_timeout":
        return GovernedQueryError(code, "Query timed out")
    from gateway.errors.mcp import sanitize_mcp_error

    return GovernedQueryError(code, f"Query failed: {sanitize_mcp_error(str(exc))}")


@dataclass
class RunOutcome:
    """Raw rows and warehouse statistics from one connector execution."""

    rows: list[dict[str, Any]]
    estimate: CostEstimate | None
    proposal_id: str | None
    native_stats: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0


async def run_query(
    executor: GovernedQueryExecutor,
    store: Store,
    *,
    context: GovernedQueryContext,
    connection_name: str,
    prepared: PreparedQuery,
    persisted_plan: Any,
    execution: GatewayGovernedQueryExecution,
    row_limit: int,
    timeout_seconds: int,
) -> RunOutcome:
    info = prepared.info
    sql_hash = prepared.sql_hash
    # Fetch one sentinel row beyond the consumer limit. An explicit LIMIT in
    # user SQL remains unknown completeness unless the sentinel proves truncation.
    fetch_limit = min(100_001, row_limit + 1)
    try:
        safe_governance_sql = inject_limit(prepared.governance_sql, fetch_limit, dialect=prepared.dialect)
        internal_safe_sql = prepared.bound_query.restore_after_governance(
            safe_governance_sql, prepared.parameter_sentinels
        )
        safe_query = prepared.bound_query.render(internal_safe_sql)
    except (ValueError, BoundQueryError) as exc:
        await fail_execution(store, execution, "query_blocked")
        raise GovernedQueryError("query_blocked", str(exc)) from exc

    conn_str = await store.get_connection_string(connection_name)
    if not conn_str:
        await fail_execution(store, execution, "credentials_missing")
        raise GovernedQueryError("credentials_missing", "No credentials stored for this connection")

    extras = await store.get_credential_extras(connection_name)
    estimate = None
    proposal_id = None
    native_stats: dict[str, Any] = {}
    started = time.monotonic()
    execution.started_at = datetime.now(UTC)
    execution.status = "running"
    await store.session.commit()
    try:
        async with pool_manager.connection(
            info.db_type,
            conn_str,
            credential_extras=extras,
            connection_name=connection_name,
        ) as connector:
            estimate = (
                CostEstimate(
                    estimated_rows=persisted_plan.estimated_scan_rows or 0,
                    estimated_cost=0,
                    estimated_usd=persisted_plan.estimated_cost_usd,
                    estimated_scan_rows=persisted_plan.estimated_scan_rows,
                    estimated_scan_bytes=persisted_plan.estimated_scan_bytes,
                    estimated_output_rows=persisted_plan.estimated_output_rows,
                    estimated_output_bytes=persisted_plan.estimated_output_bytes,
                    quality=persisted_plan.estimate_quality,
                )
                if persisted_plan is not None
                else await CostEstimator.estimate(connector, safe_governance_sql, info.db_type)
            )
            execution.estimated_cost_usd = max(0.0, estimate.estimated_usd)
            await store.session.commit()
            if context.run_id and enterprise_chat_feature_flags().query_approval:
                reservation = await reserve_or_request_approval(
                    store.session,
                    run_id=context.run_id,
                    sql_hash=sql_hash,
                    normalized_sql=prepared.normalized_sql,
                    connection_name=connection_name,
                    query_path=context.path,
                    purpose=(persisted_plan.purpose if persisted_plan is not None else "Run a governed analysis query"),
                    timeout_seconds=timeout_seconds,
                    estimated_cost_usd=execution.estimated_cost_usd,
                    estimate_quality=(
                        persisted_plan.estimate_quality if persisted_plan is not None else estimate.quality
                    ),
                    estimate_json={
                        "estimated_scan_rows": estimate.estimated_scan_rows,
                        "estimated_scan_bytes": estimate.estimated_scan_bytes,
                        "estimated_output_rows": estimate.estimated_output_rows,
                        "estimated_output_bytes": estimate.estimated_output_bytes,
                        "planner_cost": estimate.estimated_cost,
                        "warning": estimate.warning,
                    },
                    plan_id=context.plan_id,
                )
                proposal_id = reservation.proposal_id
                if persisted_plan is not None:
                    persisted_plan.proposal_id = proposal_id
                    await store.session.commit()
                if not reservation.approved:
                    execution.status = "waiting_for_approval"
                    await store.session.commit()
                    raise GovernedQueryError(
                        "query_approval_required",
                        f"Query approval required (proposal {proposal_id})",
                    )
            executor._active_connectors[execution.id] = connector
            if context.run_id:
                await chat_store.append_event(
                    store.session,
                    run_id=context.run_id,
                    event_type="query_started",
                    payload={
                        "execution_id": execution.id,
                        "proposal_id": proposal_id,
                        "sql_hash": sql_hash,
                    },
                )
            try:
                rows = await connector.execute(
                    safe_query.sql,
                    params=safe_query.parameters,
                    timeout=timeout_seconds,
                )
            except asyncio.CancelledError:
                with suppress(Exception):
                    await connector.cancel_current_query()
                raise
            except Exception:
                with suppress(Exception):
                    await connector.cancel_current_query()
                raise
            finally:
                executor._active_connectors.pop(execution.id, None)
            execution.warehouse_query_id = connector.get_last_query_id()
            native_stats = connector.get_last_query_stats() or {}
    except asyncio.CancelledError:
        health_monitor.record(
            connection_name, (time.monotonic() - started) * 1000, False, "CancelledError", info.db_type
        )
        with suppress(Exception):
            execution.status = "cancelled"
            execution.public_error_code = "query_cancelled"
            execution.terminal_at = datetime.now(UTC)
            await emit_query_credit(store.session, execution)
            await store.session.commit()
        raise
    except GovernedQueryError:
        raise
    except Exception as exc:
        raise await record_execution_failure(
            executor,
            store,
            execution,
            exc,
            context=context,
            connection_name=connection_name,
            db_type=info.db_type,
            elapsed_ms=(time.monotonic() - started) * 1000,
            proposal_id=proposal_id,
            sql_hash=sql_hash,
        ) from exc

    elapsed_ms = (time.monotonic() - started) * 1000
    health_monitor.record(connection_name, elapsed_ms, True, db_type=info.db_type)
    return RunOutcome(
        rows=rows,
        estimate=estimate,
        proposal_id=proposal_id,
        native_stats=native_stats,
        elapsed_ms=elapsed_ms,
    )
