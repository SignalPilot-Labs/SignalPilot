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

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import register_routers
from .byok import DEKCache
from .byok.factory import make_provider
from .connectors.health_monitor import health_monitor
from .connectors.pool_manager import pool_manager
from .connectors.schema_cache import schema_cache
from .db.engine import close_db, get_session_factory, init_db
from .governance.context import current_org_id_var
from .http import (
    APIKeyAuthMiddleware,
    RateLimitMiddleware,
    RequestBodySizeLimitMiddleware,
    RequestCorrelationMiddleware,
    SecurityHeadersMiddleware,
    enforce_principal_rate_limit,
)
from .models import ConnectionUpdate
from .runtime.mode import is_cloud_mode
from .store import Store, configure_byok
from .store.crypto import _validate_encryption_health

logger = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage background tasks: DB init, pool cleanup, and scheduled schema refresh."""

    # Initialize gateway DB tables
    await init_db()

    # Load persisted health state into in-memory cache
    await health_monitor.load_from_db()

    # Verify encryption key is functional at startup
    if not _validate_encryption_health():
        logger.error(
            "STARTUP: Encryption health check failed. "
            "Credentials may not be readable. Check SP_ENCRYPTION_KEY configuration."
        )
    else:
        logger.info("STARTUP: Encryption health check passed.")

    # Configure BYOK provider — type and config are read from env vars at startup.
    # SP_BYOK_PROVIDER: provider type string (default: "local")
    # SP_BYOK_PROVIDER_CONFIG: JSON-encoded provider config dict (optional)
    byok_provider_type = os.getenv("SP_BYOK_PROVIDER", "local")
    byok_provider_config_raw = os.getenv("SP_BYOK_PROVIDER_CONFIG")
    byok_provider_config: dict | None = None
    if byok_provider_config_raw:
        import json as _json

        try:
            byok_provider_config = _json.loads(byok_provider_config_raw)
        except _json.JSONDecodeError:
            logger.error("STARTUP FATAL: SP_BYOK_PROVIDER_CONFIG contains invalid JSON")
            raise SystemExit(1)

    # In cloud mode, skip local BYOK provider auto-registration
    dek_cache = DEKCache(ttl_seconds=300)
    if is_cloud_mode() and byok_provider_type == "local":
        logger.info(
            "STARTUP: Cloud mode — skipping local BYOK provider; set SP_BYOK_PROVIDER to aws_kms/gcp_kms/azure_kv"
        )
    else:
        byok_provider = make_provider(byok_provider_type, byok_provider_config)
        configure_byok(byok_provider, dek_cache)
        logger.info("STARTUP: BYOK provider configured (%s)", byok_provider_type)

    if is_cloud_mode():
        logger.info("STARTUP: Cloud mode — sandbox, file browser, dbt projects disabled")

    async def _health_flush_loop():
        """Flush buffered health events to DB every 5 seconds."""
        while True:
            await asyncio.sleep(5)
            try:
                await health_monitor.flush_to_db()
            except Exception as e:
                logger.warning("Health flush loop error: %s", e)

    async def _health_cleanup_loop():
        """Delete health events older than 7 days, every hour."""
        while True:
            await asyncio.sleep(3600)
            try:
                await health_monitor.cleanup_old_events()
            except Exception as e:
                logger.warning("Health cleanup loop error: %s", e)

    async def _health_ping_loop():
        """Ping each connection every 30s to keep health stats fresh."""
        await asyncio.sleep(10)  # Wait for startup to settle
        while True:
            try:
                factory = get_session_factory()
                async with factory() as session:
                    store = Store(session, allow_unscoped=True)
                    connections = await store.list_connections()
                    for conn_info in connections:
                        token = current_org_id_var.set(conn_info.org_id)
                        try:
                            inner_store = Store(session, org_id=conn_info.org_id)
                            conn_str = await inner_store.get_connection_string(conn_info.name)
                            if not conn_str:
                                continue
                            extras = await inner_store.get_credential_extras(conn_info.name)
                            start = time.monotonic()
                            try:
                                async with pool_manager.connection(
                                    conn_info.db_type,
                                    conn_str,
                                    credential_extras=extras,
                                    connection_name=conn_info.name,
                                ) as connector:
                                    ok = await connector.health_check()
                                elapsed = (time.monotonic() - start) * 1000
                                health_monitor.record(
                                    conn_info.name,
                                    elapsed,
                                    ok,
                                    error=None if ok else "health_check returned false",
                                    db_type=conn_info.db_type,
                                )
                            except Exception as e:
                                elapsed = (time.monotonic() - start) * 1000
                                health_monitor.record(
                                    conn_info.name,
                                    elapsed,
                                    False,
                                    error=str(e)[:200],
                                    db_type=conn_info.db_type,
                                )
                        finally:
                            current_org_id_var.reset(token)
            except Exception as e:
                logger.warning("Health ping loop error: %s", e)
            await asyncio.sleep(30)

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
                    store = Store(session, allow_unscoped=True)  # Background task: needs cross-user access
                    connections = await store.list_connections()
                    now = time.time()
                    for conn_info in connections:
                        interval = conn_info.schema_refresh_interval
                        if not interval:
                            continue
                        last_refresh = conn_info.last_schema_refresh or 0
                        if now - last_refresh < interval:
                            continue
                        # Outer Store is allow_unscoped; construct a per-org inner Store
                        # so get_connection_string, get_credential_extras, and update_connection
                        # are correctly scoped and update_connection's WHERE clause matches.
                        token = current_org_id_var.set(conn_info.org_id)
                        try:
                            inner_store = Store(session, org_id=conn_info.org_id)
                            conn_str = await inner_store.get_connection_string(conn_info.name)
                            if not conn_str:
                                continue
                            extras = await inner_store.get_credential_extras(conn_info.name)
                            async with pool_manager.connection(
                                conn_info.db_type,
                                conn_str,
                                credential_extras=extras,
                                connection_name=conn_info.name,
                            ) as connector:
                                schema = await connector.get_schema()
                            diff_result = schema_cache.put(conn_info.name, schema, track_diff=True)
                            await inner_store.update_connection(
                                conn_info.name,
                                ConnectionUpdate(
                                    last_schema_refresh=now,
                                ),
                            )
                            if diff_result and diff_result.get("has_changes"):
                                added = len(diff_result.get("added_tables", []))
                                removed = len(diff_result.get("removed_tables", []))
                                modified = len(diff_result.get("modified_tables", []))
                                logger.info(
                                    "Schema change detected for '%s': +%d/-%d tables, %d modified",
                                    conn_info.name,
                                    added,
                                    removed,
                                    modified,
                                )
                            else:
                                logger.info(
                                    "Scheduled schema refresh for '%s': %d tables (no structural changes)",
                                    conn_info.name,
                                    len(schema),
                                )
                        except Exception as e:
                            logger.warning(
                                "Scheduled schema refresh failed for '%s': %s",
                                conn_info.name,
                                e,
                            )
                        finally:
                            current_org_id_var.reset(token)
            except Exception as e:
                logger.warning("Schema refresh loop error: %s", e)

    health_flush_task = asyncio.create_task(_health_flush_loop())
    health_cleanup_task = asyncio.create_task(_health_cleanup_loop())
    health_ping_task = asyncio.create_task(_health_ping_loop())
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
        # Flush any remaining health events before shutdown
        await health_monitor.flush_to_db()
        health_flush_task.cancel()
        health_cleanup_task.cancel()
        health_ping_task.cancel()
        cleanup_task.cancel()
        refresh_task.cancel()
        await pool_manager.close_all()
        dek_cache.clear()
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
    dependencies=[Depends(enforce_principal_rate_limit)],
)


# CORS
def _build_allowed_origins() -> list[str]:
    raw = os.environ.get("SP_ALLOWED_ORIGINS", "")
    if is_cloud_mode():
        if not raw:
            return [
                "https://signalpilot.ai",
                "https://www.signalpilot.ai",
                "https://app.signalpilot.ai",
            ]
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        validated = []
        for origin in origins:
            if not origin.startswith("https://"):
                logger.warning("CORS: Skipping non-HTTPS origin '%s' in cloud mode", origin)
                continue
            validated.append(origin)
        return validated
    if not raw:
        return ["http://localhost:3000", "http://localhost:3200"]
    return [o.strip() for o in raw.split(",") if o.strip()]


_ALLOWED_ORIGINS = _build_allowed_origins()

# Middleware stack (last added = outermost = runs first)
# Execution order (outermost → innermost):
#   CORS → BodySizeLimit → SecurityHeaders → RateLimit → Correlation → Auth
# CORS is outermost so all error responses (including auth errors) get CORS headers.
# RequestCorrelationMiddleware runs before Auth so auth logs already have a request ID.
# APIKeyAuthMiddleware is innermost — closest to the application handlers.
app.add_middleware(APIKeyAuthMiddleware)
app.add_middleware(RequestCorrelationMiddleware)
app.add_middleware(RateLimitMiddleware, general_rpm=10000, expensive_rpm=1000, auth_rpm=100)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestBodySizeLimitMiddleware, max_body_bytes=2_097_152)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
    allow_credentials=True,
)

# ─── Global Exception Handler ─────────────────────────────────────────────────


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Safety net: return a generic 500 for any unhandled exception.

    HTTPException variants (intentional 4xx/5xx) are re-raised so FastAPI's
    built-in handler processes them normally and they reach the client unchanged.
    """
    if isinstance(exc, (HTTPException, StarletteHTTPException)):
        raise exc
    logger.exception(
        "Unhandled exception in %s %s",
        request.method,
        request.url.path,
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Register all API routers
register_routers(app)

# Mount the MCP server at /mcp for streamable-http transport (used by Claude Code plugin)
_mcp_session_manager = None
try:
    from .mcp import mcp as _mcp_instance

    # Override the gateway URL so the MCP tools call back to this same process
    os.environ.setdefault("SP_GATEWAY_URL", "http://localhost:3300")

    from .auth.mcp_api_key import MCPAuthMiddleware

    _mcp_http_app = _mcp_instance.streamable_http_app()
    _mcp_session_manager = _mcp_instance.session_manager
    _mcp_http_app = MCPAuthMiddleware(_mcp_http_app)
    app.mount("/mcp", _mcp_http_app)  # New canonical path
    app.mount("/", _mcp_http_app)  # Backward compat — remove after client migration
    logger.info("MCP streamable-http endpoint mounted at /mcp (also / for backward compat)")
except Exception as e:
    logger.warning("Failed to mount MCP HTTP endpoint: %s", e)
