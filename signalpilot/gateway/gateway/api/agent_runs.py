"""Agent run tracking endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..models.workspace import AgentRunCreate, AgentRunInfo, AgentRunUpdate
from ..security.scope_guard import RequireScope
from .deps import StoreD

router = APIRouter(prefix="/api")


@router.post("/agent-runs", status_code=201, response_model=AgentRunInfo, dependencies=[RequireScope("write")])
async def create_run(body: AgentRunCreate, store: StoreD):
    return await store.create_agent_run(
        project_id=body.project_id,
        conversation_id=body.conversation_id,
        agent_type=body.agent_type,
        input_json=body.input_json,
        metadata_json=body.metadata_json,
    )


@router.get("/agent-runs", dependencies=[RequireScope("read")])
async def list_runs(
    store: StoreD,
    project_id: str | None = Query(None),
    status: str | None = Query(None, max_length=20),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    runs, total = await store.list_agent_runs(project_id=project_id, status=status, limit=limit, offset=offset)
    return {"runs": runs, "total": total}


@router.get("/agent-runs/{run_id}", response_model=AgentRunInfo, dependencies=[RequireScope("read")])
async def get_run(run_id: str, store: StoreD):
    run = await store.get_agent_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


@router.patch("/agent-runs/{run_id}", response_model=AgentRunInfo, dependencies=[RequireScope("write")])
async def update_run(run_id: str, body: AgentRunUpdate, store: StoreD):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    run = await store.update_agent_run(run_id, updates)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run
