"""Shared pytest fixtures for the Workspaces API test suite.

DB strategy: SQLite in-memory via sqlite+aiosqlite:///:memory: with
execution_options={"schema_translate_map": {"workspaces": None}}. This
causes SQLAlchemy to rewrite all "workspaces.*" qualified names to
unqualified at statement-prepare time. Production Postgres engine is built
without the map. Alembic is NOT run in unit tests.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from workspaces_api.agent.spawner import StubSpawner
from workspaces_api.auth.clerk import JwksClient
from workspaces_api.config import Settings, get_settings
from workspaces_api.dashboards.models import Chart, ChartQuery
from workspaces_api.db import Base, make_sessionmaker
from workspaces_api.events.bus import EventBus
from workspaces_api.main import create_app
from workspaces_api.routes.runs import _get_bus, _get_session_factory, _get_spawner

_SQLITE_URL = "sqlite+aiosqlite:///:memory:"
_SCHEMA_MAP: dict[str | None, str | None] = {"workspaces": None}


@pytest_asyncio.fixture
async def async_engine():
    engine = create_async_engine(
        _SQLITE_URL,
        execution_options={"schema_translate_map": _SCHEMA_MAP},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(async_engine):
    return make_sessionmaker(async_engine)


@pytest_asyncio.fixture
async def db_session(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture
def settings_local() -> Settings:
    return Settings.model_validate({
        "SP_DEPLOYMENT_MODE": "local",
        "CLAUDE_CODE_OAUTH_TOKEN": "test-token",
        "WORKSPACES_DATABASE_URL": _SQLITE_URL,
    })


@pytest.fixture
def settings_cloud_byo() -> Settings:
    return Settings.model_validate({
        "SP_DEPLOYMENT_MODE": "cloud",
        "ANTHROPIC_API_KEY": "sk-ant-test-key",
        "WORKSPACES_DATABASE_URL": _SQLITE_URL,
    })


@pytest.fixture
def settings_cloud_no_key() -> Settings:
    return Settings.model_validate({
        "SP_DEPLOYMENT_MODE": "cloud",
        "WORKSPACES_DATABASE_URL": _SQLITE_URL,
    })


@pytest.fixture
def settings_cloud_metered() -> Settings:
    return Settings.model_validate({
        "SP_DEPLOYMENT_MODE": "cloud",
        "ANTHROPIC_API_KEY": "sk-ant-test-key",
        "WORKSPACES_DATABASE_URL": _SQLITE_URL,
    })


@pytest.fixture
def stub_spawner() -> StubSpawner:
    return StubSpawner()


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def stub_jwks_client() -> JwksClient:
    """A JwksClient that is never queried (local mode)."""
    mock_http = AsyncMock()
    return JwksClient(
        jwks_url="http://unused.local/.well-known/jwks.json",
        http_client=mock_http,
        ttl_seconds=600,
    )


@pytest_asyncio.fixture
async def app(settings_local, session_factory, stub_spawner, event_bus, stub_jwks_client):
    application = create_app()

    application.dependency_overrides[get_settings] = lambda: settings_local
    application.dependency_overrides[_get_session_factory] = lambda: session_factory
    application.dependency_overrides[_get_spawner] = lambda: stub_spawner
    application.dependency_overrides[_get_bus] = lambda: event_bus

    application.state.session_factory = session_factory
    application.state.spawner = stub_spawner
    application.state.bus = event_bus
    application.state.chart_executor = None
    application.state.jwks_client = stub_jwks_client

    yield application


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def chart_factory(db_session, session_factory):
    """Factory for creating Chart + ChartQuery ORM objects in tests."""

    async def _make_chart(
        workspace_id: str = "ws-test",
        title: str = "Test Chart",
        chart_type: str = "line",
        connector_name: str = "my_conn",
        sql: str = "SELECT 1",
        params: dict | None = None,
        refresh_interval_seconds: int = 3600,
    ) -> tuple[Chart, ChartQuery]:
        chart = Chart(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            title=title,
            chart_type=chart_type,
            echarts_option={},
        )
        db_session.add(chart)
        await db_session.flush()

        cq = ChartQuery(
            id=uuid.uuid4(),
            chart_id=chart.id,
            connector_name=connector_name,
            sql=sql,
            params=params or {},
            refresh_interval_seconds=refresh_interval_seconds,
        )
        db_session.add(cq)
        await db_session.flush()
        await db_session.commit()
        return chart, cq

    return _make_chart


# ─── Cloud-mode fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def settings_cloud_with_clerk() -> Settings:
    """Cloud-mode settings with Clerk configuration for tests."""
    return Settings.model_validate({
        "SP_DEPLOYMENT_MODE": "cloud",
        "ANTHROPIC_API_KEY": "sk-ant-test-key",
        "WORKSPACES_DATABASE_URL": _SQLITE_URL,
        "SP_CLERK_JWKS_URL": "http://fake-clerk.local/.well-known/jwks.json",
        "SP_CLERK_ISSUER": "https://fake-clerk.local",
    })


@pytest_asyncio.fixture
async def app_cloud(
    settings_cloud_with_clerk, session_factory, stub_spawner, event_bus
):
    """A cloud-mode app with a fake JwksClient injected via dependency override."""
    from tests.fixtures.jwks import _factory

    application = create_app()

    jwks_dict = _factory.jwks_dict()

    # Create a real JwksClient but override current_user_id at dependency level
    mock_http = AsyncMock()
    jwks_client = JwksClient(
        jwks_url="http://fake-clerk.local/.well-known/jwks.json",
        http_client=mock_http,
        ttl_seconds=600,
    )
    # Pre-populate cache so no real network call is made
    jwks_client._cached_keys = {
        jwk["kid"]: jwk for jwk in jwks_dict["keys"]
    }
    import time
    jwks_client._fetched_at = time.monotonic()

    application.dependency_overrides[get_settings] = lambda: settings_cloud_with_clerk
    application.dependency_overrides[_get_session_factory] = lambda: session_factory
    application.dependency_overrides[_get_spawner] = lambda: stub_spawner
    application.dependency_overrides[_get_bus] = lambda: event_bus

    application.state.session_factory = session_factory
    application.state.spawner = stub_spawner
    application.state.bus = event_bus
    application.state.chart_executor = None
    application.state.jwks_client = jwks_client

    yield application


@pytest_asyncio.fixture
async def client_cloud(app_cloud):
    async with AsyncClient(
        transport=ASGITransport(app=app_cloud), base_url="http://test"
    ) as c:
        yield c
