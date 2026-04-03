"""Sandbox management endpoints."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, HTTPException

from ..models import AuditEntry, ExecuteRequest, SandboxCreate
from ..store import (
    delete_sandbox,
    get_sandbox,
    list_sandboxes,
    load_settings,
    upsert_sandbox,
    append_audit,
)
from .deps import get_sandbox_client, ResourceID

router = APIRouter(prefix="/api")


@router.get("/sandboxes")
async def get_sandboxes():
    return list_sandboxes()


@router.post("/sandboxes", status_code=201)
async def create_sandbox(req: SandboxCreate):
    session_token = str(uuid.uuid4())
    settings = load_settings()

    client = get_sandbox_client()
    try:
        sandbox = await client.create_sandbox(
            session_token=session_token,
            connection_name=req.connection_name,
            label=req.label,
            budget_usd=req.budget_usd,
            row_limit=req.row_limit,
        )
    except Exception as e:
        error_msg = str(e)[:200]
        raise HTTPException(
            status_code=502,
            detail=f"Failed to create sandbox: {error_msg}",
        )
    upsert_sandbox(sandbox)

    await append_audit(AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        event_type="connect",
        connection_name=req.connection_name,
        sandbox_id=sandbox.id,
        metadata={"label": req.label},
    ))

    return sandbox


@router.get("/sandboxes/{sandbox_id}")
async def get_sandbox_detail(sandbox_id: ResourceID):
    sandbox = get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return sandbox


@router.delete("/sandboxes/{sandbox_id}", status_code=204)
async def kill_sandbox(sandbox_id: ResourceID):
    sandbox = get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if sandbox.vm_id:
        client = get_sandbox_client()
        try:
            await client.kill(sandbox.vm_id)
        except Exception as e:
            # Log but don't block deletion — the sandbox record should still be cleaned up
            import logging
            logging.getLogger(__name__).warning("Failed to kill sandbox VM %s: %s", sandbox.vm_id, str(e)[:200])

    delete_sandbox(sandbox_id)


@router.post("/sandboxes/{sandbox_id}/execute")
async def execute_in_sandbox(sandbox_id: ResourceID, req: ExecuteRequest):
    sandbox = get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if sandbox.status == "stopped":
        raise HTTPException(status_code=409, detail="Sandbox has been stopped")

    settings = load_settings()
    session_token = str(uuid.uuid4())  # In production, this is tied to the session

    client = get_sandbox_client()
    try:
        result = await client.execute(
            sandbox=sandbox,
            code=req.code,
            session_token=session_token,
            timeout=req.timeout,
        )
    except Exception as e:
        # Sanitize error to avoid leaking sandbox infrastructure details
        error_msg = str(e)[:200]
        raise HTTPException(
            status_code=502,
            detail=f"Sandbox execution failed: {error_msg}",
        )

    # Update sandbox state
    upsert_sandbox(sandbox)

    await append_audit(AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        event_type="execute",
        connection_name=sandbox.connection_name,
        sandbox_id=sandbox_id,
        metadata={"code_preview": req.code[:200], "success": result.success},
    ))

    return result
