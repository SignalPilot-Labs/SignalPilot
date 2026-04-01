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
from .models import (
    AuditEntry,
    ConnectionCreate,
    ExecuteRequest,
    GatewaySettings,
    SandboxCreate,
)
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
    yield
    # Clean up on shutdown
    if _sandbox_client:
        await _sandbox_client.close()
    # Close all cached database connection pools
    if _connector_pool:
        await _close_all_pools()


app = FastAPI(
    title="SignalPilot Gateway",
    version="0.1.0",
    description="Governed MCP server for AI database access",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
async def test_connection_endpoint(name: str):
    from .connectors.registry import get_connector

    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        return {
            "status": "error",
            "message": "No credentials stored (restart gateway to reload)",
            "error_hint": "Credentials are stored in memory only. Re-create the connection to restore them.",
        }

    connector = get_connector(info.db_type)
    try:
        await connector.connect(conn_str, ssl=info.ssl)
        result = await connector.test_connection()
        await connector.close()

        # Update connection status in store
        _update_connection_status(name, "healthy" if result.healthy else "error")

        return {
            "status": "healthy" if result.healthy else "error",
            **result.to_dict(),
        }
    except Exception as e:
        _update_connection_status(name, "error")
        msg, hint = connector.friendly_error(e)
        return {
            "status": "error",
            "message": msg,
            "error_hint": hint,
        }


def _update_connection_status(name: str, status: str):
    """Update the stored status field for a connection."""
    import time as _time
    from .store import _load_json, _save_json, CONNECTIONS_FILE

    data = _load_json(CONNECTIONS_FILE, {})
    if name in data:
        data[name]["status"] = status
        data[name]["last_used"] = _time.time()
        _save_json(CONNECTIONS_FILE, data)


@app.get("/api/db-types")
async def get_db_types():
    """Return metadata about all supported database types for the frontend."""
    from .connectors.registry import list_supported_types
    return list_supported_types()


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


# ─── Persistent Connection Pool Cache ────────────────────────────────────────

from pydantic import BaseModel as _BaseModel
from .connectors.base import BaseConnector as _BaseConnector

_connector_pool: dict[str, _BaseConnector] = {}


async def _get_pooled_connector(name: str) -> _BaseConnector:
    """Get or create a persistent connector for the named connection.

    Reuses existing connection pools instead of creating a new pool per query,
    which is critical for performance under load.
    """
    from .connectors.registry import get_connector

    if name in _connector_pool:
        connector = _connector_pool[name]
        if await connector.health_check():
            return connector
        # Pool went stale — close and reconnect
        await connector.close()
        del _connector_pool[name]

    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    connector = get_connector(info.db_type)
    await connector.connect(conn_str, ssl=info.ssl)
    _connector_pool[name] = connector
    return connector


async def _close_all_pools():
    """Close all cached connection pools (called on shutdown)."""
    for connector in _connector_pool.values():
        try:
            await connector.close()
        except Exception:
            pass
    _connector_pool.clear()


# ─── Direct SQL Query ─────────────────────────────────────────────────────────


class DirectQueryRequest(_BaseModel):
    connection_name: str
    sql: str
    row_limit: int = 10_000


@app.post("/api/query")
async def query_database(req: DirectQueryRequest):
    info = get_connection(req.connection_name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{req.connection_name}' not found")

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

    connector = await _get_pooled_connector(req.connection_name)
    start = time.monotonic()
    try:
        rows = await connector.execute(safe_sql)
    except Exception as e:
        # Remove stale pool on error so next request reconnects
        _connector_pool.pop(req.connection_name, None)
        raise HTTPException(status_code=500, detail=str(e))

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
