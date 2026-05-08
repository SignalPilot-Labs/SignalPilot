"""Kernel session endpoints."""

from __future__ import annotations

import os
import time
import uuid

from fastapi import APIRouter, HTTPException

from ..auth import OrgID, UserID
from ..models import AuditEntry
from ..models.sessions import (
    CellResultResponse,
    SessionCreate,
    SessionExecuteRequest,
    SessionHistoryResponse,
    SessionInfoResponse,
)
from ..security.scope_guard import RequireScope
from ..store.sessions import (
    delete_session,
    get_session,
    list_sessions,
    upsert_session,
)
from .deps import StoreD, get_sandbox_client_with_store


def _gateway_url() -> str:
    return os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")

router = APIRouter(prefix="/api")


@router.get("/sessions", dependencies=[RequireScope("read")])
async def get_sessions(_: UserID, org_id: OrgID):
    return list_sessions(org_id)


@router.post("/sessions", status_code=201, dependencies=[RequireScope("execute")])
async def create_session(req: SessionCreate, store: StoreD):
    session_token = str(uuid.uuid4())
    org_id = store.org_id or ""

    client = await get_sandbox_client_with_store(store)
    result = await client.create_kernel_session(
        session_token=session_token,
        gateway_url=_gateway_url(),
    )

    session_info = SessionInfoResponse(
        id=result.get("session_id", str(uuid.uuid4())),
        org_id=org_id,
        status=result.get("status", "idle"),
        created_at=time.time(),
        last_active=time.time(),
        connection_name=req.connection_name,
        label=req.label,
    )
    upsert_session(session_info)

    await store.append_audit(
        AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type="session_create",
            connection_name=req.connection_name,
            metadata={"session_id": session_info.id, "label": req.label},
        )
    )
    return session_info


@router.get("/sessions/{session_id}", dependencies=[RequireScope("read")])
async def get_session_detail(_: UserID, org_id: OrgID, session_id: str):
    session = get_session(session_id, org_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    client = get_sandbox_client_from_cache()
    if client:
        try:
            remote = await client.get_kernel_session(session_id)
            session.status = remote.get("status", session.status)
            session.cell_count = remote.get("cell_count", session.cell_count)
            session.last_active = remote.get("last_active", session.last_active)
        except Exception:
            pass

    return session


@router.post("/sessions/{session_id}/execute", dependencies=[RequireScope("execute")])
async def execute_in_session(session_id: str, req: SessionExecuteRequest, store: StoreD):
    org_id = store.org_id or ""
    session = get_session(session_id, org_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    client = await get_sandbox_client_with_store(store)
    result = await client.execute_in_session(
        session_id=session_id,
        code=req.code,
        timeout=req.timeout,
        cell_id=req.cell_id,
    )

    session.last_active = time.time()
    session.cell_count = result.get("cell_count", session.cell_count + 1)
    session.status = result.get("session_status", "idle")
    upsert_session(session)

    await store.append_audit(
        AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type="session_execute",
            connection_name=session.connection_name,
            metadata={
                "session_id": session_id,
                "code_preview": req.code[:200],
                "success": result.get("success", False),
            },
        )
    )

    return CellResultResponse(
        success=result.get("success", False),
        output=result.get("output", ""),
        outputs=result.get("outputs"),
        error=result.get("error"),
        execution_ms=result.get("execution_ms"),
        execution_count=result.get("execution_count", 0),
        cell_id=result.get("cell_id"),
    )


@router.get("/sessions/{session_id}/history", dependencies=[RequireScope("read")])
async def get_session_history(session_id: str, _: UserID, org_id: OrgID):
    session = get_session(session_id, org_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    client = get_sandbox_client_from_cache()
    cells: list[CellResultResponse] = []
    if client:
        try:
            data = await client.get_session_history(session_id)
            cells = [
                CellResultResponse(
                    success=c.get("success", False),
                    output=c.get("output", ""),
                    outputs=c.get("outputs"),
                    error=c.get("error"),
                    execution_ms=c.get("execution_ms"),
                    execution_count=c.get("execution_count", 0),
                    cell_id=c.get("cell_id"),
                )
                for c in data.get("cells", [])
            ]
        except Exception:
            pass

    return SessionHistoryResponse(session_id=session_id, cells=cells)


@router.delete("/sessions/{session_id}", status_code=204, dependencies=[RequireScope("execute")])
async def kill_session(session_id: str, store: StoreD):
    org_id = store.org_id or ""
    session = get_session(session_id, org_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    client = await get_sandbox_client_with_store(store)
    await client.delete_kernel_session(session_id)
    delete_session(session_id, org_id)


@router.post("/sessions/{session_id}/restart", dependencies=[RequireScope("execute")])
async def restart_session(session_id: str, store: StoreD):
    org_id = store.org_id or ""
    session = get_session(session_id, org_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session_token = str(uuid.uuid4())
    client = await get_sandbox_client_with_store(store)
    result = await client.restart_kernel_session(
        session_id=session_id,
        session_token=session_token,
        gateway_url=_gateway_url(),
    )

    session.status = result.get("status", "idle")
    session.cell_count = 0
    session.last_active = time.time()
    upsert_session(session)
    return session


def get_sandbox_client_from_cache():
    """Get existing sandbox client without store (for read-only ops)."""
    from .deps import _sandbox_client
    return _sandbox_client
