"""Query endpoints — POST /api/query and POST /api/query/explain."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..common.ip import request_meta
from ..connectors.pool_manager import pool_manager
from ..db.models import (
    GatewayChatConversation,
    GatewayChatRun,
    GatewayGovernedQueryExecution,
    GatewayQueryPlan,
    GatewayRuntimeDataset,
    GatewayStructuredQueryResult,
)
from ..engine import inject_limit, sqlglot_dialect, validate_sql
from ..governance.annotations import load_annotations
from ..governance.query_executor import (
    GovernedQueryContext,
    GovernedQueryError,
    governed_query_executor,
)
from ..governance.query_planner import QueryPlanError, create_query_plan
from ..governance.runtime_datasets import RuntimeDatasetError, runtime_dataset_executor
from ..security.scope_guard import RequireScope
from ..standalone_chat.config import enterprise_chat_feature_flags
from ..standalone_chat.object_storage import chat_object_storage, runtime_object_key
from ..standalone_chat.query_results import QueryResultUnavailable, load_result_rows
from .deps import StoreD, sanitize_db_error
from .query_models import (
    DirectQueryRequest,
    PublishResultRequest,
    QueryDatasetRequest,
    QueryPlanRequest,
)

router = APIRouter(prefix="/api")


async def _query_context(store: StoreD, request: Request, *, path: str, plan_id: str | None = None):
    context = GovernedQueryContext(path=path)  # type: ignore[arg-type]
    claims = getattr(request.state, "_jwt_claims", {}) or {}
    identity = claims.get("execution_identity")
    if not isinstance(identity, str) or not identity.startswith("chat:"):
        return context
    run_id = identity.removeprefix("chat:")
    scoped = (
        await store.session.execute(
            select(GatewayChatRun, GatewayChatConversation)
            .join(
                GatewayChatConversation,
                GatewayChatConversation.id == GatewayChatRun.conversation_id,
            )
            .where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.org_id == store._require_org_id(),
                GatewayChatRun.user_id == (store.user_id or "local"),
                GatewayChatRun.project_id == claims.get("project_id"),
                GatewayChatRun.status == "running",
                GatewayChatRun.cancellation_requested_at.is_(None),
                GatewayChatConversation.commit_sha == claims.get("commit_sha"),
                GatewayChatConversation.branch == claims.get("branch"),
                GatewayChatConversation.surface == "standalone",
            )
        )
    ).one_or_none()
    if scoped is None:
        raise HTTPException(status_code=403, detail="Standalone query scope mismatch")
    run, conversation = scoped
    return GovernedQueryContext(
        path=path,  # type: ignore[arg-type]
        conversation_id=run.conversation_id,
        run_id=run.id,
        project_id=run.project_id,
        commit_sha=conversation.commit_sha,
        branch=conversation.branch,
        plan_id=plan_id,
    )


@router.post("/query/plan", dependencies=[RequireScope("query")])
async def plan_query(req: QueryPlanRequest, store: StoreD, request: Request):
    context = await _query_context(store, request, path="sdk")
    try:
        plan = await create_query_plan(
            store,
            connection_name=req.connection_name,
            sql=req.sql,
            purpose=req.purpose,
            context=context,
            row_level_analysis_justified=req.row_level_analysis_justified,
        )
    except QueryPlanError as exc:
        status = 404 if exc.code == "connection_not_found" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return plan.as_agent_dict()


@router.get("/query/plans/{plan_id}", dependencies=[RequireScope("query")])
async def get_query_plan(plan_id: str, store: StoreD, request: Request):
    context = await _query_context(store, request, path="sdk", plan_id=plan_id)
    owner_user_id = store.user_id or "local"
    plan = await store.session.get(GatewayQueryPlan, plan_id)
    if (
        plan is None
        or plan.org_id != store._require_org_id()
        or plan.user_id != owner_user_id
        or plan.run_id != context.run_id
        or plan.project_id != context.project_id
        or plan.commit_sha != context.commit_sha
        or plan.branch != context.branch
        or plan.expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(status_code=404, detail="Query plan not found")
    return {
        "route": plan.route,
        "approval_required": plan.approval_required,
    }


@router.get("/query/results/{result_id}", dependencies=[RequireScope("query")])
async def get_query_result(result_id: str, store: StoreD):
    if not enterprise_chat_feature_flags().structured_results:
        raise HTTPException(status_code=404, detail="Structured query results are not enabled")
    owner_user_id = store.user_id or "local"
    result = (
        await store.session.execute(
            select(GatewayStructuredQueryResult, GatewayGovernedQueryExecution)
            .outerjoin(
                GatewayGovernedQueryExecution,
                GatewayGovernedQueryExecution.id == GatewayStructuredQueryResult.execution_id,
            )
            .where(
                GatewayStructuredQueryResult.id == result_id,
                GatewayStructuredQueryResult.org_id == store._require_org_id(),
                GatewayStructuredQueryResult.owner_user_id == owner_user_id,
            )
        )
    ).one_or_none()
    if result is None:
        raise HTTPException(status_code=404, detail="Query result not found")
    stored, execution = result
    try:
        rows = await load_result_rows(stored)
    except QueryResultUnavailable as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "result_id": stored.id,
        "execution_id": execution.id if execution else None,
        "columns": stored.columns_json,
        "rows": rows,
        "query_row_count": stored.query_row_count,
        "saved_row_count": stored.saved_row_count,
        "completeness": stored.result_completeness,
        "truncation_reason": stored.truncation_reason,
        "provenance": stored.provenance_json,
        "freshness_at": stored.freshness_at,
    }


@router.post("/query/results/publish", dependencies=[RequireScope("query")])
async def publish_runtime_result(body: PublishResultRequest, store: StoreD, request: Request):
    flags = enterprise_chat_feature_flags()
    if not flags.runtime_results:
        raise HTTPException(status_code=404, detail="Runtime result publication is not enabled")
    context = await _query_context(store, request, path="sdk")
    if not context.run_id or not context.conversation_id:
        raise HTTPException(status_code=403, detail="Runtime result publication requires a chat run")
    owner_user_id = store.user_id or "local"
    if len(body.rows) > 100_000:
        raise HTTPException(status_code=413, detail="Derived result exceeds 100,000 rows")
    serialized = json.dumps(body.rows, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
    if len(serialized) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Derived result exceeds 10 MiB")
    source_rows = list(
        (
            await store.session.execute(
                select(GatewayStructuredQueryResult).where(
                    GatewayStructuredQueryResult.id.in_(body.source_result_ids),
                    GatewayStructuredQueryResult.org_id == store._require_org_id(),
                    GatewayStructuredQueryResult.owner_user_id == owner_user_id,
                    GatewayStructuredQueryResult.conversation_id == context.conversation_id,
                )
            )
        ).scalars()
    )
    if {row.id for row in source_rows} != set(body.source_result_ids):
        raise HTTPException(status_code=422, detail="Every source_result_id must belong to this conversation")
    incomplete = [
        row.id
        for row in source_rows
        if row.result_completeness != "complete" or row.source_completeness != "complete"
    ]
    if body.completeness == "complete" and incomplete and not (body.reconciliation or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Incomplete or unknown sources require documented reconciliation before a complete derived result",
        )
    columns = []
    if body.rows:
        for name in body.rows[0]:
            sample = next((row.get(name) for row in body.rows if row.get(name) is not None), None)
            logical_type = (
                "boolean"
                if isinstance(sample, bool)
                else "integer"
                if isinstance(sample, int)
                else "number"
                if isinstance(sample, float)
                else "unknown"
                if sample is None
                else type(sample).__name__.lower()
            )
            columns.append(
                {
                    "name": str(name),
                    "logical_type": logical_type,
                    "nullable": any(row.get(name) is None for row in body.rows),
                }
            )
    content_hash = hashlib.sha256(serialized).hexdigest()
    result_identity = "|".join(
        (
            context.run_id,
            body.code_hash,
            body.name,
            ",".join(sorted(body.source_result_ids)),
            body.completeness,
            content_hash,
        )
    )
    result_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"signalpilot-runtime-result:{result_identity}"))
    existing = await store.session.get(GatewayStructuredQueryResult, result_id)
    if existing is not None:
        if (
            existing.org_id != store._require_org_id()
            or existing.owner_user_id != owner_user_id
            or existing.run_id != context.run_id
            or existing.content_hash != content_hash
        ):
            raise HTTPException(status_code=409, detail="Runtime result identity conflict")
        return {
            "result_id": existing.id,
            "name": body.name,
            "row_count": existing.saved_row_count,
            "byte_size": existing.byte_size or len(serialized),
            "completeness": existing.result_completeness,
        }
    key = runtime_object_key(
        org_id=store._require_org_id(),
        conversation_id=context.conversation_id,
        run_id=context.run_id,
        category="derived-results",
        object_id=result_id,
        filename="rows.json",
    )
    stored = await chat_object_storage().put_bytes(
        key=key,
        data=serialized,
        content_type="application/json",
    )
    result = GatewayStructuredQueryResult(
        id=result_id,
        execution_id=None,
        org_id=store._require_org_id(),
        owner_user_id=owner_user_id,
        conversation_id=context.conversation_id,
        run_id=context.run_id,
        columns_json=columns,
        rows_json=[],
        preview_rows_json=body.rows[:200],
        storage_kind="object",
        object_key=stored.key,
        byte_size=stored.byte_size,
        content_hash=stored.content_hash,
        source_result_ids_json=body.source_result_ids,
        code_hash=body.code_hash,
        result_origin="runtime",
        query_row_count=len(body.rows),
        saved_row_count=len(body.rows),
        source_completeness=(
            "complete"
            if all(row.source_completeness == "complete" for row in source_rows)
            else "truncated"
            if any(row.source_completeness == "truncated" for row in source_rows)
            else "unknown"
        ),
        result_completeness=body.completeness,
        display_completeness="complete" if len(body.rows) <= 200 else "truncated",
        truncation_reason=(None if body.completeness == "complete" else "Derived result declared incomplete"),
        provenance_json={
            "name": body.name,
            "source_result_ids": body.source_result_ids,
            "code_hash": body.code_hash,
            "reconciliation": body.reconciliation,
            "project_id": context.project_id,
            "commit_sha": context.commit_sha,
        },
    )
    store.session.add(result)
    try:
        await store.session.commit()
    except IntegrityError as exc:
        await store.session.rollback()
        winner = await store.session.get(GatewayStructuredQueryResult, result_id)
        if (
            winner is not None
            and winner.org_id == store._require_org_id()
            and winner.owner_user_id == owner_user_id
            and winner.run_id == context.run_id
            and winner.content_hash == content_hash
        ):
            return {
                "result_id": winner.id,
                "name": body.name,
                "row_count": winner.saved_row_count,
                "byte_size": winner.byte_size or len(serialized),
                "completeness": winner.result_completeness,
            }
        with suppress(Exception):
            await chat_object_storage().delete(stored.key)
        raise HTTPException(status_code=409, detail="Runtime result identity conflict") from exc
    except Exception:
        await store.session.rollback()
        with suppress(Exception):
            await chat_object_storage().delete(stored.key)
        raise
    from gateway.store import standalone_chat as chat_store

    await chat_store.append_event(
        store.session,
        run_id=context.run_id,
        event_type="runtime_result_created",
        payload={"result_id": result.id, "name": body.name, "row_count": len(body.rows)},
    )
    return {
        "result_id": result.id,
        "name": body.name,
        "row_count": len(body.rows),
        "byte_size": stored.byte_size,
        "completeness": body.completeness,
    }


@router.post("/query/datasets", dependencies=[RequireScope("query")])
async def create_runtime_dataset(body: QueryDatasetRequest, store: StoreD, request: Request):
    if not enterprise_chat_feature_flags().dataset_refs:
        raise HTTPException(status_code=404, detail="DatasetRef execution is not enabled")
    context = await _query_context(store, request, path="sdk", plan_id=body.plan_id)
    settings = await store.load_settings()
    try:
        plan_id = body.plan_id
        if context.run_id and not plan_id:
            plan = await create_query_plan(
                store,
                connection_name=body.connection_name,
                sql=body.sql,
                purpose="Create a governed notebook dataset",
                context=context,
                row_level_analysis_justified=True,
            )
            if plan.route != "dataset_ref":
                raise RuntimeDatasetError(
                    "route_mismatch",
                    f"The query route is {plan.route}, not dataset_ref",
                )
            plan_id = plan.plan_id
            context = replace(context, plan_id=plan_id)
        if not plan_id:
            raise RuntimeDatasetError("plan_required", "DatasetRef execution requires a chat plan")
        dataset = await runtime_dataset_executor.execute(
            store,
            connection_name=body.connection_name,
            sql=body.sql,
            plan_id=plan_id,
            context=context,
            timeout_seconds=settings.default_timeout_seconds,
        )
    except RuntimeDatasetError as exc:
        status = 409 if exc.code == "aggregate_required" else 400
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
    return {
        "dataset_id": dataset.id,
        "schema": dataset.schema_json,
        "row_count": dataset.row_count,
        "byte_size": dataset.byte_size,
        "completeness": dataset.completeness,
        "expires_at": dataset.expires_at,
    }


@router.get("/query/datasets/{dataset_id}/content", dependencies=[RequireScope("query")])
async def get_runtime_dataset_content(dataset_id: str, store: StoreD):
    dataset = (
        await store.session.execute(
            select(GatewayRuntimeDataset).where(
                GatewayRuntimeDataset.id == dataset_id,
                GatewayRuntimeDataset.org_id == store._require_org_id(),
                GatewayRuntimeDataset.owner_user_id == (store.user_id or "local"),
                GatewayRuntimeDataset.expires_at > datetime.now(UTC),
            )
        )
    ).scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=404, detail="DatasetRef not found or expired")
    return StreamingResponse(
        chat_object_storage().iter_bytes(dataset.object_key),
        media_type="application/vnd.apache.parquet",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Length": str(dataset.byte_size),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/query/datasets/{dataset_id}/access", dependencies=[RequireScope("query")])
async def create_runtime_dataset_access(dataset_id: str, store: StoreD):
    dataset = (
        await store.session.execute(
            select(GatewayRuntimeDataset).where(
                GatewayRuntimeDataset.id == dataset_id,
                GatewayRuntimeDataset.org_id == store._require_org_id(),
                GatewayRuntimeDataset.owner_user_id == (store.user_id or "local"),
                GatewayRuntimeDataset.expires_at > datetime.now(UTC),
            )
        )
    ).scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=404, detail="DatasetRef not found or expired")
    return {
        "url": await chat_object_storage().presign_get(dataset.object_key, expires_seconds=300),
        "expires_in_seconds": 300,
    }


@router.post("/query/executions/{execution_id}/cancel", dependencies=[RequireScope("query")])
async def cancel_query_execution(execution_id: str, store: StoreD):
    owner_user_id = store.user_id or "local"
    execution = (
        await store.session.execute(
            select(GatewayGovernedQueryExecution).where(
                GatewayGovernedQueryExecution.id == execution_id,
                GatewayGovernedQueryExecution.org_id == store._require_org_id(),
                GatewayGovernedQueryExecution.user_id == owner_user_id,
            )
        )
    ).scalar_one_or_none()
    if execution is None:
        raise HTTPException(status_code=404, detail="Query execution not found")
    cancelled = await governed_query_executor.cancel(execution_id)
    if not cancelled:
        cancelled = await runtime_dataset_executor.cancel(execution_id)
    if cancelled:
        execution.status = "cancelled"
        execution.terminal_at = datetime.now(UTC)
        await store.session.commit()
    return {"execution_id": execution_id, "cancelled": cancelled}


@router.post("/query", dependencies=[RequireScope("query")])
async def query_database(req: DirectQueryRequest, store: StoreD, request: Request):
    _client_ip, _user_agent = request_meta(request)
    preliminary = validate_sql(req.sql)
    if not preliminary.ok:
        raise HTTPException(status_code=400, detail=f"Query blocked: {preliminary.blocked_reason}")
    settings = await store.load_settings()
    timeout = req.timeout_seconds or settings.default_timeout_seconds
    requested_path = "sdk" if request.headers.get("x-sp-query-path") == "sdk" else "direct_api"
    context = await _query_context(
        store,
        request,
        path=requested_path,
        plan_id=req.plan_id,
    )
    try:
        if context.run_id and requested_path == "sdk" and not context.plan_id:
            plan = await create_query_plan(
                store,
                connection_name=req.connection_name,
                sql=req.sql,
                purpose="Run a governed notebook query",
                context=context,
            )
            if plan.route != "notebook_sdk":
                raise GovernedQueryError(
                    "route_mismatch",
                    f"The query route is {plan.route}, not notebook_sdk",
                )
            context = replace(context, plan_id=plan.plan_id)
        result = await governed_query_executor.execute(
            store,
            connection_name=req.connection_name,
            sql=req.sql,
            row_limit=req.row_limit,
            timeout_seconds=timeout,
            context=context,
        )
    except GovernedQueryError as exc:
        status = 404 if exc.code == "connection_not_found" else 408 if exc.code == "query_timeout" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    return {
        "query_execution_id": result.execution_id,
        "result_id": result.result_id,
        "rows": result.rows,
        "row_count": result.row_count,
        "columns": result.columns,
        "tables": result.tables,
        "execution_ms": result.execution_ms,
        "sql_hash": result.sql_hash,
        "completeness": result.completeness,
        "truncation_reason": result.truncation_reason,
        "pii_redacted": result.pii_redacted or None,
        "cost_estimate": {
            "estimated_usd": round(result.estimated_cost_usd, 8),
            "warning": result.estimate_warning,
        },
    }


@router.post("/query/explain", dependencies=[RequireScope("query")])
async def explain_query(req: DirectQueryRequest, store: StoreD):
    """Explain a query without executing it — returns the query plan and cost estimate."""
    info = await store.get_connection(req.connection_name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{req.connection_name}' not found")

    conn_str = await store.get_connection_string(req.connection_name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    dialect = sqlglot_dialect(info.db_type)
    annotations = load_annotations(store.org_id, req.connection_name)
    blocked_tables = list(annotations.blocked_tables)
    settings = await store.load_settings()
    if settings.blocked_tables:
        blocked_tables.extend(t for t in settings.blocked_tables if t not in blocked_tables)
    validation = validate_sql(req.sql, blocked_tables=blocked_tables or None, dialect=dialect)
    if not validation.ok:
        raise HTTPException(status_code=400, detail=f"Query blocked: {validation.blocked_reason}")

    try:
        safe_sql = inject_limit(req.sql, req.row_limit, dialect=dialect)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Query blocked: {exc}") from exc

    try:
        extras = await store.get_credential_extras(req.connection_name)
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=req.connection_name
        ) as connector:
            from ..governance.cost_estimator import CostEstimator

            cost_estimate = await CostEstimator.estimate(connector, safe_sql, info.db_type)

        return {
            "connection_name": req.connection_name,
            "sql": safe_sql,
            "tables": validation.tables,
            "estimated_rows": cost_estimate.estimated_rows,
            "estimated_scan_rows": cost_estimate.estimated_scan_rows,
            "estimated_scan_bytes": cost_estimate.estimated_scan_bytes,
            "estimated_output_rows": cost_estimate.estimated_output_rows,
            "estimated_output_bytes": cost_estimate.estimated_output_bytes,
            "estimate_quality": cost_estimate.quality,
            "estimated_cost": cost_estimate.estimated_cost,
            "estimated_usd": round(cost_estimate.estimated_usd, 8),
            "is_expensive": cost_estimate.is_expensive,
            "warning": cost_estimate.warning,
            "plan": cost_estimate.raw_plan,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e)))
