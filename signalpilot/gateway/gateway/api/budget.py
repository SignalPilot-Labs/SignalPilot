"""Budget and annotation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..auth import UserID
from ..connectors.pool_manager import pool_manager
from ..governance.annotations import generate_skeleton, load_annotations
from ..governance.budget import budget_ledger
from ..scope_guard import RequireScope
from .deps import StoreD, sanitize_db_error

router = APIRouter(prefix="/api")


class BudgetCreateRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    budget_usd: float = Field(default=10.0, ge=0.01, le=10_000.0)


@router.post("/budget", status_code=201, dependencies=[RequireScope("write")])
async def create_budget(_: UserID, req: BudgetCreateRequest):
    """Create a budget for a session."""
    budget = budget_ledger.create_session(req.session_id, req.budget_usd)
    return budget.to_dict()


@router.get("/budget/{session_id}", dependencies=[RequireScope("read")])
async def get_budget(_: UserID, session_id: str):
    """Get budget status for a session."""
    budget = budget_ledger.get_session(session_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Session budget not found")
    return budget.to_dict()


@router.get("/budget", dependencies=[RequireScope("read")])
async def list_budgets(_: UserID):
    """List all active session budgets."""
    return {
        "sessions": budget_ledger.get_all_sessions(),
        "total_spent_usd": round(budget_ledger.total_spent, 6),
    }


@router.delete("/budget/{session_id}", status_code=204, dependencies=[RequireScope("write")])
async def close_budget(_: UserID, session_id: str):
    """Close and remove a session budget."""
    closed = budget_ledger.close_session(session_id)
    if not closed:
        raise HTTPException(status_code=404, detail="Session budget not found")


# ─── Schema Annotations ────────────────────────────────────────────────────


@router.get("/connections/{name}/annotations", dependencies=[RequireScope("read")])
async def get_annotations(name: str, store: StoreD):
    """Get schema annotations for a connection (Feature #16)."""
    info = await store.get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    annotations = load_annotations(name)
    return annotations.to_dict()


@router.post("/connections/{name}/annotations/generate", dependencies=[RequireScope("write")])
async def generate_annotations(name: str, store: StoreD):
    """Generate a starter schema.yml from database introspection (Feature #29)."""
    info = await store.get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    try:
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            schema = await connector.get_schema()
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e)))

    skeleton = generate_skeleton(schema, name)
    return {
        "connection_name": name,
        "table_count": len(schema),
        "yaml": skeleton,
    }
