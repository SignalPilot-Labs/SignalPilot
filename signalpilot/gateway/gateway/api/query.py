"""Query endpoints — POST /api/query and POST /api/query/explain."""

from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..connectors.health_monitor import health_monitor
from ..connectors.pool_manager import pool_manager
from ..engine import inject_limit, validate_sql
from ..errors import query_error_hint
from ..governance.annotations import load_annotations
from ..governance.budget import budget_ledger
from ..models import AuditEntry
from ..scope_guard import RequireScope
from ..governance.plan_limits import check_query_limit, record_query, get_org_limits
from .deps import SQLGLOT_DIALECTS, StoreD, sanitize_db_error

router = APIRouter(prefix="/api")


class DirectQueryRequest(BaseModel):
    connection_name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    sql: str = Field(..., min_length=1, max_length=100_000)
    row_limit: int = Field(default=10_000, ge=1, le=100_000)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)


@router.post("/query", dependencies=[RequireScope("query")])
async def query_database(req: DirectQueryRequest, store: StoreD, request: Request):
    _client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else None)
    _user_agent = request.headers.get("user-agent")

    # Enforce daily query limit based on org's plan tier
    plan = await get_org_limits(store.org_id)
    check_query_limit(store.org_id, plan)

    info = await store.get_connection(req.connection_name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{req.connection_name}' not found")

    settings = await store.load_settings()
    timeout = req.timeout_seconds or settings.default_timeout_seconds

    # Load annotations for blocked tables check
    annotations = load_annotations(store.org_id, req.connection_name)
    blocked_tables = list(annotations.blocked_tables)

    if settings.blocked_tables:
        blocked_tables.extend(t for t in settings.blocked_tables if t not in blocked_tables)

    dialect = SQLGLOT_DIALECTS.get(info.db_type, "postgres")

    validation = validate_sql(req.sql, blocked_tables=blocked_tables or None, dialect=dialect)
    if not validation.ok:
        await store.append_audit(AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type="block",
            connection_name=req.connection_name,
            sql=req.sql,
            blocked=True,
            block_reason=validation.blocked_reason,
            client_ip=_client_ip,
            user_agent=_user_agent,
        ))
        raise HTTPException(status_code=400, detail=f"Query blocked: {validation.blocked_reason}")

    safe_sql = inject_limit(req.sql, req.row_limit, dialect=dialect)

    conn_str = await store.get_connection_string(req.connection_name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    extras = await store.get_credential_extras(req.connection_name)
    connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)

    try:
        # Cost estimation — run EXPLAIN before execution
        cost_estimate = None
        try:
            from ..governance.cost_estimator import CostEstimator
            cost_estimate = await CostEstimator.estimate(connector, safe_sql, info.db_type)
        except Exception:
            pass

        start = time.monotonic()
        try:
            rows = await connector.execute(safe_sql, timeout=timeout)
        except asyncio.TimeoutError:
            health_monitor.record(req.connection_name, (time.monotonic() - start) * 1000, False, "timeout", info.db_type)
            raise HTTPException(
                status_code=408,
                detail=f"Query timed out after {timeout}s. Consider adding more specific WHERE clauses or reducing the scope.",
            )
        except Exception as e:
            health_monitor.record(req.connection_name, (time.monotonic() - start) * 1000, False, str(e)[:200], info.db_type)
            sanitized = sanitize_db_error(str(e))
            hint = query_error_hint(str(e), info.db_type)
            detail = {"error": sanitized, "hint": hint} if hint else sanitized
            raise HTTPException(status_code=500, detail=detail)
    finally:
        await pool_manager.release(info.db_type, conn_str)

    elapsed_ms = (time.monotonic() - start) * 1000
    health_monitor.record(req.connection_name, elapsed_ms, True, db_type=info.db_type)

    # Apply PII redaction
    from ..governance.pii import PIIRedactor
    pii_redactor = PIIRedactor()
    if info.pii_enabled and info.pii_rules:
        for col_name, rule in info.pii_rules.items():
            pii_redactor.add_rule(col_name, rule)
    for col_name, rule in annotations.pii_columns.items():
        pii_redactor.add_rule(col_name, rule)
    if pii_redactor.has_rules():
        rows = pii_redactor.redact_rows(rows)

    record_query(store.org_id)

    query_cost_usd = (elapsed_ms / 1000) * 0.000014
    await budget_ledger.charge("default", query_cost_usd)

    await store.append_audit(AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        event_type="query",
        connection_name=req.connection_name,
        sql=req.sql,
        tables=validation.tables,
        rows_returned=len(rows),
        duration_ms=elapsed_ms,
        cost_usd=query_cost_usd,
        metadata={"pii_redacted": pii_redactor.last_redacted_columns} if pii_redactor.last_redacted_columns else {},
        client_ip=_client_ip,
        user_agent=_user_agent,
    ))

    response = {
        "rows": rows,
        "row_count": len(rows),
        "tables": validation.tables,
        "execution_ms": elapsed_ms,
        "sql_executed": safe_sql,
        "pii_redacted": pii_redactor.last_redacted_columns if pii_redactor.last_redacted_columns else None,
    }
    if cost_estimate and not cost_estimate.warning:
        response["cost_estimate"] = {
            "estimated_rows": cost_estimate.estimated_rows,
            "estimated_usd": round(cost_estimate.estimated_usd, 8),
            "is_expensive": cost_estimate.is_expensive,
        }
    if info.db_type == "bigquery":
        try:
            from ..connectors.bigquery import BigQueryConnector
            if isinstance(connector, BigQueryConnector):
                job_stats = connector.get_last_job_stats()
                if job_stats:
                    response["bigquery_stats"] = job_stats
        except Exception:
            pass
    return response


@router.post("/query/explain", dependencies=[RequireScope("query")])
async def explain_query(req: DirectQueryRequest, store: StoreD):
    """Explain a query without executing it — returns the query plan and cost estimate."""
    info = await store.get_connection(req.connection_name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{req.connection_name}' not found")

    conn_str = await store.get_connection_string(req.connection_name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    dialect = SQLGLOT_DIALECTS.get(info.db_type, "postgres")
    annotations = load_annotations(store.org_id, req.connection_name)
    blocked_tables = list(annotations.blocked_tables)
    settings = await store.load_settings()
    if settings.blocked_tables:
        blocked_tables.extend(t for t in settings.blocked_tables if t not in blocked_tables)
    validation = validate_sql(req.sql, blocked_tables=blocked_tables or None, dialect=dialect)
    if not validation.ok:
        raise HTTPException(status_code=400, detail=f"Query blocked: {validation.blocked_reason}")

    safe_sql = inject_limit(req.sql, req.row_limit, dialect=dialect)

    try:
        extras = await store.get_credential_extras(req.connection_name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            from ..governance.cost_estimator import CostEstimator
            cost_estimate = await CostEstimator.estimate(connector, safe_sql, info.db_type)

        return {
            "connection_name": req.connection_name,
            "sql": safe_sql,
            "tables": validation.tables,
            "estimated_rows": cost_estimate.estimated_rows,
            "estimated_cost": cost_estimate.estimated_cost,
            "estimated_usd": round(cost_estimate.estimated_usd, 8),
            "is_expensive": cost_estimate.is_expensive,
            "warning": cost_estimate.warning,
            "plan": cost_estimate.raw_plan,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e)))
