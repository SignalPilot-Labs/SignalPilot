"""Persistence phase of the governed query executor: execution rows, results, events.

Every ``query_completed`` event carries ``status`` (``completed`` here,
``reused`` and ``rejected`` in the route phase, ``failed`` in the run phase)
so the chat worker can derive ``tool_completed.error`` from it.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from gateway import __version__ as gateway_version
from gateway.billing.emitters.queries import emit_query_credit
from gateway.db.models import GatewayGovernedQueryExecution, GatewayStructuredQueryResult
from gateway.governance.query_executor_types import GovernedQueryContext, GovernedQueryError
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.standalone_chat.object_storage import chat_object_storage, runtime_object_key
from gateway.standalone_chat.query_approvals import reconcile_reservation
from gateway.store import Store
from gateway.store import standalone_chat as chat_store


def _actual_scan_bytes(stats: dict[str, Any]) -> int | None:
    for key in ("total_bytes_processed", "total_bytes_billed", "bytes_scanned", "scanned_bytes"):
        value = stats.get(key)
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
    return None


def actual_cost_usd(native_stats: dict[str, Any], elapsed_ms: float) -> float:
    return float(native_stats.get("estimated_cost_usd") or 0) or (elapsed_ms / 1000) * 0.000014


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


async def fail_execution(store: Store, execution: GatewayGovernedQueryExecution, code: str) -> None:
    execution.status = "failed"
    execution.public_error_code = code
    execution.terminal_at = datetime.now(UTC)
    await emit_query_credit(store.session, execution)
    await store.session.commit()


async def create_execution(
    store: Store,
    *,
    org_id: str,
    context: GovernedQueryContext,
    connection_name: str,
    sql_hash: str,
    timeout_seconds: int,
) -> GatewayGovernedQueryExecution:
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
    return execution


async def persist_result(
    store: Store,
    *,
    org_id: str,
    context: GovernedQueryContext,
    connection_name: str,
    execution: GatewayGovernedQueryExecution,
    tables: list[str],
    sql_hash: str,
    saved_rows: list[dict[str, Any]],
    serialized_rows: list[dict[str, Any]],
    serialized_bytes: bytes,
    columns: list[dict[str, Any]],
    completeness: str,
    truncation_reason: str | None,
    query_row_count: int | None,
    native_stats: dict[str, Any],
    elapsed_ms: float,
    proposal_id: str | None,
) -> str:
    """Store the structured result, close the execution, and emit chat events.

    Returns the new result id.
    """
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
            "tables": tables,
            "runtime_version": gateway_version,
            "plugin_version": os.getenv("SIGNALPILOT_PLUGIN_VERSION", "deployed"),
        },
    )
    store.session.add(result)
    execution.status = "completed"
    execution.row_count = len(saved_rows)
    execution.completeness = completeness
    execution.truncation_reason = truncation_reason
    cost_usd = actual_cost_usd(native_stats, elapsed_ms)
    execution.actual_cost_usd = cost_usd
    execution.actual_scan_bytes = _actual_scan_bytes(native_stats)
    execution.actual_output_bytes = len(serialized_bytes)
    execution.execution_ms = elapsed_ms
    execution.terminal_at = datetime.now(UTC)
    try:
        await emit_query_credit(store.session, execution)
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
                persisted_execution.actual_cost_usd = cost_usd
                persisted_execution.actual_scan_bytes = _actual_scan_bytes(native_stats)
                persisted_execution.actual_output_bytes = len(serialized_bytes)
                persisted_execution.execution_ms = elapsed_ms
                persisted_execution.row_count = len(saved_rows)
                persisted_execution.completeness = completeness
                persisted_execution.terminal_at = datetime.now(UTC)
                await emit_query_credit(store.session, persisted_execution)
                await store.session.commit()
        if proposal_id:
            with suppress(Exception):
                await reconcile_reservation(
                    store.session,
                    proposal_id=proposal_id,
                    actual_cost_usd=cost_usd,
                    completed=True,
                )
        raise GovernedQueryError(
            "result_persistence_failed",
            "The query completed but its governed result could not be persisted",
        ) from exc
    if proposal_id:
        await reconcile_reservation(
            store.session,
            proposal_id=proposal_id,
            actual_cost_usd=cost_usd,
            completed=True,
        )
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
                "status": "completed",
                "row_count": len(saved_rows),
                "completeness": completeness,
                "truncation_reason": truncation_reason,
            },
        )
    return result_id
