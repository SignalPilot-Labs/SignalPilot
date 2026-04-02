"""Query route — governed SQL execution against connected databases."""

from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..connectors.health_monitor import health_monitor
from ..connectors.pool_manager import pool_manager
from ..engine import inject_limit, validate_sql
from ..governance.annotations import load_annotations
from ..governance.budget import budget_ledger
from ..governance.cache import query_cache
from ..models import AuditEntry
from ..store import (
    append_audit,
    get_connection,
    get_connection_string,
    load_settings,
)

router = APIRouter()


class DirectQueryRequest(BaseModel):
    connection_name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    sql: str = Field(..., min_length=1, max_length=100_000)
    row_limit: int = Field(default=10_000, ge=1, le=100_000)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)


def _sanitize_db_error(error: str) -> str:
    """Remove connection strings, passwords, and host info from error messages."""
    from ..main import _sanitize_db_error as _sanitize
    return _sanitize(error)


@router.post("/api/query")
async def query_database(req: DirectQueryRequest):
    info = get_connection(req.connection_name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{req.connection_name}' not found")

    settings = load_settings()
    timeout = req.timeout_seconds or settings.default_timeout_seconds

    # Load annotations for blocked tables check (Feature #19)
    annotations = load_annotations(req.connection_name)
    blocked_tables = list(annotations.blocked_tables)

    # Merge with settings-level blocked tables
    if settings.blocked_tables:
        blocked_tables.extend(t for t in settings.blocked_tables if t not in blocked_tables)

    # Validate SQL (with blocked tables from annotations + settings)
    validation = validate_sql(req.sql, blocked_tables=blocked_tables or None)
    if not validation.ok:
        await append_audit(AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type="block",
            connection_name=req.connection_name,
            sql=req.sql,
            blocked=True,
            block_reason=validation.blocked_reason,
        ))
        raise HTTPException(status_code=400, detail=f"Query blocked: {validation.blocked_reason}")

    # Inject LIMIT
    safe_sql = inject_limit(req.sql, req.row_limit)

    # Check query cache (Feature #30) — same normalized query returns cached result
    cached = query_cache.get(req.connection_name, req.sql, req.row_limit)
    if cached:
        await append_audit(AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type="query",
            connection_name=req.connection_name,
            sql=req.sql,
            tables=cached.tables,
            rows_returned=len(cached.rows),
            duration_ms=0.0,
            metadata={"cache_hit": True},
        ))
        return {
            "rows": cached.rows,
            "row_count": len(cached.rows),
            "tables": cached.tables,
            "execution_ms": cached.execution_ms,
            "sql_executed": cached.sql_executed,
            "cache_hit": True,
        }

    conn_str = get_connection_string(req.connection_name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    # Acquire connector once for both cost estimation and query execution (perf optimization)
    connector = await pool_manager.acquire(info.db_type, conn_str)

    try:
        # Cost estimation (Feature #13) — run EXPLAIN before execution
        cost_estimate = None
        try:
            from ..governance.cost_estimator import CostEstimator
            cost_estimate = await CostEstimator.estimate(connector, safe_sql, info.db_type)

            # Check budget before executing expensive queries
            if cost_estimate.is_expensive and cost_estimate.estimated_usd > 0:
                # Warn in audit log but don't block (policy-based blocking is a future feature)
                await append_audit(AuditEntry(
                    id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    event_type="query",
                    connection_name=req.connection_name,
                    sql=req.sql,
                    metadata={"cost_warning": True, "estimated_usd": cost_estimate.estimated_usd, "estimated_rows": cost_estimate.estimated_rows},
                ))
        except Exception:
            pass  # Cost estimation is best-effort

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
            sanitized = _sanitize_db_error(str(e))
            raise HTTPException(status_code=500, detail=sanitized)
    finally:
        await pool_manager.release(info.db_type, conn_str)

    elapsed_ms = (time.monotonic() - start) * 1000
    health_monitor.record(req.connection_name, elapsed_ms, True, db_type=info.db_type)

    # Apply PII redaction from annotations (Feature #15)
    from ..governance.pii import PIIRedactor
    pii_redactor = PIIRedactor()
    pii_columns = annotations.pii_columns
    for col_name, rule in pii_columns.items():
        pii_redactor.add_rule(col_name, rule)
    if pii_redactor.has_rules():
        rows = pii_redactor.redact_rows(rows)

    # Store in cache after PII redaction (so cached data is already redacted)
    query_cache.put(
        connection_name=req.connection_name,
        sql=req.sql,
        row_limit=req.row_limit,
        rows=rows,
        tables=validation.tables,
        execution_ms=elapsed_ms,
        sql_executed=safe_sql,
    )

    # Charge query cost to budget (Feature #11 + #12)
    query_cost_usd = (elapsed_ms / 1000) * 0.000014
    budget_ledger.charge("default", query_cost_usd)

    await append_audit(AuditEntry(
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
    ))

    response = {
        "rows": rows,
        "row_count": len(rows),
        "tables": validation.tables,
        "execution_ms": elapsed_ms,
        "sql_executed": safe_sql,
        "cache_hit": False,
        "pii_redacted": pii_redactor.last_redacted_columns if pii_redactor.last_redacted_columns else None,
    }
    if cost_estimate and not cost_estimate.warning:
        response["cost_estimate"] = {
            "estimated_rows": cost_estimate.estimated_rows,
            "estimated_usd": round(cost_estimate.estimated_usd, 8),
            "is_expensive": cost_estimate.is_expensive,
        }
    return response
