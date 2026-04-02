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
import os
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .middleware import APIKeyAuthMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware
from .models import ConnectionCreate, GatewaySettings
from .connectors.pool_manager import pool_manager
from .connectors.health_monitor import health_monitor
from .connectors.schema_cache import schema_cache
from .sandbox_client import SandboxClient
from .store import (
    create_connection,
    delete_connection,
    get_connection,
    get_connection_string,
    list_connections,
    list_sandboxes,
    load_settings,
    save_settings,
)

# ─── Error Sanitization (HIGH-06) ────────────────────────────────────────────

_SENSITIVE_PATTERNS = [
    re.compile(r"postgresql://[^\s]+", re.IGNORECASE),
    re.compile(r"mysql://[^\s]+", re.IGNORECASE),
    re.compile(r"password[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"host=\S+", re.IGNORECASE),
]


def _sanitize_db_error(error: str) -> str:
    """Remove connection strings, passwords, and host info from error messages."""
    sanitized = error
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
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
_extra_origins = os.getenv("SP_ALLOWED_ORIGINS", "")
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

# ─── Include route modules ──────────────────────────────────────────────────

from .api.query import router as query_router
from .api.sandboxes import router as sandboxes_router
from .api.audit import router as audit_router
from .api.governance import router as governance_router

app.include_router(query_router)
app.include_router(sandboxes_router)
app.include_router(audit_router)
app.include_router(governance_router)


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
    _reset_sandbox_client()
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


# Connection health — must be defined before {name} routes to avoid path conflict
@app.get("/api/connections/health")
async def get_all_connection_health(window: int = Query(default=300, ge=60, le=3600)):
    """Get health stats for all monitored connections (Feature #31)."""
    return {"connections": health_monitor.all_stats(window)}


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
        try:
            ok = await connector.health_check()
        finally:
            await pool_manager.release(info.db_type, conn_str)
        return {"status": "healthy" if ok else "error", "message": "Connection test passed" if ok else "Health check failed"}
    except Exception as e:
        return {"status": "error", "message": _sanitize_db_error(str(e))}


@app.get("/api/connections/{name}/health")
async def get_connection_health(name: str, window: int = Query(default=300, ge=60, le=3600)):
    """Get health stats for a specific connection."""
    stats = health_monitor.connection_stats(name, window)
    if stats is None:
        raise HTTPException(status_code=404, detail=f"No health data for connection '{name}'")
    return stats


@app.get("/api/connections/{name}/schema")
async def get_connection_schema(name: str):
    """Retrieve the full schema for a database connection (Feature #18: schema caching)."""
    info = get_connection(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    conn_str = get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    cached = schema_cache.get(name)
    if cached is not None:
        return {
            "connection_name": name,
            "db_type": info.db_type,
            "table_count": len(cached),
            "tables": cached,
            "cached": True,
        }

    try:
        connector = await pool_manager.acquire(info.db_type, conn_str)
        try:
            schema = await connector.get_schema()
        finally:
            await pool_manager.release(info.db_type, conn_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_sanitize_db_error(str(e)))

    schema_cache.put(name, schema)
    return {
        "connection_name": name,
        "db_type": info.db_type,
        "table_count": len(schema),
        "tables": schema,
        "cached": False,
    }


# ─── Metrics SSE ─────────────────────────────────────────────────────────────

from .governance.cache import query_cache


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
                "query_cache": query_cache.stats(),
                "schema_cache": schema_cache.stats(),
            }

            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(generate(), media_type="text/event-stream")
