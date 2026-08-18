"""Single execution authority for REST, MCP, and the SignalPilot SDK."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import sqlglot
from sqlalchemy import select

from gateway import __version__ as gateway_version
from gateway.connectors.health_monitor import health_monitor
from gateway.connectors.pool_manager import pool_manager
from gateway.db.models import GatewayGovernedQueryExecution, GatewayStructuredQueryResult
from gateway.engine import inject_limit, sqlglot_dialect, validate_sql
from gateway.governance.annotations import load_annotations
from gateway.governance.cost_estimator import CostEstimate, CostEstimator
from gateway.governance.pii import PIIRedactor
from gateway.governance.plan_limits import check_query_limit, get_org_limits, record_query
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.standalone_chat.object_storage import chat_object_storage, runtime_object_key
from gateway.standalone_chat.query_approvals import (
    reconcile_reservation,
    reserve_or_request_approval,
)
from gateway.store import Store
from gateway.store import standalone_chat as chat_store


class GovernedQueryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GovernedQueryContext:
    path: Literal["direct_api", "mcp", "sdk"]
    conversation_id: str | None = None
    run_id: str | None = None
    project_id: str | None = None
    commit_sha: str | None = None
    branch: str | None = None
    plan_id: str | None = None


@dataclass(frozen=True)
class GovernedQueryResult:
    execution_id: str
    result_id: str
    rows: list[dict[str, Any]]
    row_count: int
    tables: list[str]
    execution_ms: float
    sql_hash: str
    completeness: str
    truncation_reason: str | None
    columns: list[dict[str, Any]]
    estimated_cost_usd: float
    estimate_warning: str | None
    pii_redacted: list[str]


def normalize_sql(sql: str, dialect: str | None) -> str:
    """Produce the canonical SQL used by durable hashes and approvals."""
    try:
        expression = sqlglot.parse_one(sql, read=dialect)
        return expression.sql(dialect=dialect, pretty=False, normalize=True)
    except Exception:
        return re.sub(r"\s+", " ", sql.strip().rstrip(";"))


def _logical_type(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, datetime):
        return "timestamp"
    return type(value).__name__.lower()


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _actual_scan_bytes(stats: dict[str, Any]) -> int | None:
    for key in ("total_bytes_processed", "total_bytes_billed", "bytes_scanned", "scanned_bytes"):
        value = stats.get(key)
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
    return None


async def _stored_result_rows(result: GatewayStructuredQueryResult) -> list[dict[str, Any]]:
    if result.storage_kind != "object":
        return list(result.rows_json or [])
    if not result.object_key:
        raise GovernedQueryError("result_unavailable", "Stored query result is unavailable")
    data = await chat_object_storage().get_bytes(result.object_key, max_bytes=10 * 1024 * 1024)
    if result.content_hash and hashlib.sha256(data).hexdigest() != result.content_hash:
        raise GovernedQueryError("result_integrity_failed", "Stored query result failed integrity validation")
    rows = json.loads(data)
    if not isinstance(rows, list):
        raise GovernedQueryError("result_unavailable", "Stored query result is invalid")
    return rows


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
    ) -> GovernedQueryResult:
        org_id = store._require_org_id()
        plan = await get_org_limits(org_id)
        check_query_limit(org_id, plan)

        info = await store.get_connection(connection_name)
        if info is None:
            raise GovernedQueryError("connection_not_found", "Connection not found")

        settings = await store.load_settings()
        annotations = load_annotations(org_id, connection_name)
        blocked_tables = list(annotations.blocked_tables)
        if settings.blocked_tables:
            blocked_tables.extend(table for table in settings.blocked_tables if table not in blocked_tables)

        dialect = sqlglot_dialect(info.db_type)
        validation = validate_sql(sql, blocked_tables=blocked_tables or None, dialect=dialect)
        if not validation.ok:
            raise GovernedQueryError("query_blocked", validation.blocked_reason or "Query blocked")

        normalized_sql = normalize_sql(sql, dialect)
        sql_hash = hashlib.sha256(normalized_sql.encode()).hexdigest()
        persisted_plan = None
        if context.run_id and enterprise_chat_feature_flags().size_router:
            if not context.plan_id:
                raise GovernedQueryError("plan_required", "Chat query execution requires a valid plan_id")
            from gateway.governance.query_planner import QueryPlanError, require_execution_plan

            try:
                persisted_plan = await require_execution_plan(
                    store,
                    plan_id=context.plan_id,
                    sql=sql,
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
                        GatewayGovernedQueryExecution.sql_hash == sql_hash,
                        GatewayGovernedQueryExecution.query_path == context.path,
                        GatewayGovernedQueryExecution.status == "completed",
                    )
                    .order_by(GatewayGovernedQueryExecution.terminal_at.desc())
                    .limit(1)
                )
            ).one_or_none()
            if prior is not None:
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
                return GovernedQueryResult(
                    execution_id=prior_execution.id,
                    result_id=prior_result.id,
                    rows=prior_rows,
                    row_count=prior_result.saved_row_count,
                    tables=list((prior_result.provenance_json or {}).get("tables") or []),
                    execution_ms=0.0,
                    sql_hash=sql_hash,
                    completeness=prior_result.result_completeness,
                    truncation_reason=prior_result.truncation_reason,
                    columns=prior_result.columns_json,
                    estimated_cost_usd=persisted_plan.estimated_cost_usd,
                    estimate_warning=None,
                    pii_redacted=list((prior_result.provenance_json or {}).get("pii_redacted") or []),
                )
        execution = GatewayGovernedQueryExecution(
            id=str(uuid.uuid4()),
            org_id=org_id,
            user_id=store.user_id,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            project_id=context.project_id,
            commit_sha=context.commit_sha,
            connection_name=connection_name,
            plan_id=context.plan_id,
            query_path=context.path,
            sql_hash=sql_hash,
            status="estimating",
            timeout_seconds=timeout_seconds,
        )
        store.session.add(execution)
        await store.session.commit()

        # Fetch one sentinel row beyond the consumer limit. An explicit LIMIT in
        # user SQL remains unknown completeness unless the sentinel proves truncation.
        fetch_limit = min(100_001, row_limit + 1)
        try:
            safe_sql = inject_limit(sql, fetch_limit, dialect=dialect)
        except ValueError as exc:
            await self._fail(store, execution, "query_blocked")
            raise GovernedQueryError("query_blocked", str(exc)) from exc

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            await self._fail(store, execution, "credentials_missing")
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
                    else await CostEstimator.estimate(connector, safe_sql, info.db_type)
                )
                execution.estimated_cost_usd = max(0.0, estimate.estimated_usd)
                await store.session.commit()
                if context.run_id and enterprise_chat_feature_flags().query_approval:
                    reservation = await reserve_or_request_approval(
                        store.session,
                        run_id=context.run_id,
                        sql_hash=sql_hash,
                        normalized_sql=normalized_sql,
                        connection_name=connection_name,
                        query_path=context.path,
                        purpose=(persisted_plan.purpose if persisted_plan is not None else "Run a governed analysis query"),
                        timeout_seconds=timeout_seconds,
                        estimated_cost_usd=execution.estimated_cost_usd,
                        estimate_quality=(persisted_plan.estimate_quality if persisted_plan is not None else estimate.quality),
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
                self._active_connectors[execution.id] = connector
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
                    rows = await connector.execute(safe_sql, timeout=timeout_seconds)
                except Exception:
                    with suppress(Exception):
                        await connector.cancel_current_query()
                    raise
                finally:
                    self._active_connectors.pop(execution.id, None)
                execution.warehouse_query_id = connector.get_last_query_id()
                native_stats = connector.get_last_query_stats() or {}
        except GovernedQueryError:
            raise
        except Exception as exc:
            elapsed = (time.monotonic() - started) * 1000
            health_monitor.record(connection_name, elapsed, False, type(exc).__name__, info.db_type)
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
                await self.cancel(execution.id)
            execution.execution_ms = elapsed
            if not explicitly_cancelled:
                await self._fail(store, execution, code)
            else:
                await store.session.commit()
            if context.run_id:
                with suppress(Exception):
                    await chat_store.append_event(
                        store.session,
                        run_id=context.run_id,
                        event_type=(
                            "query_cancelled"
                            if code in {"query_timeout", "query_cancelled"}
                            else "query_completed"
                        ),
                        payload={
                            "execution_id": execution.id,
                            "proposal_id": proposal_id,
                            "sql_hash": sql_hash,
                            "status": (
                                "cancelled"
                                if code == "query_cancelled"
                                else "timed_out"
                                if code == "query_timeout"
                                else "failed"
                            ),
                            "error_code": code,
                        },
                    )
            if proposal_id:
                await reconcile_reservation(
                    store.session,
                    proposal_id=proposal_id,
                    actual_cost_usd=None,
                    completed=False,
                )
            from gateway.errors.mcp import sanitize_mcp_error

            raise GovernedQueryError(
                code,
                "Query cancelled"
                if code == "query_cancelled"
                else "Query timed out"
                if code == "query_timeout"
                else f"Query failed: {sanitize_mcp_error(str(exc))}",
            ) from exc

        elapsed_ms = (time.monotonic() - started) * 1000
        health_monitor.record(connection_name, elapsed_ms, True, db_type=info.db_type)

        redactor = PIIRedactor()
        if info.pii_enabled and info.pii_rules:
            for column, rule in info.pii_rules.items():
                redactor.add_rule(column, rule)
        for column, rule in annotations.pii_columns.items():
            redactor.add_rule(column, rule)
        if redactor.has_rules():
            rows = redactor.redact_rows(rows)

        sentinel_found = len(rows) > row_limit
        saved_rows = rows[:row_limit]
        if (
            sentinel_found
            and context.run_id
            and enterprise_chat_feature_flags().size_router
            and not (persisted_plan and persisted_plan.scout_row_limit)
        ):
            route_code = "runtime_required" if context.path == "mcp" else "aggregate_required"
            actual_cost_usd = float(native_stats.get("estimated_cost_usd") or 0) or (elapsed_ms / 1000) * 0.000014
            execution.status = "failed"
            execution.public_error_code = route_code
            execution.actual_cost_usd = actual_cost_usd
            execution.actual_scan_bytes = _actual_scan_bytes(native_stats)
            execution.execution_ms = elapsed_ms
            execution.row_count = row_limit
            execution.completeness = "truncated"
            execution.truncation_reason = f"actual output exceeded the {row_limit}-row route limit"
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
            await chat_store.append_event(
                store.session,
                run_id=context.run_id,
                event_type="query_completed",
                payload={
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
            actual_cost_usd = float(native_stats.get("estimated_cost_usd") or 0) or (elapsed_ms / 1000) * 0.000014
            execution.status = "failed"
            route_code = (
                "runtime_required"
                if context.run_id and context.path == "mcp" and enterprise_chat_feature_flags().size_router
                else "aggregate_required"
                if context.run_id and enterprise_chat_feature_flags().size_router
                else "result_too_large"
            )
            execution.public_error_code = route_code
            execution.actual_cost_usd = actual_cost_usd
            execution.actual_scan_bytes = _actual_scan_bytes(native_stats)
            execution.actual_output_bytes = len(serialized_bytes)
            execution.execution_ms = elapsed_ms
            execution.row_count = len(saved_rows)
            execution.completeness = completeness
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
                        "proposal_id": proposal_id,
                        "sql_hash": sql_hash,
                        "status": "rejected",
                        "error_code": route_code,
                    },
                )
            raise GovernedQueryError(
                route_code,
                "Governed result exceeds 10 MiB; aggregate, filter, segment, or narrow the query",
            )

        columns = []
        if saved_rows:
            for name in saved_rows[0]:
                values = [row.get(name) for row in saved_rows]
                sample = next((value for value in values if value is not None), None)
                columns.append(
                    {
                        "name": str(name),
                        "logical_type": _logical_type(sample),
                        "nullable": any(v is None for v in values),
                    }
                )

        result_id = str(uuid.uuid4())
        storage_kind = "inline"
        object_key = None
        stored_rows = serialized_rows
        preview_rows = serialized_rows[:200]
        content_hash = hashlib.sha256(serialized_bytes).hexdigest()
        if (
            context.path == "sdk"
            and context.run_id
            and context.conversation_id
            and enterprise_chat_feature_flags().runtime_results
        ):
            storage_kind = "object"
            object_key = runtime_object_key(
                org_id=org_id,
                conversation_id=context.conversation_id,
                run_id=context.run_id,
                category="results",
                object_id=result_id,
                filename="rows.json",
            )
            stored = await chat_object_storage().put_bytes(
                key=object_key,
                data=serialized_bytes,
                content_type="application/json",
            )
            content_hash = stored.content_hash
            stored_rows = []
        result = GatewayStructuredQueryResult(
            id=result_id,
            execution_id=execution.id,
            org_id=org_id,
            owner_user_id=store.user_id,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            columns_json=columns,
            rows_json=stored_rows,
            preview_rows_json=preview_rows,
            storage_kind=storage_kind,
            object_key=object_key,
            byte_size=len(serialized_bytes),
            content_hash=content_hash,
            source_result_ids_json=[],
            result_origin=context.path,
            query_row_count=query_row_count,
            saved_row_count=len(saved_rows),
            source_completeness="unknown",
            result_completeness=completeness,
            display_completeness=("complete" if len(saved_rows) <= 200 else "truncated"),
            truncation_reason=truncation_reason,
            provenance_json={
                "sql_hash": sql_hash,
                "connection_name": connection_name,
                "project_id": context.project_id,
                "commit_sha": context.commit_sha,
                "query_path": context.path,
                "tables": validation.tables,
                "runtime_version": gateway_version,
                "plugin_version": os.getenv("SIGNALPILOT_PLUGIN_VERSION", "deployed"),
            },
        )
        store.session.add(result)
        execution.status = "completed"
        execution.row_count = len(saved_rows)
        execution.completeness = completeness
        execution.truncation_reason = truncation_reason
        actual_cost_usd = float(native_stats.get("estimated_cost_usd") or 0) or (elapsed_ms / 1000) * 0.000014
        execution.actual_cost_usd = actual_cost_usd
        execution.actual_scan_bytes = _actual_scan_bytes(native_stats)
        execution.actual_output_bytes = len(serialized_bytes)
        execution.execution_ms = elapsed_ms
        execution.terminal_at = datetime.now(UTC)
        try:
            await store.session.commit()
        except Exception as exc:
            await store.session.rollback()
            if object_key:
                with suppress(Exception):
                    await chat_object_storage().delete(object_key)
            with suppress(Exception):
                persisted_execution = await store.session.get(GatewayGovernedQueryExecution, execution.id)
                if persisted_execution is not None:
                    persisted_execution.status = "failed"
                    persisted_execution.public_error_code = "result_persistence_failed"
                    persisted_execution.actual_cost_usd = actual_cost_usd
                    persisted_execution.actual_scan_bytes = _actual_scan_bytes(native_stats)
                    persisted_execution.actual_output_bytes = len(serialized_bytes)
                    persisted_execution.execution_ms = elapsed_ms
                    persisted_execution.row_count = len(saved_rows)
                    persisted_execution.completeness = completeness
                    persisted_execution.terminal_at = datetime.now(UTC)
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
            raise GovernedQueryError(
                "result_persistence_failed",
                "The query completed but its governed result could not be persisted",
            ) from exc
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
                event_type="query_progress",
                payload={
                    "execution_id": execution.id,
                    "rows_saved": len(saved_rows),
                    "completeness": completeness,
                },
            )
            await chat_store.append_event(
                store.session,
                run_id=context.run_id,
                event_type="query_completed",
                payload={
                    "execution_id": execution.id,
                    "result_id": result_id,
                    "proposal_id": proposal_id,
                    "sql_hash": sql_hash,
                    "row_count": len(saved_rows),
                    "completeness": completeness,
                    "truncation_reason": truncation_reason,
                },
            )

        return GovernedQueryResult(
            execution_id=execution.id,
            result_id=result_id,
            rows=saved_rows,
            row_count=len(saved_rows),
            tables=validation.tables,
            execution_ms=elapsed_ms,
            sql_hash=sql_hash,
            completeness=completeness,
            truncation_reason=truncation_reason,
            columns=columns,
            estimated_cost_usd=max(0.0, estimate.estimated_usd if estimate else 0.0),
            estimate_warning=estimate.warning if estimate else "Estimate unavailable",
            pii_redacted=list(redactor.last_redacted_columns or []),
        )

    @staticmethod
    async def _fail(store: Store, execution: GatewayGovernedQueryExecution, code: str) -> None:
        execution.status = "failed"
        execution.public_error_code = code
        execution.terminal_at = datetime.now(UTC)
        await store.session.commit()


governed_query_executor = GovernedQueryExecutor()
