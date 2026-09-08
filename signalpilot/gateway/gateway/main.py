"""Create the SignalPilot FastAPI gateway.

The modules in gateway/api define the endpoint handlers.
This module defines lifespan, middleware, and router registration.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import register_routers
from .background import cancel_background_tasks, start_background_tasks
from .byok import DEKCache
from .byok.factory import make_provider
from .connectors.health_monitor import health_monitor
from .connectors.pool_manager import pool_manager
from .db.engine import close_db, get_session_factory, init_db
from .dbt_proxy import DbtProxyServer, RunTokenStore
from .dbt_proxy.config import DbtProxyConfig
from .http import (
    APIKeyAuthMiddleware,
    CookieAuthCsrfMiddleware,
    RateLimitMiddleware,
    RequestBodySizeLimitMiddleware,
    RequestCorrelationMiddleware,
    SecurityHeadersMiddleware,
    enforce_principal_rate_limit,
)
from .http.log_redaction import install_uvicorn_secret_path_filter, redact_secret_path
from .runtime.mode import is_cloud_mode
from .store import configure_byok
from .store.crypto import _validate_encryption_health

logger = logging.getLogger(__name__)
install_uvicorn_secret_path_filter()


# Lifespan.


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage background tasks: DB init, pool cleanup, and scheduled schema refresh."""

    # Cloud mode requires the network policy, sandbox runtime class, URL controls,
    # and sandbox service. This check detects invalid settings during startup.
    from .runtime.mode import assert_cloud_hardening_intact

    assert_cloud_hardening_intact()

    from .notebook_proxy.constants import (
        PROXY_CONNECT_TIMEOUT_SECONDS,
        PROXY_POOL_TIMEOUT_SECONDS,
        PROXY_READ_TIMEOUT_SECONDS,
        PROXY_WRITE_TIMEOUT_SECONDS,
    )

    # One httpx client serves all notebook proxy requests.
    # Lifespan teardown closes the client. The proxy applies individual connect,
    # write, and pool timeouts. The proxy also monitors idle chunk reads.
    proxy_client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=PROXY_CONNECT_TIMEOUT_SECONDS,
            read=PROXY_READ_TIMEOUT_SECONDS,
            write=PROXY_WRITE_TIMEOUT_SECONDS,
            pool=PROXY_POOL_TIMEOUT_SECONDS,
        )
    )
    app.state.notebook_proxy_client = proxy_client

    # Load notebook session JWT secret at startup (fail fast if misconfigured)
    from .auth.jwt_secret import load_session_jwt_secret

    try:
        load_session_jwt_secret()
        logger.info("STARTUP: Notebook session JWT secret loaded successfully.")
    except RuntimeError as e:
        logger.error("STARTUP FATAL: %s", e)
        raise SystemExit(1) from e

    # Ensure git repos directory exists
    from .git.repos import ensure_repos_dir
    ensure_repos_dir()

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

    # Plaintext TLS material blocks cloud readiness.
    # The health endpoint returns 503 until the operator completes the explicit migration.
    if is_cloud_mode():
        from .store.tls_migration import check_plaintext_tls_readiness

        tls_blocked = await check_plaintext_tls_readiness(force=True)
        if tls_blocked:
            logger.error("STARTUP: %s", tls_blocked)

    # Verify that cloud mode can resolve the OAuth state-signing key.
    from .api._oauth_state import get_state_hmac_key
    get_state_hmac_key()  # Raise at startup when the cloud encryption key is absent.

    # Configure the BYOK provider from startup environment variables.
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

    # Stop running sessions whose compute no longer answers after a gateway
    # restart. Handles are DB-backed, so live sandboxes reattach untouched;
    # dead ones get marked stopped and the next connection recreates them.
    try:
        from .notebooks.backends import get_notebook_backend
        from .store.notebook_sessions import list_stale_sessions, mark_stopped

        backend = get_notebook_backend()
        factory = get_session_factory()
        async with factory() as db_session:
            stale = await list_stale_sessions(db_session, max_idle_seconds=0)
            for s in stale:
                try:
                    alive = bool(s.runtime_handle) and await backend.is_alive(s.runtime_handle)
                except Exception:
                    alive = False
                if not alive:
                    await mark_stopped(db_session, session_id=s.session_id, org_id=s.org_id or "")
                    logger.info(
                        "STARTUP: cleaned stale session %s (runtime %s dead)",
                        s.session_id,
                        s.runtime_handle,
                    )
            await db_session.commit()
    except Exception as e:
        logger.warning("STARTUP: stale session cleanup failed: %s", e)

    background_tasks = start_background_tasks(get_session_factory())

    # Start MCP session manager if mounted
    mcp_ctx = None
    if _mcp_session_manager is not None:
        mcp_ctx = _mcp_session_manager.run()
        await mcp_ctx.__aenter__()

    # Start dbt-proxy TCP listener
    dbt_proxy_config = DbtProxyConfig()
    dbt_proxy_config.enforce_bind_safety(cloud=is_cloud_mode())

    # Fail closed: if secret is absent, token store is not created and the
    # server.start() context manager will log an error and skip binding.
    if dbt_proxy_config.sp_gateway_run_token_secret:
        dbt_proxy_token_store: RunTokenStore | None = RunTokenStore(dbt_proxy_config.sp_gateway_run_token_secret)
    else:
        dbt_proxy_token_store = None
    app.state.dbt_proxy_config = dbt_proxy_config
    app.state.dbt_proxy_token_store = dbt_proxy_token_store

    # DbtProxyServer.start() handles both disabled and secret-missing cases by
    # yielding _DisabledProxyServer without binding a port. When token_store is
    # None, the server checks config.sp_gateway_run_token_secret and aborts.
    dbt_proxy_ctx = DbtProxyServer.start(
        dbt_proxy_config,
        token_store=dbt_proxy_token_store,
        store_factory=get_session_factory,
    )
    dbt_proxy_server = await dbt_proxy_ctx.__aenter__()
    app.state.dbt_proxy_server = dbt_proxy_server

    try:
        yield
    finally:
        if mcp_ctx is not None:
            await mcp_ctx.__aexit__(None, None, None)
        await dbt_proxy_ctx.__aexit__(None, None, None)
        slack_poc_worker = getattr(app.state, "slack_poc_worker", None)
        if slack_poc_worker is not None:
            await slack_poc_worker.drain()
        slack_poc_client = getattr(app.state, "slack_poc_client", None)
        if slack_poc_client is not None:
            await slack_poc_client.aclose()
        # Flush any remaining health events before shutdown
        await health_monitor.flush_to_db()
        await cancel_background_tasks(background_tasks)
        await pool_manager.close_all()
        dek_cache.clear()
        await close_db()
        await proxy_client.aclose()
        from .api.deps import close_sandbox_clients

        await close_sandbox_clients()


