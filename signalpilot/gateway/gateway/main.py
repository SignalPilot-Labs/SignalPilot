"""SignalPilot Gateway — FastAPI application.

All endpoint handlers live in gateway/api/ router modules.
This file is the app shell: lifespan, middleware, and router registration.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .middleware import APIKeyAuthMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware
from .models import ConnectionUpdate
from .connectors.pool_manager import pool_manager
from .connectors.schema_cache import schema_cache
from .db.engine import init_db, close_db, get_session_factory
from .store import Store
from .api import register_routers
from .api.deps import reset_sandbox_client, _sandbox_client

logger = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage background tasks: DB init, pool cleanup, and scheduled schema refresh."""

    # Initialize gateway DB tables
    await init_db()

    async def _pool_cleanup_loop():
        while True:
            await asyncio.sleep(60)
            await pool_manager.cleanup_idle()

    async def _schema_refresh_loop():
        while True:
            await asyncio.sleep(30)
            try:
                factory = get_session_factory()
                async with factory() as session:
                    store = Store(session)  # No user_id = global (all users' connections)
                    connections = await store.list_connections()
                    now = time.time()
                    for conn_info in connections:
                        interval = conn_info.schema_refresh_interval
                        if not interval:
                            continue
                        last_refresh = conn_info.last_schema_refresh or 0
                        if now - last_refresh < interval:
                            continue
                        try:
                            conn_str = await store.get_connection_string(conn_info.name)
                            if not conn_str:
                                continue
                            extras = await store.get_credential_extras(conn_info.name)
                            async with pool_manager.connection(
                                conn_info.db_type, conn_str, credential_extras=extras,
                            ) as connector:
                                schema = await connector.get_schema()
                            diff_result = schema_cache.put(conn_info.name, schema, track_diff=True)
                            await store.update_connection(conn_info.name, ConnectionUpdate(
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

    # Start MCP session manager if mounted
    mcp_ctx = None
    if _mcp_session_manager is not None:
        mcp_ctx = _mcp_session_manager.run()
        await mcp_ctx.__aenter__()

    try:
        yield
    finally:
        if mcp_ctx is not None:
            await mcp_ctx.__aexit__(None, None, None)
        cleanup_task.cancel()
        refresh_task.cancel()
        await pool_manager.close_all()
        await close_db()
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

# CORS
_ALLOWED_ORIGINS = [
    "http://localhost:3200",
    "http://localhost:3000",
    "http://127.0.0.1:3200",
    "http://127.0.0.1:3000",
]
_extra_origins = os.getenv("SP_ALLOWED_ORIGINS", "")
if _extra_origins:
    _ALLOWED_ORIGINS.extend(o.strip() for o in _extra_origins.split(",") if o.strip())

# Middleware stack (last added = outermost = runs first)
# CORS must be outermost so error responses from auth also get CORS headers
app.add_middleware(APIKeyAuthMiddleware)
app.add_middleware(RateLimitMiddleware, general_rpm=120, expensive_rpm=30)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    allow_credentials=True,
)

# Register all API routers
register_routers(app)

# Mount the MCP server at /mcp for streamable-http transport (used by Claude Code plugin)
_mcp_session_manager = None
try:
    from .mcp_server import mcp as _mcp_instance

    # Override the gateway URL so the MCP tools call back to this same process
    os.environ.setdefault("SP_GATEWAY_URL", "http://localhost:3300")

    from .mcp_auth import MCPAuthMiddleware
    _mcp_http_app = _mcp_instance.streamable_http_app()
    _mcp_session_manager = _mcp_instance.session_manager
    _mcp_http_app = MCPAuthMiddleware(_mcp_http_app)
    app.mount("/", _mcp_http_app)
    logger.info("MCP streamable-http endpoint mounted at /mcp")
except Exception as e:
    logger.warning("Failed to mount MCP HTTP endpoint: %s", e)
