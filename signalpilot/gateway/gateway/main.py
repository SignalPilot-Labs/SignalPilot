"""SignalPilot Gateway — FastAPI application.

All endpoint handlers live in gateway/api/ router modules.
This file is the app shell: lifespan, middleware, and router registration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .middleware import (
    APIKeyAuthMiddleware,
    AuthBruteForceMiddleware,
    RateLimitMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)
from .models import ConnectionUpdate
from .connectors.pool_manager import pool_manager
from .connectors.schema_cache import schema_cache
from .store import (
    get_connection_string,
    get_credential_extras,
    list_connections,
    load_tunnels,
    update_connection,
)
from .api import register_routers

logger = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage background tasks: pool cleanup, schema refresh, and tunnel lifecycle."""
    # Load persisted tunnels (all as stopped)
    load_tunnels()

    async def _pool_cleanup_loop():
        while True:
            await asyncio.sleep(60)
            await pool_manager.cleanup_idle()

    async def _schema_refresh_loop():
        while True:
            await asyncio.sleep(30)
            try:
                connections = list_connections()
                now = time.time()
                for conn_info in connections:
                    interval = conn_info.schema_refresh_interval
                    if not interval:
                        continue
                    last_refresh = conn_info.last_schema_refresh or 0
                    if now - last_refresh < interval:
                        continue
                    try:
                        conn_str = get_connection_string(conn_info.name)
                        if not conn_str:
                            continue
                        extras = get_credential_extras(conn_info.name)
                        async with pool_manager.connection(
                            conn_info.db_type, conn_str, credential_extras=extras,
                        ) as connector:
                            schema = await connector.get_schema()
                        diff_result = schema_cache.put(conn_info.name, schema, track_diff=True)
                        update_connection(conn_info.name, ConnectionUpdate(
                            last_schema_refresh=now,
                        ))
                        if diff_result and diff_result.get("has_changes"):
                            added = len(diff_result.get("added_tables", []))
                            removed = len(diff_result.get("removed_tables", []))
                            modified = len(diff_result.get("modified_tables", []))
                            logger.info(
                                "Schema change detected for '%s': +%d/-%d tables, %d modified",
                                conn_info.name, added, removed, modified,
                            )
                        else:
                            logger.info(
                                "Scheduled schema refresh for '%s': %d tables (no structural changes)",
                                conn_info.name, len(schema),
                            )
                    except Exception as e:
                        logger.warning(
                            "Scheduled schema refresh failed for '%s': %s",
                            conn_info.name, e,
                        )
            except Exception as e:
                logger.warning("Schema refresh loop error: %s", e)

    cleanup_task = asyncio.create_task(_pool_cleanup_loop())
    refresh_task = asyncio.create_task(_schema_refresh_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        refresh_task.cancel()
        # Stop all tunnel processes
        from .api.tunnels import get_tunnel_manager
        await get_tunnel_manager().stop_all()
        await pool_manager.close_all()
        from .api.deps import _sandbox_client
        if _sandbox_client:
            await _sandbox_client.close()


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="SignalPilot Gateway",
    version="0.1.0",
    description="Governed MCP server for AI database access",
    lifespan=lifespan,
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions to prevent stack trace leaks in responses."""
    from .api.deps import sanitize_db_error

    request_id = getattr(request.state, "request_id", "unknown")
    # Sanitize first, then truncate — sanitize_db_error handles its own truncation
    # (truncating before sanitization can split credentials mid-token, evading regex)
    safe_msg = sanitize_db_error(str(exc))
    logger.error(
        "Unhandled exception [request_id=%s] %s: %s",
        request_id, type(exc).__name__, safe_msg,
    )
    # Don't expose internal details in production
    return Response(
        content=json.dumps({"detail": "Internal server error", "request_id": request_id}),
        status_code=500,
        media_type="application/json",
    )


# CORS — dynamic origin allowlist (supports tunnel URLs added at runtime)
_ALLOWED_ORIGINS: set[str] = {
    "http://localhost:3200",
    "http://localhost:3000",
    "http://127.0.0.1:3200",
    "http://127.0.0.1:3000",
}
_extra_origins = os.getenv("SP_ALLOWED_ORIGINS", "")
if _extra_origins:
    _ALLOWED_ORIGINS.update(o.strip() for o in _extra_origins.split(",") if o.strip())

_CORS_METHODS = "GET, POST, PUT, DELETE, OPTIONS"
_CORS_HEADERS = "Content-Type, Authorization, X-API-Key"


def add_tunnel_origin(url: str):
    _ALLOWED_ORIGINS.add(url.rstrip("/"))


def remove_tunnel_origin(url: str):
    _ALLOWED_ORIGINS.discard(url.rstrip("/"))


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        origin = request.headers.get("origin", "")
        if request.method == "OPTIONS" and origin in _ALLOWED_ORIGINS:
            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": _CORS_METHODS,
                    "Access-Control-Allow-Headers": _CORS_HEADERS,
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Max-Age": "600",
                    "Vary": "Origin",
                },
            )
        response = await call_next(request)
        # Append Vary: Origin for correct cache behavior (don't clobber existing Vary)
        existing_vary = response.headers.get("Vary", "")
        if "Origin" not in existing_vary:
            response.headers.append("Vary", "Origin")
        if origin in _ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        return response


# Security middleware stack
# Registration order is reverse of execution order (last registered = outermost = first to execute)
# Execution order: RequestID → CORS → SecurityHeaders → RateLimit → BruteForce → Auth → App
app.add_middleware(APIKeyAuthMiddleware)
app.add_middleware(AuthBruteForceMiddleware)
app.add_middleware(RateLimitMiddleware, general_rpm=120, expensive_rpm=30)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(DynamicCORSMiddleware)
app.add_middleware(RequestIDMiddleware)

# Register all API routers
register_routers(app)
