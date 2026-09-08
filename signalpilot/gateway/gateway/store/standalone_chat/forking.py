"""Fork a shared chat: copy the whole conversation to the caller.

The fork owner gets a faithful private copy: runs, messages, run events,
files, structured query results, and governed query executions. Every row
gets a new id and one id map rewrites every reference inside the copied
JSON blobs, so tool cards and inline artifact cards resolve in the fork.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayChatConversation,
    GatewayChatFile,
    GatewayChatMessage,
    GatewayChatRun,
    GatewayChatRunEvent,
    GatewayGovernedQueryExecution,
    GatewayStructuredQueryResult,
)
from gateway.standalone_chat.domain import NONTERMINAL_RUN_STATUSES
from gateway.standalone_chat.object_storage import (
    conversation_file_key,
    conversation_prefix,
    runtime_object_key,
)
from gateway.store.standalone_chat.preferences import default_chat_budgets
from gateway.store.standalone_chat.sharing import _shared_grant_row


def _object_storage():
    """Resolve the storage factory through the package namespace at call time.

    Tests patch chat_object_storage on the package module. Read the name late
    so the patch takes effect."""
    from gateway.store import standalone_chat as chat_store

    return chat_store.chat_object_storage()


def remap_ids(value: Any, id_map: dict[str, str]) -> Any:
    """Return a deep copy of ``value`` with every string equal to an old id replaced.

    Only whole string values are rewritten. Keys, numbers, and substrings
    stay untouched. Pure: the input is never mutated.
    """
    if isinstance(value, str):
        return id_map.get(value, value)
    if isinstance(value, dict):
        return {key: remap_ids(item, id_map) for key, item in value.items()}
    if isinstance(value, list):
        return [remap_ids(item, id_map) for item in value]
    if isinstance(value, tuple):
        return tuple(remap_ids(item, id_map) for item in value)
    return value


def _result_object_category(object_key: str | None) -> str:
    """Category segment of a stored result key, e.g. "results" or "derived-results"."""
    parts = (object_key or "").split("/")
    if len(parts) >= 2 and "runs" in parts:
        try:
            return parts[parts.index("runs") + 2]
        except IndexError:
            pass
    return "results"


async def _rows(db: AsyncSession, query) -> list:
    return list((await db.execute(query)).scalars())


async def _load_source(db: AsyncSession, *, org_id: str, source: GatewayChatConversation) -> dict[str, list]:
    return {
        "runs": await _rows(
            db,
            select(GatewayChatRun)
            .where(GatewayChatRun.conversation_id == source.id)
            .order_by(GatewayChatRun.created_at),
        ),
        "messages": await _rows(
            db,
            select(GatewayChatMessage)
            .where(
                GatewayChatMessage.conversation_id == source.id,
                GatewayChatMessage.org_id == org_id,
                GatewayChatMessage.user_id == source.user_id,
                GatewayChatMessage.role.in_(("user", "assistant")),
            )
            .order_by(GatewayChatMessage.sequence),
        ),
        "events": await _rows(
            db,
            select(GatewayChatRunEvent)
            .where(
                GatewayChatRunEvent.conversation_id == source.id,
                GatewayChatRunEvent.org_id == org_id,
            )
            .order_by(GatewayChatRunEvent.created_at, GatewayChatRunEvent.sequence),
        ),
        "files": await _rows(
            db,
            select(GatewayChatFile)
            .where(
                GatewayChatFile.conversation_id == source.id,
                GatewayChatFile.org_id == org_id,
                GatewayChatFile.user_id == source.user_id,
                GatewayChatFile.status == "active",
            )
            .order_by(GatewayChatFile.created_at),
        ),
        "results": await _rows(
            db,
            select(GatewayStructuredQueryResult)
            .where(
                GatewayStructuredQueryResult.conversation_id == source.id,
                GatewayStructuredQueryResult.org_id == org_id,
            )
            .order_by(GatewayStructuredQueryResult.created_at),
        ),
        "executions": await _rows(
            db,
            select(GatewayGovernedQueryExecution)
            .where(
                GatewayGovernedQueryExecution.conversation_id == source.id,
                GatewayGovernedQueryExecution.org_id == org_id,
            )
            .order_by(GatewayGovernedQueryExecution.created_at),
        ),
    }


def _copy_run(
    row: GatewayChatRun, *, org_id: str, user_id: str, fork_id: str, id_map: dict[str, str]
) -> GatewayChatRun:
    return GatewayChatRun(
        id=id_map[row.id],
        org_id=org_id,
        user_id=user_id,
        conversation_id=fork_id,
        project_id=row.project_id,
        user_message_id=id_map.get(row.user_message_id, row.user_message_id),
        status=row.status,
        runtime_env=None,
        retry_of_run_id=id_map.get(row.retry_of_run_id or "", row.retry_of_run_id),
        execution_session_id=None,
        runtime_archive_id=None,
        execution_attempt=0,
        lease_owner=None,
        lease_expires_at=None,
        cancellation_requested_at=row.cancellation_requested_at,
        public_error_code=row.public_error_code,
        public_error_message=row.public_error_message,
        cost_usd=row.cost_usd,
        usage_json=row.usage_json,
        created_at=row.created_at,
        started_at=row.started_at,
        terminal_at=row.terminal_at,
        last_event_sequence=row.last_event_sequence,
    )


def _copy_message(
    row: GatewayChatMessage,
    *,
    org_id: str,
    user_id: str,
    project_id: str | None,
    fork_id: str,
    id_map: dict[str, str],
) -> GatewayChatMessage:
    metadata = dict(remap_ids(row.metadata_json or {}, id_map))
    metadata.pop("internal", None)
    metadata.pop("runtime_archive_available", None)
    metadata["forked"] = True
    return GatewayChatMessage(
        id=id_map[row.id],
        org_id=org_id,
        user_id=user_id,
        project_id=project_id,
        conversation_id=fork_id,
        role=row.role,
        content=row.content,
        metadata_json=metadata,
        idempotency_key=None,
        sequence=row.sequence,
        created_at=row.created_at,
    )


def _copy_event(
    row: GatewayChatRunEvent, *, org_id: str, user_id: str, fork_id: str, id_map: dict[str, str]
) -> GatewayChatRunEvent:
    return GatewayChatRunEvent(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        conversation_id=fork_id,
        run_id=id_map.get(row.run_id, row.run_id),
        sequence=row.sequence,
        event_type=row.event_type,
        payload_json=remap_ids(row.payload_json or {}, id_map),
        created_at=row.created_at,
    )


def _copy_execution(
    row: GatewayGovernedQueryExecution, *, user_id: str, fork_id: str, id_map: dict[str, str]
) -> GatewayGovernedQueryExecution:
    return GatewayGovernedQueryExecution(
        id=id_map[row.id],
        org_id=row.org_id,
        user_id=user_id,
        conversation_id=fork_id,
        run_id=id_map.get(row.run_id or "", row.run_id),
        project_id=row.project_id,
        commit_sha=row.commit_sha,
        connection_name=row.connection_name,
        plan_id=row.plan_id,
        query_path=row.query_path,
        sql_hash=row.sql_hash,
        status=row.status,
        timeout_seconds=row.timeout_seconds,
        warehouse_query_id=row.warehouse_query_id,
        estimated_cost_usd=row.estimated_cost_usd,
        actual_cost_usd=row.actual_cost_usd,
        actual_scan_bytes=row.actual_scan_bytes,
        actual_output_bytes=row.actual_output_bytes,
        execution_ms=row.execution_ms,
        row_count=row.row_count,
        completeness=row.completeness,
        truncation_reason=row.truncation_reason,
        public_error_code=row.public_error_code,
        created_at=row.created_at,
        started_at=row.started_at,
        terminal_at=row.terminal_at,
    )


async def _copy_result(
    row: GatewayStructuredQueryResult,
    *,
    storage,
    org_id: str,
    user_id: str,
    fork_id: str,
    id_map: dict[str, str],
) -> GatewayStructuredQueryResult:
    new_id = id_map[row.id]
    object_key = row.object_key
    byte_size = row.byte_size
    content_hash = row.content_hash
    if row.storage_kind == "object" and row.object_key:
        object_key = runtime_object_key(
            org_id=org_id,
            conversation_id=fork_id,
            run_id=id_map.get(row.run_id or "", row.run_id) or "fork",
            category=_result_object_category(row.object_key),
            object_id=new_id,
            filename="rows.json",
        )
        copied = await storage.copy(source_key=row.object_key, destination_key=object_key)
        byte_size = copied.byte_size or row.byte_size
        content_hash = copied.content_hash or row.content_hash
    return GatewayStructuredQueryResult(
        id=new_id,
        execution_id=id_map.get(row.execution_id or "", row.execution_id),
        org_id=org_id,
        owner_user_id=user_id,
        conversation_id=fork_id,
        run_id=id_map.get(row.run_id or "", row.run_id),
        columns_json=row.columns_json,
        rows_json=row.rows_json,
        preview_rows_json=row.preview_rows_json,
        storage_kind=row.storage_kind,
        object_key=object_key,
        byte_size=byte_size,
        content_hash=content_hash,
        source_result_ids_json=remap_ids(row.source_result_ids_json or [], id_map),
        code_hash=row.code_hash,
        result_origin=row.result_origin,
        query_row_count=row.query_row_count,
        saved_row_count=row.saved_row_count,
        source_completeness=row.source_completeness,
        result_completeness=row.result_completeness,
        display_completeness=row.display_completeness,
        truncation_reason=row.truncation_reason,
        provenance_json=remap_ids(row.provenance_json or {}, id_map),
        freshness_at=row.freshness_at,
        created_at=row.created_at,
    )


async def _copy_file(
    row: GatewayChatFile, *, storage, org_id: str, user_id: str, fork_id: str, id_map: dict[str, str]
) -> GatewayChatFile:
    copied_file_id = id_map[row.id]
    object_key = conversation_file_key(
        org_id=org_id,
        conversation_id=fork_id,
        file_id=copied_file_id,
        filename=row.filename,
    )
    copied = await storage.copy(source_key=row.object_key, destination_key=object_key)
    return GatewayChatFile(
        id=copied_file_id,
        org_id=org_id,
        user_id=user_id,
        conversation_id=fork_id,
        path=row.path,
        filename=row.filename,
        kind=row.kind,
        mime_type=row.mime_type,
        byte_size=copied.byte_size or row.byte_size,
        content_hash=copied.content_hash or row.content_hash,
        object_key=object_key,
        origin_run_id=id_map.get(row.origin_run_id or "", row.origin_run_id),
        origin="fork",
        status="active",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def fork_shared_conversation(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    token: str,
) -> GatewayChatConversation | None:
    """Copy the whole shared chat into a new private conversation for the caller.

    Budgets come from the caller's saved defaults. Raises RuntimeError while
    the source has a run in flight. Returns None when the grant is not active
    in the caller's organization.
    """
    shared = await _shared_grant_row(db, org_id=org_id, token=token, lock=True)
    if shared is None:
        return None
    _, source = shared
    active_run = (
        await db.execute(
            select(GatewayChatRun.id).where(
                GatewayChatRun.conversation_id == source.id,
                GatewayChatRun.status.in_(NONTERMINAL_RUN_STATUSES),
            )
        )
    ).scalar_one_or_none()
    if active_run is not None:
        raise RuntimeError("Wait for the current answer to finish before forking this chat")

    per_query_budget_usd, chat_budget_usd = await default_chat_budgets(db, org_id=org_id, user_id=user_id)
    rows = await _load_source(db, org_id=org_id, source=source)
    now = time.time()
    fork = GatewayChatConversation(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=source.project_id,
        surface="standalone",
        origin=source.origin,
        branch=source.branch,
        commit_sha=source.commit_sha,
        per_query_budget_usd=per_query_budget_usd,
        chat_budget_usd=chat_budget_usd,
        estimated_spend_usd=0.0,
        actual_spend_usd=0.0,
        reserved_spend_usd=0.0,
        model=source.model,
        effort=source.effort,
        forked_from_conversation_id=source.id,
        status="active",
        title=(source.title or "New chat")[:200],
        internal_summary=None,
        agent_session_id=None,
        notebook_session_id=None,
        notebook_kernel_session_id=None,
        notebook_path=None,
        message_count=len(rows["messages"]),
        total_tokens=0,
        total_cost_usd=0.0,
        created_at=now,
        updated_at=now,
    )

    # One id map across every copied table. Payloads reference results,
    # executions, runs, messages, and files by id; the walker rewrites all.
    id_map: dict[str, str] = {source.id: fork.id}
    for name in ("runs", "messages", "results", "executions", "files"):
        for row in rows[name]:
            id_map[row.id] = str(uuid.uuid4())

    db.add(fork)
    for run in rows["runs"]:
        db.add(_copy_run(run, org_id=org_id, user_id=user_id, fork_id=fork.id, id_map=id_map))
    for message in rows["messages"]:
        db.add(
            _copy_message(
                message,
                org_id=org_id,
                user_id=user_id,
                project_id=source.project_id,
                fork_id=fork.id,
                id_map=id_map,
            )
        )
    for event in rows["events"]:
        db.add(_copy_event(event, org_id=org_id, user_id=user_id, fork_id=fork.id, id_map=id_map))
    for execution in rows["executions"]:
        db.add(_copy_execution(execution, user_id=user_id, fork_id=fork.id, id_map=id_map))

    storage = _object_storage() if rows["files"] or rows["results"] else None
    copied_objects = False
    try:
        for result in rows["results"]:
            if result.storage_kind == "object" and result.object_key:
                copied_objects = True
            db.add(
                await _copy_result(
                    result, storage=storage, org_id=org_id, user_id=user_id, fork_id=fork.id, id_map=id_map
                )
            )
        for file in rows["files"]:
            copied_objects = True
            db.add(
                await _copy_file(file, storage=storage, org_id=org_id, user_id=user_id, fork_id=fork.id, id_map=id_map)
            )
        await db.commit()
    except Exception:
        await db.rollback()
        if copied_objects and storage is not None:
            try:
                await storage.delete_prefix(conversation_prefix(org_id, fork.id))
            except Exception:
                pass
        raise
    await db.refresh(fork)
    return fork
