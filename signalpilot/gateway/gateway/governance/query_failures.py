"""Terminal failure and rejection bookkeeping for governed query executions.

Every path that ends an execution without a stored result goes through here
so the execution row, the reservation, the plan counters and the
``query_completed`` / ``query_cancelled`` chat events stay consistent. Each
chat event carries ``status`` so the worker can derive ``tool_completed.error``
from it: ``failed``, ``rejected``, ``cancelled`` or ``timed_out``.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from gateway.connectors.health_monitor import health_monitor
from gateway.db.models import GatewayGovernedQueryExecution
from gateway.errors.mcp import sanitize_mcp_error
from gateway.governance.plan_limits import record_query
from gateway.governance.query_types import (
    GATEWAY_DB_UNAVAILABLE,
    GATEWAY_DB_UNAVAILABLE_MESSAGE,
    GovernedQueryContext,
    GovernedQueryError,
    actual_scan_bytes,
)
from gateway.standalone_chat.object_storage import chat_object_storage
from gateway.standalone_chat.query_approvals import reconcile_reservation
from gateway.store import Store
from gateway.store import standalone_chat as chat_store

# Warehouse connectors never raise SQLAlchemy errors; only the gateway's own
# session does. So a DBAPIError inside the execution block means SignalPilot's
# database dropped, not the customer's warehouse.
_GATEWAY_DB_ERRORS: tuple[type[BaseException], ...] = (DBAPIError, OperationalError, InterfaceError)


def is_gateway_db_error(exc: BaseException) -> bool:
    return isinstance(exc, _GATEWAY_DB_ERRORS)


async def fail_execution(store: Store, execution: GatewayGovernedQueryExecution, code: str) -> None:
    execution.status = "failed"
    execution.public_error_code = code
    execution.terminal_at = datetime.now(UTC)
    await store.session.commit()


def _failure_status(code: str) -> str:
    if code == "query_cancelled":
        return "cancelled"
    if code == "query_timeout":
        return "timed_out"
    return "failed"


async def record_execution_failure(
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
    cancel: Any,
) -> GovernedQueryError:
    """Persist a failed execution and return the public error to raise."""
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
        await cancel(execution.id)
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
    return GovernedQueryError(code, f"Query failed: {sanitize_mcp_error(str(exc))}")


async def reject_result(
    store: Store,
    execution: GatewayGovernedQueryExecution,
    *,
    context: GovernedQueryContext,
    org_id: str,
    route_code: str,
    message: str,
    elapsed_ms: float,
    native_stats: dict[str, Any],
    proposal_id: str | None,
    sql_hash: str,
    row_count: int,
    completeness: str,
    truncation_reason: str | None = None,
    output_bytes: int | None = None,
    event_extra: dict[str, Any] | None = None,
) -> GovernedQueryError:
    """Record a query that ran but whose output the route refuses to return."""
    actual_cost_usd = float(native_stats.get("estimated_cost_usd") or 0) or (elapsed_ms / 1000) * 0.000014
    execution.status = "failed"
    execution.public_error_code = route_code
    execution.actual_cost_usd = actual_cost_usd
    execution.actual_scan_bytes = actual_scan_bytes(native_stats)
    if output_bytes is not None:
        execution.actual_output_bytes = output_bytes
    execution.execution_ms = elapsed_ms
    execution.row_count = row_count
    execution.completeness = completeness
    if truncation_reason is not None:
        execution.truncation_reason = truncation_reason
    execution.terminal_at = datetime.now(UTC)
    await store.session.commit()
    if proposal_id:
        await reconcile_reservation(
            store.session,
            proposal_id=proposal_id,
            actual_cost_usd=actual_cost_usd,
            completed=True,
        )
    record_query(org_id)
    if context.run_id:
        await chat_store.append_event(
            store.session,
            run_id=context.run_id,
            event_type="query_completed",
            payload={
                "execution_id": execution.id,
                "plan_id": context.plan_id,
                "proposal_id": proposal_id,
                "sql_hash": sql_hash,
                "status": "rejected",
                "error_code": route_code,
                **(event_extra or {}),
            },
        )
    return GovernedQueryError(route_code, message)


async def persistence_failed(
    store: Store,
    execution: GatewayGovernedQueryExecution,
    *,
    org_id: str,
    object_key: str | None,
    proposal_id: str | None,
    actual_cost_usd: float,
    native_stats: dict[str, Any],
    output_bytes: int,
    elapsed_ms: float,
    row_count: int,
    completeness: str,
) -> GovernedQueryError:
    """The warehouse answered but the result row could not be committed."""
    if object_key:
        with suppress(Exception):
            await chat_object_storage().delete(object_key)
    with suppress(Exception):
        persisted = await store.session.get(GatewayGovernedQueryExecution, execution.id)
        if persisted is not None:
            persisted.status = "failed"
            persisted.public_error_code = "result_persistence_failed"
            persisted.actual_cost_usd = actual_cost_usd
            persisted.actual_scan_bytes = actual_scan_bytes(native_stats)
            persisted.actual_output_bytes = output_bytes
            persisted.execution_ms = elapsed_ms
            persisted.row_count = row_count
            persisted.completeness = completeness
            persisted.terminal_at = datetime.now(UTC)
            await store.session.commit()
    if proposal_id:
        with suppress(Exception):
            await reconcile_reservation(
                store.session,
                proposal_id=proposal_id,
                actual_cost_usd=actual_cost_usd,
                completed=True,
            )
    record_query(org_id)
    return GovernedQueryError(
        "result_persistence_failed",
        "The query completed but its governed result could not be persisted",
    )
