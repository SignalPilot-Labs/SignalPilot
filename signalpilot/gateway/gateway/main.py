"""Create the SignalPilot FastAPI gateway.

The modules in gateway/api define the endpoint handlers.
This module defines lifespan, middleware, and router registration.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import httpx
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
from .dbt_proxy import DbtProxyServer, RunTokenStore
from .dbt_proxy.config import DbtProxyConfig
from .governance.context import current_org_id_var
from .http import (
    APIKeyAuthMiddleware,
    CookieAuthCsrfMiddleware,
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
                            # A single row with undecryptable credentials must
                            # not abort the sweep for every other connection.
                            try:
                                conn_str = await inner_store.get_connection_string(conn_info.name)
                                extras = await inner_store.get_credential_extras(conn_info.name)
                            except Exception as e:
                                logger.debug(
                                    "Health ping skipped for %s: %s", conn_info.name, e
                                )
                                continue
                            if not conn_str:
                                continue
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

    async def _notebook_lifecycle_loop():
        """Runtime v2 session lifecycle, every 300 s:

        - extend the execution grant of every session with a fresh ping (the
          provider caps one grant; the loop keeps active sessions alive);
        - flush-by-contract, snapshot, and release compute for idle sessions
          (scale-to-zero — resume happens on the next request);
        - destroy notebook-tagged sandboxes no live session row owns (the
          crashed-gateway backstop the provider time limit only bounds).
        """
        import time as _time

        from .config.notebooks import get_notebook_settings
        from .notebooks.backends import VercelNotebookBackend, get_notebook_backend
        from .notebooks.session_service import snapshot_idle_session
        from .store import notebook_sessions as ns

        while True:
            await asyncio.sleep(300)
            try:
                settings = get_notebook_settings()
                if settings.resolved_backend() != "vercel":
                    continue
                backend = get_notebook_backend(settings)
                factory = get_session_factory()
                async with factory() as session:
                    now = _time.time()
                    for s in await ns.list_running_internal(session):
                        if not s.runtime_handle:
                            continue
                        idle = now - (s.last_ping or 0)
                        if idle < settings.idle_snapshot_seconds:
                            try:
                                await backend.extend(
                                    s.runtime_handle, settings.session_grant_seconds
                                )
                                await ns.update_session_runtime(
                                    session,
                                    session_id=s.session_id,
                                    org_id=s.org_id,
                                    last_extend_at=now,
                                )
                            except Exception:
                                logger.warning(
                                    "Extend failed for session %s; snapshot backstop applies",
                                    s.session_id,
                                    exc_info=True,
                                )
                        else:
                            logger.info(
                                "Snapshotting idle notebook session %s (idle %.0fs)",
                                s.session_id,
                                idle,
                            )
                            await snapshot_idle_session(session, internal=s, backend=backend)
                    if isinstance(backend, VercelNotebookBackend):
                        keep = await ns.live_runtime_handles(session)
                        reaped = await backend.reap_orphans(keep)
                        if reaped:
                            logger.info("Notebook sandbox reaper: destroyed %d orphan(s)", reaped)
            except Exception as e:
                logger.warning("Notebook lifecycle loop error: %s", e)

    async def _knowledge_retention_loop():
        """Prune knowledge retrieval events past the retention window.

        BM25 ranks documents during each query. This loop limits event log growth.
        """
        from .store.knowledge_search import prune_retrieval_events

        await asyncio.sleep(30)
        while True:
            try:
                factory = get_session_factory()
                async with factory() as session:
                    pruned = await prune_retrieval_events(session)
                    if pruned:
                        logger.info("Pruned %d old knowledge retrieval event(s)", pruned)
            except Exception as e:
                logger.warning("Knowledge retention loop error: %s", e)
            await asyncio.sleep(3600)

    async def _schema_watch_loop():
        """Run scheduled schema-difference checks every minute.

        A detected difference can create a GitHub pull request.
        """
        from .schema_watch.runner import run_due_watches

        while True:
            await asyncio.sleep(60)
            try:
                ran = await run_due_watches(get_session_factory())
                if ran:
                    logger.info("Schema watch loop: ran %d watch(es)", ran)
            except Exception as e:
                logger.warning("Schema watch loop error: %s", e)

    async def _eval_reaper_loop():
        """Recover stale runs and remove orphaned eval branches every two minutes.

        Recovery marks stale runs before the reaper checks their branches.
        """
        from .evals.retention import reap_orphans, recover_stale_runs

        # A run from an earlier process cannot continue in this process.
        try:
            recovered = await recover_stale_runs()
            if recovered:
                logger.warning("Eval startup recovery: failed %d stale run(s)", recovered)
        except Exception as e:
            logger.warning("Eval startup recovery error: %s", e)

        while True:
            await asyncio.sleep(120)
            try:
                await recover_stale_runs()
                reaped = await reap_orphans()
                if reaped["branches"] or reaped["connections"]:
                    logger.warning("Eval reaper: %s", reaped)
            except Exception as e:
                logger.warning("Eval reaper loop error: %s", e)

    async def _eval_retention_loop():
        """Backstop for the on-write retention enforcement, hourly."""
        from .evals.retention import retention_sweep

        while True:
            await asyncio.sleep(3600)
            try:
                await retention_sweep()
            except Exception as e:
                logger.warning("Eval retention loop error: %s", e)

    async def _dbt_map_reaper_loop():
        """Fail dbt-map compiles whose lease died with a previous process."""
        from .dbt_map.runner import reap_stale_compiles

        while True:
            await asyncio.sleep(120)
            try:
                reaped = await reap_stale_compiles()
                if reaped:
                    logger.warning("dbt-map reaper: failed %d stale compile(s)", reaped)
            except Exception as e:
                logger.warning("dbt-map reaper loop error: %s", e)

    async def _improvement_schedule_loop():
        """Seed due daily improvement runs every minute.

        Each enabled org gets at most one system-initiated run per ET day.
        """
        from .improvements.scheduler import run_due_improvement_runs

        while True:
            await asyncio.sleep(60)
            try:
                ran = await run_due_improvement_runs(get_session_factory())
                if ran:
                    logger.info("Improvement schedule loop: processed %d org(s)", ran)
            except Exception as e:
                logger.warning("Improvement schedule loop error: %s", e)

    health_flush_task = asyncio.create_task(_health_flush_loop())
    health_cleanup_task = asyncio.create_task(_health_cleanup_loop())
    health_ping_task = asyncio.create_task(_health_ping_loop())
    cleanup_task = asyncio.create_task(_pool_cleanup_loop())
    refresh_task = asyncio.create_task(_schema_refresh_loop())
    notebook_lifecycle_task = asyncio.create_task(_notebook_lifecycle_loop())
    knowledge_retention_task = asyncio.create_task(_knowledge_retention_loop())
    schema_watch_task = asyncio.create_task(_schema_watch_loop())
    eval_reaper_task = asyncio.create_task(_eval_reaper_loop())
    eval_retention_task = asyncio.create_task(_eval_retention_loop())
    improvement_schedule_task = asyncio.create_task(_improvement_schedule_loop())
    dbt_map_reaper_task = asyncio.create_task(_dbt_map_reaper_loop())

    async def _repo_mirror_reconcile_startup() -> None:
        # Heal any GitHub-linked project whose bare mirror is missing (reset
        # repos volume, failed import clone, container remount) so users never
        # hit "the production branch is not available". One-shot, best-effort,
        # slightly delayed so it never slows startup.
        await asyncio.sleep(15)
        try:
            from .git.sync import reconcile_all_repo_mirrors

            await reconcile_all_repo_mirrors()
        except Exception as e:
            logger.warning("repo mirror reconcile failed: %s", e)

    repo_reconcile_task = asyncio.create_task(_repo_mirror_reconcile_startup())

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
        health_flush_task.cancel()
        health_cleanup_task.cancel()
        health_ping_task.cancel()
        cleanup_task.cancel()
        refresh_task.cancel()
        notebook_lifecycle_task.cancel()
        knowledge_retention_task.cancel()
        schema_watch_task.cancel()
        eval_reaper_task.cancel()
        eval_retention_task.cancel()
        improvement_schedule_task.cancel()
        dbt_map_reaper_task.cancel()
        repo_reconcile_task.cancel()
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
        request.url.path,
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
