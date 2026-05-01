"""Workspaces API application factory.

Usage (uvicorn):
    uvicorn workspaces_api.main:app --host 0.0.0.0 --port 3400

Usage (programmatic):
    from workspaces_api.main import create_app
    app = create_app()
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI

from workspaces_api.agent.spawner import StubSpawner
from workspaces_api.auth.clerk import JwksClient
from workspaces_api.config import get_settings
from workspaces_api.dashboards import router as dashboards_router
from workspaces_api.db import make_engine, make_sessionmaker
from workspaces_api.agent.sandbox_runtime import build_runtime
from workspaces_api.errors import (
    ClerkConfigMissing,
    SandboxBinaryNotFound,
    SandboxRuntimeUnavailable,
    register_exception_handlers,
)
from workspaces_api.events.bus import EventBus
from workspaces_api.routes import health_router, runs_router

logger = logging.getLogger(__name__)

_STATIC_CLAUDE_MD_PATH = (
    Path(__file__).parent.parent.parent / "agent" / "CLAUDE.md"
)
_HTTP_CLIENT_TIMEOUT = httpx.Timeout(connect=2, read=5, write=5, pool=2)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    # Fail fast: cloud mode requires Clerk JWKS URL and issuer configured.
    if settings.sp_deployment_mode == "cloud":
        if not settings.clerk_jwks_url:
            raise ClerkConfigMissing(
                "SP_CLERK_JWKS_URL is required in cloud mode"
            )
        if not settings.clerk_jwks_url.startswith("https://"):
            raise ClerkConfigMissing(
                "SP_CLERK_JWKS_URL must use https:// scheme to prevent JWKS MITM"
            )
        if not settings.clerk_issuer:
            raise ClerkConfigMissing(
                "SP_CLERK_ISSUER is required in cloud mode"
            )

    # Validate sandbox binary early
    if settings.sp_use_subprocess_spawner:
        if not settings.sp_sandbox_server_path.exists():
            raise SandboxBinaryNotFound(
                f"Sandbox server.py not found at {settings.sp_sandbox_server_path}. "
                "Set SP_SANDBOX_SERVER_PATH or SP_USE_SUBPROCESS_SPAWNER=false."
            )

    # R8/R9: sandbox runtime gate — runs BEFORE make_engine so broken deploys
    # never open DB pools.
    runtime = build_runtime(settings)
    if settings.sp_deployment_mode == "cloud" and runtime.name != "runsc":
        raise SandboxRuntimeUnavailable(
            f"cloud mode requires SP_SANDBOX_RUNTIME=runsc (got {runtime.name!r})"
        )
    await runtime.validate_available()

    # Ensure workdir root exists
    settings.sp_run_workdir_root.mkdir(parents=True, exist_ok=True)

    engine = make_engine(settings.database_url)
    session_factory = make_sessionmaker(engine)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.bus = EventBus()

    if settings.sp_use_subprocess_spawner:
        from workspaces_api.agent.proxy_token_client import ProxyTokenClient
        from workspaces_api.agent.subprocess_spawner import SubprocessSpawner

        http_client = httpx.AsyncClient(timeout=_HTTP_CLIENT_TIMEOUT)

        token_client: ProxyTokenClient | None = None
        if settings.gateway_url:
            api_key = (
                settings.sp_api_key.get_secret_value()
                if settings.sp_api_key is not None
                else None
            )
            token_client = ProxyTokenClient(
                gateway_url=settings.gateway_url,
                http_client=http_client,
                api_key=api_key,
            )

        static_md_text = ""
        if _STATIC_CLAUDE_MD_PATH.exists():
            static_md_text = _STATIC_CLAUDE_MD_PATH.read_text(encoding="utf-8")
        else:
            logger.warning(
                "static CLAUDE.md not found at %s — sandbox will have empty static instructions",
                _STATIC_CLAUDE_MD_PATH,
            )

        spawner = SubprocessSpawner(
            settings=settings,
            session_factory=session_factory,
            bus=app.state.bus,
            token_client=token_client,
            static_md_text=static_md_text,
            runtime=runtime,
        )
        app.state.spawner = spawner

        if token_client is not None:
            from workspaces_api.dashboards.executor import DbtProxyExecutor

            app.state.chart_executor = DbtProxyExecutor(
                settings=settings,
                token_client=token_client,
            )
        else:
            app.state.chart_executor = None
    else:
        http_client = None  # type: ignore[assignment]
        app.state.spawner = StubSpawner()
        app.state.chart_executor = None

    # Build JWKS client (always — constructor is cheap, fetches lazily).
    # In local mode the client is constructed but never queried.
    jwks_url = settings.clerk_jwks_url or ""
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=_HTTP_CLIENT_TIMEOUT)
    app.state.jwks_client = JwksClient(
        jwks_url=jwks_url,
        http_client=http_client,
        ttl_seconds=settings.clerk_jwks_cache_ttl_seconds,
    )

    logger.info(
        "workspaces_api starting mode=%s spawner=%s",
        settings.sp_deployment_mode,
        type(app.state.spawner).__name__,
    )

    try:
        yield
    finally:
        await app.state.spawner.shutdown()
        await engine.dispose()
        if http_client is not None:
            await http_client.aclose()
        logger.info("workspaces_api stopped")


def create_app() -> FastAPI:
    """Build and return the Workspaces API FastAPI application."""
    app = FastAPI(
        title="Workspaces API",
        version="0.0.0",
        lifespan=_lifespan,
    )

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(runs_router)
    app.include_router(dashboards_router)

    return app


app = create_app()
