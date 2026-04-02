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
from .store import (
    get_connection_string,
    get_credential_extras,
    list_connections,
    update_connection,
)
from .api import register_routers

logger = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage background tasks: pool cleanup and scheduled schema refresh."""

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

# Register all API routers
register_routers(app)
