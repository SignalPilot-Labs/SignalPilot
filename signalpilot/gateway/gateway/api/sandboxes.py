"""Sandbox management endpoints."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, HTTPException

from ..models import AuditEntry, ExecuteRequest, SandboxCreate
from ..scope_guard import RequireScope
from ..store import (
    delete_sandbox,
    get_sandbox,
    list_sandboxes,
    upsert_sandbox,
)
from .deps import StoreD, get_sandbox_client_with_store

router = APIRouter(prefix="/api")


@router.get("/sandboxes", dependencies=[RequireScope("read")])
async def get_sandboxes():
    return list_sandboxes()


@router.post("/sandboxes", status_code=201, dependencies=[RequireScope("execute")])
async def create_sandbox(req: SandboxCreate, store: StoreD):
    session_token = str(uuid.uuid4())

    client = await get_sandbox_client_with_store(store)
    sandbox = await client.create_sandbox(
        session_token=session_token,
        connection_name=req.connection_name,
        label=req.label,
        budget_usd=req.budget_usd,
        row_limit=req.row_limit,
    )
    upsert_sandbox(sandbox)

    await store.append_audit(AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        event_type="connect",
        connection_name=req.connection_name,
        sandbox_id=sandbox.id,
        metadata={"label": req.label},
    ))

    return sandbox


@router.get("/sandboxes/{sandbox_id}", dependencies=[RequireScope("read")])
async def get_sandbox_detail(sandbox_id: str):
    sandbox = get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return sandbox


@router.delete("/sandboxes/{sandbox_id}", status_code=204, dependencies=[RequireScope("execute")])
async def kill_sandbox(sandbox_id: str, store: StoreD):
    sandbox = get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if sandbox.vm_id:
        client = await get_sandbox_client_with_store(store)
        await client.kill(sandbox.vm_id)

    delete_sandbox(sandbox_id)


@router.post("/sandboxes/{sandbox_id}/execute", dependencies=[RequireScope("execute")])
async def execute_in_sandbox(sandbox_id: str, req: ExecuteRequest, store: StoreD):
    sandbox = get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if sandbox.status == "stopped":
        raise HTTPException(status_code=409, detail="Sandbox has been stopped")

    session_token = str(uuid.uuid4())  # In production, this is tied to the session

    client = await get_sandbox_client_with_store(store)
    result = await client.execute(
        sandbox=sandbox,
        code=req.code,
        session_token=session_token,
        timeout=req.timeout,
    )

    # Update sandbox state
    upsert_sandbox(sandbox)

    await store.append_audit(AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        event_type="execute",
        connection_name=sandbox.connection_name,
        sandbox_id=sandbox_id,
        metadata={"code_preview": req.code[:200], "success": result.success},
    ))

    return result
