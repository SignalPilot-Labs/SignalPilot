"""Governance routes — budget, cache, annotations, and PII detection."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..connectors.pool_manager import pool_manager
from ..connectors.schema_cache import schema_cache
from ..governance.annotations import generate_skeleton, load_annotations
from ..governance.budget import budget_ledger
from ..governance.cache import query_cache
from ..store import get_connection, get_connection_string

router = APIRouter()


def _sanitize_db_error(error: str) -> str:
    from ..main import _sanitize_db_error as _sanitize
    return _sanitize(error)


# ─── Budget ─────────────────────────────────────────────────────────────────


class BudgetCreateRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    budget_usd: float = Field(default=10.0, ge=0.01, le=10_000.0)


@router.post("/api/budget", status_code=201)
async def create_budget(req: BudgetCreateRequest):
    """Create a budget for a session."""
    budget = budget_ledger.create_session(req.session_id, req.budget_usd)
    return budget.to_dict()


@router.get("/api/budget/{session_id}")
async def get_budget(session_id: str):
    """Get budget status for a session."""
    budget = budget_ledger.get_session(session_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Session budget not found")
    return budget.to_dict()


@router.get("/api/budget")
async def list_budgets():
    """List all active session budgets."""
    return {
        "sessions": budget_ledger.get_all_sessions(),
        "total_spent_usd": round(budget_ledger.total_spent, 6),
    }


@router.delete("/api/budget/{session_id}", status_code=204)
async def close_budget(session_id: str):
    """Close and remove a session budget."""
    closed = budget_ledger.close_session(session_id)
    if not closed:
        raise HTTPException(status_code=404, detail="Session budget not found")


# ─── Schema Annotations ────────────────────────────────────────────────────


@router.get("/api/connections/{name}/annotations")
async def get_annotations(name: str):
    """Get schema annotations for a connection (Feature #16)."""
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    annotations = load_annotations(name)
    return annotations.to_dict()


@router.post("/api/connections/{name}/annotations/generate")
async def generate_annotations_endpoint(name: str):
    """Generate a starter schema.yml from database introspection (Feature #29)."""
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    try:
        connector = await pool_manager.acquire(info.db_type, conn_str)
        try:
            schema = await connector.get_schema()
        finally:
            await pool_manager.release(info.db_type, conn_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))

    skeleton = generate_skeleton(schema, name)
    return {
        "connection_name": name,
        "table_count": len(schema),
        "yaml": skeleton,
    }


# ─── Query Cache ────────────────────────────────────────────────────────────


@router.get("/api/cache/stats")
async def cache_stats():
    """Get query cache statistics (Feature #30)."""
    return query_cache.stats()


@router.post("/api/cache/invalidate", status_code=200)
async def invalidate_cache(connection_name: str | None = None):
    """Invalidate cached query results. Optionally filter by connection."""
    count = query_cache.invalidate(connection_name)
    return {"invalidated": count, "connection_name": connection_name}


# ─── PII Detection ──────────────────────────────────────────────────────────


@router.post("/api/connections/{name}/detect-pii")
async def detect_pii(name: str):
    """Auto-detect PII columns in a database schema based on naming patterns.

    Returns suggested PII rules for columns with names matching known
    PII patterns (email, ssn, phone, etc.). Results should be reviewed
    and saved to schema.yml annotations.
    """
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    # Get schema (from cache if available)
    cached_schema = schema_cache.get(name)
    if cached_schema is None:
        try:
            connector = await pool_manager.acquire(info.db_type, conn_str)
            try:
                cached_schema = await connector.get_schema()
            finally:
                await pool_manager.release(info.db_type, conn_str)
            schema_cache.put(name, cached_schema)
        except Exception as e:
            raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))

    from ..governance.pii import detect_pii_columns

    all_detections: dict[str, dict[str, str]] = {}
    for table_key, table_data in cached_schema.items():
        columns = [col["name"] for col in table_data.get("columns", [])]
        detected = detect_pii_columns(columns)
        if detected:
            all_detections[table_data.get("name", table_key)] = {
                col: rule.value for col, rule in detected.items()
            }

    return {
        "connection_name": name,
        "tables_scanned": len(cached_schema),
        "tables_with_pii": len(all_detections),
        "detections": all_detections,
    }


# ─── Schema Cache ───────────────────────────────────────────────────────────


@router.get("/api/schema-cache/stats")
async def schema_cache_stats():
    """Get schema cache statistics (Feature #18)."""
    return schema_cache.stats()


@router.post("/api/schema-cache/invalidate", status_code=200)
async def invalidate_schema_cache(connection_name: str | None = None):
    """Invalidate cached schema data. Optionally filter by connection."""
    count = schema_cache.invalidate(connection_name)
    return {"invalidated": count, "connection_name": connection_name}
