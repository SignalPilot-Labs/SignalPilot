"""
SignalPilot Gateway — FastAPI application.

Endpoints:
  GET  /health
  GET  /api/settings          GET/PUT gateway settings (BYOF config)
  PUT  /api/settings
  GET  /api/connections        list connections
  POST /api/connections        create connection
  GET  /api/connections/{name} get connection details
  DELETE /api/connections/{name}
  POST /api/connections/{name}/test

  GET  /api/sandboxes          list active sandboxes
  POST /api/sandboxes          create sandbox
  GET  /api/sandboxes/{id}     get sandbox details
  DELETE /api/sandboxes/{id}   kill sandbox
  POST /api/sandboxes/{id}/execute  run code

  POST /api/query              governed SQL query (direct DB)

  GET  /api/audit              audit log
  GET  /api/metrics            SSE live metrics stream
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .engine import inject_limit, validate_sql
from .middleware import APIKeyAuthMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware
from .models import (
    AuditEntry,
    ConnectionCreate,
    ExecuteRequest,
    GatewaySettings,
    SandboxCreate,
)
from .connectors.pool_manager import pool_manager
from .sandbox_client import SandboxClient
from .store import (
    append_audit,
    create_connection,
    delete_connection,
    delete_sandbox,
    get_connection,
    get_connection_string,
    get_sandbox,
    list_connections,
    list_sandboxes,
    load_settings,
    read_audit,
    save_settings,
    upsert_sandbox,
)

# ─── Error Sanitization (HIGH-06) ────────────────────────────────────────────

import re as _re

_SENSITIVE_PATTERNS = [
    _re.compile(r"postgresql://[^\s]+", _re.IGNORECASE),
    _re.compile(r"mysql://[^\s]+", _re.IGNORECASE),
    _re.compile(r"password[=:]\s*\S+", _re.IGNORECASE),
    _re.compile(r"host=\S+", _re.IGNORECASE),
]


def _sanitize_db_error(error: str) -> str:
    """Remove connection strings, passwords, and host info from error messages."""
    sanitized = error
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    # Truncate to prevent information dump
    if len(sanitized) > 500:
        sanitized = sanitized[:500] + "..."
    return sanitized


# ─── Global sandbox client (recreated when settings change) ──────────────────

_sandbox_client: SandboxClient | None = None


def _get_sandbox_client() -> SandboxClient:
    global _sandbox_client
    if _sandbox_client is None:
        settings = load_settings()
        _sandbox_client = SandboxClient(
            base_url=settings.sandbox_manager_url,
            api_key=settings.sandbox_api_key,
        )
    return _sandbox_client


def _reset_sandbox_client():
    global _sandbox_client
    if _sandbox_client is not None:
        asyncio.create_task(_sandbox_client.close())
    _sandbox_client = None


# ─── App ─────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background pool cleanup task
    async def _pool_cleanup_loop():
        while True:
            await asyncio.sleep(60)
            await pool_manager.cleanup_idle()

    cleanup_task = asyncio.create_task(_pool_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        await pool_manager.close_all()
        if _sandbox_client:
            await _sandbox_client.close()


app = FastAPI(
    title="SignalPilot Gateway",
    version="0.1.0",
    description="Governed MCP server for AI database access",
    lifespan=lifespan,
)

# CORS — restrict to known origins instead of wildcard (CRIT-02 fix)
_ALLOWED_ORIGINS = [
    "http://localhost:3200",
    "http://localhost:3000",
    "http://127.0.0.1:3200",
    "http://127.0.0.1:3000",
]
# Allow override via env var for production deployments
import os as _os
_extra_origins = _os.getenv("SP_ALLOWED_ORIGINS", "")
if _extra_origins:
    _ALLOWED_ORIGINS.extend(o.strip() for o in _extra_origins.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    allow_credentials=True,
)

# Security middleware stack (order matters: outermost runs first)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, general_rpm=120, expensive_rpm=30)
app.add_middleware(APIKeyAuthMiddleware)


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    settings = load_settings()
    sandbox_status = "unknown"
    try:
        client = _get_sandbox_client()
        data = await client.health()
        sandbox_status = data.get("status", "unknown")
    except Exception as e:
        sandbox_status = f"error: {e}"

    return {
        "status": "healthy",
        "version": "0.1.0",
        "sandbox_manager": settings.sandbox_manager_url,
        "sandbox_status": sandbox_status,
        "active_sandboxes": len(list_sandboxes()),
        "connections": len(list_connections()),
    }


# ─── Settings ────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    return load_settings()


@app.put("/api/settings")
async def update_settings(settings: GatewaySettings):
    save_settings(settings)
    _reset_sandbox_client()  # Reconnect with new URL
    return settings


# ─── Connections ─────────────────────────────────────────────────────────────

@app.get("/api/connections")
async def get_connections():
    return list_connections()


@app.post("/api/connections", status_code=201)
async def add_connection(conn: ConnectionCreate):
    try:
        info = create_connection(conn)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return info


@app.get("/api/connections/{name}")
async def get_connection_detail(name: str):
    conn = get_connection(name)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    return conn


@app.delete("/api/connections/{name}", status_code=204)
async def remove_connection(name: str):
    if not delete_connection(name):
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")


@app.post("/api/connections/{name}/test")
async def test_connection(name: str):
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        return {"status": "error", "message": "No credentials stored (restart gateway to reload)"}

    try:
        connector = await pool_manager.acquire(info.db_type, conn_str)
        ok = await connector.health_check()
        await pool_manager.release(info.db_type, conn_str)
        return {"status": "healthy" if ok else "error", "message": "Connection test passed" if ok else "Health check failed"}
    except Exception as e:
        return {"status": "error", "message": _sanitize_db_error(str(e))}


# ─── Sandboxes ───────────────────────────────────────────────────────────────

@app.get("/api/sandboxes")
async def get_sandboxes():
    return list_sandboxes()


@app.post("/api/sandboxes", status_code=201)
async def create_sandbox(req: SandboxCreate):
    session_token = str(uuid.uuid4())
    settings = load_settings()

    client = _get_sandbox_client()
    sandbox = await client.create_sandbox(
        session_token=session_token,
        connection_name=req.connection_name,
        label=req.label,
        budget_usd=req.budget_usd,
        row_limit=req.row_limit,
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


@app.get("/api/sandboxes/{sandbox_id}")
async def get_sandbox_detail(sandbox_id: str):
    sandbox = get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return sandbox


@app.delete("/api/sandboxes/{sandbox_id}", status_code=204)
async def kill_sandbox(sandbox_id: str):
    sandbox = get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if sandbox.vm_id:
        client = _get_sandbox_client()
        await client.kill(sandbox.vm_id)

    delete_sandbox(sandbox_id)


@app.post("/api/sandboxes/{sandbox_id}/execute")
async def execute_in_sandbox(sandbox_id: str, req: ExecuteRequest):
    sandbox = get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if sandbox.status == "stopped":
        raise HTTPException(status_code=409, detail="Sandbox has been stopped")

    settings = load_settings()
    session_token = str(uuid.uuid4())  # In production, this is tied to the session

    client = _get_sandbox_client()
    result = await client.execute(
        sandbox=sandbox,
        code=req.code,
        session_token=session_token,
        timeout=req.timeout,
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


# ─── Direct SQL Query ─────────────────────────────────────────────────────────

class QueryRequest(ConnectionCreate.__class__):
    pass


from pydantic import BaseModel, Field


class DirectQueryRequest(BaseModel):
    connection_name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    sql: str = Field(..., min_length=1, max_length=100_000)
    row_limit: int = Field(default=10_000, ge=1, le=100_000)


@app.post("/api/query")
async def query_database(req: DirectQueryRequest):
    info = get_connection(req.connection_name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{req.connection_name}' not found")

    settings = load_settings()

    # Validate SQL
    validation = validate_sql(req.sql)
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

    conn_str = get_connection_string(req.connection_name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    start = time.monotonic()
    try:
        connector = await pool_manager.acquire(info.db_type, conn_str)
        rows = await connector.execute(safe_sql)
        await pool_manager.release(info.db_type, conn_str)
    except Exception as e:
        # Sanitize error message — never expose connection strings or internal details (HIGH-06)
        sanitized = _sanitize_db_error(str(e))
        raise HTTPException(status_code=500, detail=sanitized)

    elapsed_ms = (time.monotonic() - start) * 1000

    await append_audit(AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        event_type="query",
        connection_name=req.connection_name,
        sql=req.sql,
        tables=validation.tables,
        rows_returned=len(rows),
        duration_ms=elapsed_ms,
    ))

    return {
        "rows": rows,
        "row_count": len(rows),
        "tables": validation.tables,
        "execution_ms": elapsed_ms,
        "sql_executed": safe_sql,
    }


# ─── Audit ───────────────────────────────────────────────────────────────────

@app.get("/api/audit")
async def get_audit(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
    connection_name: str | None = None,
    event_type: str | None = None,
):
    entries = await read_audit(
        limit=limit,
        offset=offset,
        connection_name=connection_name,
        event_type=event_type,
    )
    return {"entries": entries, "total": len(entries)}


# ─── Metrics SSE ─────────────────────────────────────────────────────────────

@app.get("/api/metrics")
async def metrics_stream():
    """Server-Sent Events stream of live gateway metrics."""

    async def generate():
        while True:
            settings = load_settings()
            sandboxes = list_sandboxes()
            running = sum(1 for s in sandboxes if s.status == "running")

            sandbox_health = "unknown"
            try:
                client = _get_sandbox_client()
                data = await client.health()
                sandbox_health = data.get("status", "unknown")
                kvm_available = data.get("kvm_available", False)
                active_vms = data.get("active_vms", 0)
                max_vms = data.get("max_vms", 10)
            except Exception:
                kvm_available = False
                active_vms = 0
                max_vms = 10

            payload = {
                "timestamp": time.time(),
                "sandbox_manager": settings.sandbox_manager_url,
                "sandbox_health": sandbox_health,
                "kvm_available": kvm_available,
                "active_sandboxes": len(sandboxes),
                "running_sandboxes": running,
                "active_vms": active_vms,
                "max_vms": max_vms,
                "connections": len(list_connections()),
            }

            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(generate(), media_type="text/event-stream")