# Application.

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
            if origin.startswith("http://localhost"):
                validated.append(origin)
            elif not origin.startswith("https://"):
                logger.warning("CORS: Skipping non-HTTPS origin '%s' in cloud mode", origin)
                continue
            else:
                validated.append(origin)
        return validated
    if not raw:
        return ["http://localhost:3000", "http://localhost:3200"]
    return [o.strip() for o in raw.split(",") if o.strip()]


_ALLOWED_ORIGINS = _build_allowed_origins()
_CSRF_ENABLED = is_cloud_mode()

# Middleware runs in reverse registration order. The last registered middleware runs first.
# The order starts with CORS. Auth is nearest to the application handlers.
# BodySizeLimit, SecurityHeaders, RateLimit, Correlation, and CSRF run between them.
# CORS is outermost so all error responses (including auth errors) get CORS headers.
# RequestCorrelationMiddleware runs before CSRF so CSRF logs already have a request ID.
# CookieAuthCsrfMiddleware runs after Correlation and before Auth.
# CookieAuthCsrfMiddleware reads headers and cookies directly.
# CookieAuthCsrfMiddleware does not depend on request.state.auth.
# RateLimit runs before CSRF and applies the general quota to rejected requests.
# APIKeyAuthMiddleware is nearest to the application handlers.
app.add_middleware(APIKeyAuthMiddleware)
app.add_middleware(CookieAuthCsrfMiddleware, allowed_origins=_ALLOWED_ORIGINS, enabled=_CSRF_ENABLED)
app.add_middleware(RequestCorrelationMiddleware)
app.add_middleware(RateLimitMiddleware, general_rpm=10000, expensive_rpm=1000, auth_rpm=100)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    RequestBodySizeLimitMiddleware,
    max_body_bytes=2_097_152,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-API-Key",
        "X-Request-ID",
        "Sp-Server-Token",
        "Sp-Session-Id",
        "x-runtime-url",
        "X-Gateway-Project-Id",
        "X-Gateway-Branch-Id",
    ],
    expose_headers=["X-Request-ID"],
    allow_credentials=True,
)

# Global exception handler.


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a generic response for an unhandled exception.

    This function raises HTTPException values again. FastAPI returns their intended status and body.
    """
    if isinstance(exc, (HTTPException, StarletteHTTPException)):
        raise exc
    logger.exception(
        "Unhandled exception in %s %s",
        request.method,
        redact_secret_path(request.url.path),
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Register all API routers
register_routers(app)

if (os.getenv("SLACK_DELIVERY_MODE") or "").lower() == "http":
    try:
        from .slack_poc.worker import load_http_config_from_env, register_http_routes

        register_http_routes(app, load_http_config_from_env())
        logger.info("Slack PoC HTTP endpoint mounted at /slack/events")
    except Exception:
        logger.exception("Failed to mount Slack PoC HTTP endpoint")
        raise

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
    # MCP streamable-http app has internal route at /mcp.
    # Mount at root so /mcp is reachable. MCPAuthMiddleware gates access.
    # FastAPI routes take priority over mounts, so /api/*, /notebook/*, /git/*
    # are handled by their routers before falling through to this mount.
    app.mount("/", _mcp_http_app)
    logger.info("MCP streamable-http endpoint mounted at /mcp (root mount, MCPAuth gated)")
except Exception as e:
    logger.warning("Failed to mount MCP HTTP endpoint: %s", e)
