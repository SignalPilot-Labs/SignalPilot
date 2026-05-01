"""Shared pytest fixtures for the Workspaces API test suite.

DB strategy: SQLite in-memory via sqlite+aiosqlite:///:memory: with
execution_options={"schema_translate_map": {"workspaces": None}}. This
causes SQLAlchemy to rewrite all "workspaces.*" qualified names to
unqualified at statement-prepare time. Production Postgres engine is built
without the map. Alembic is NOT run in unit tests.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from workspaces_api.agent.spawner import StubSpawner
from workspaces_api.config import Settings, get_settings
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
    return Settings(
        SP_DEPLOYMENT_MODE="local",
        CLAUDE_CODE_OAUTH_TOKEN="test-token",
        WORKSPACES_DATABASE_URL=_SQLITE_URL,
    )


@pytest.fixture
def settings_cloud_byo() -> Settings:
    return Settings(
        SP_DEPLOYMENT_MODE="cloud",
        ANTHROPIC_API_KEY="sk-ant-test-key",
        WORKSPACES_DATABASE_URL=_SQLITE_URL,
    )


@pytest.fixture
def settings_cloud_no_key() -> Settings:
    return Settings(
        SP_DEPLOYMENT_MODE="cloud",
        WORKSPACES_DATABASE_URL=_SQLITE_URL,
    )


@pytest.fixture
def settings_cloud_metered() -> Settings:
    return Settings(
        SP_DEPLOYMENT_MODE="cloud",
        ANTHROPIC_API_KEY="sk-ant-test-key",
        WORKSPACES_DATABASE_URL=_SQLITE_URL,
    )


@pytest.fixture
def stub_spawner() -> StubSpawner:
    return StubSpawner()


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest_asyncio.fixture
async def app(settings_local, session_factory, stub_spawner, event_bus):
    application = create_app()

    application.dependency_overrides[get_settings] = lambda: settings_local
    application.dependency_overrides[_get_session_factory] = lambda: session_factory
    application.dependency_overrides[_get_spawner] = lambda: stub_spawner
    application.dependency_overrides[_get_bus] = lambda: event_bus

    application.state.session_factory = session_factory
    application.state.spawner = stub_spawner
    application.state.bus = event_bus

    yield application


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
