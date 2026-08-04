"""Legacy plaintext TLS material must block readiness in cloud mode.

Reads redact ca_cert/client_cert/client_key and new writes encrypt them, so a
pre-existing row is inert — but the plaintext copy is still on disk. Rewriting
credential storage implicitly at startup is riskier than refusing to serve, so
the gateway fails readiness and names the migration instead.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api import health as health_api
from gateway.db.models import GatewayBase, GatewayConnection
from gateway.models import ConnectionCreate
from gateway.store import Store, tls_migration

_ORG_ID = "test-org-tls-readiness"
_USER_ID = "test-user-tls-readiness"

_SSL_CONFIG = {
    "enabled": True,
    "mode": "verify-full",
    "ca_cert": "-----BEGIN CERTIFICATE-----\nCA\n-----END CERTIFICATE-----",
    "client_cert": "-----BEGIN CERTIFICATE-----\nCERT\n-----END CERTIFICATE-----",
    "client_key": "-----BEGIN PRIVATE KEY-----\nKEY\n-----END PRIVATE KEY-----",
}


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(session_factory) -> AsyncSession:
    async with session_factory() as session:
        yield session


@pytest.fixture
def store(db_session: AsyncSession) -> Store:
    return Store(db_session, org_id=_ORG_ID, user_id=_USER_ID)


@pytest.fixture(autouse=True)
def _fresh_cache():
    tls_migration.reset_readiness_cache()
    yield
    tls_migration.reset_readiness_cache()


@pytest.fixture
def wired_factory(monkeypatch, session_factory):
    """Point the readiness probe at the in-memory database; count its probes."""
    calls = {"n": 0}

    def _factory():
        calls["n"] += 1
        return session_factory

    monkeypatch.setattr("gateway.db.engine.get_session_factory", _factory)
    return calls


@pytest.fixture
def cloud_mode(monkeypatch):
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")


async def _seed_legacy_row(store: Store, session: AsyncSession, name: str = "legacy-tls") -> None:
    """Create a connection, then write the TLS material back into the plaintext
    column the way a pre-migration release did."""
    await store.create_connection(
        ConnectionCreate(
            name=name,
            db_type="postgres",
            host="db.example.com",
            port=5432,
            database="app",
            username="svc",
            password="pw",
            ssl=True,
            ssl_config=_SSL_CONFIG,
        )
    )
    row = (await session.execute(select(GatewayConnection).where(GatewayConnection.name == name))).scalar_one()
    row.ssl_config = dict(_SSL_CONFIG)
    await session.commit()


def _health_client() -> TestClient:
    app = FastAPI()
    app.include_router(health_api.router)
    return TestClient(app)


class TestProbe:
    @pytest.mark.asyncio
    async def test_clean_database_counts_zero(self, store, db_session):
        await store.create_connection(
            ConnectionCreate(
                name="modern",
                db_type="postgres",
                host="db.example.com",
                database="app",
                username="svc",
                password="pw",
                ssl=True,
                ssl_config=_SSL_CONFIG,
            )
        )
        assert await tls_migration.count_plaintext_tls_connections(db_session) == 0

    @pytest.mark.asyncio
    async def test_legacy_row_is_counted(self, store, db_session):
        await _seed_legacy_row(store, db_session)
        assert await tls_migration.count_plaintext_tls_connections(db_session) == 1


class TestReadiness:
    @pytest.mark.asyncio
    async def test_readiness_fails_while_legacy_rows_remain(self, store, db_session, wired_factory):
        await _seed_legacy_row(store, db_session)
        message = await tls_migration.check_plaintext_tls_readiness()
        assert message is not None
        assert tls_migration.MIGRATION_COMMAND in message

    @pytest.mark.asyncio
    async def test_readiness_passes_after_migration(self, store, db_session, wired_factory):
        await _seed_legacy_row(store, db_session)
        assert await tls_migration.check_plaintext_tls_readiness(force=True) is not None

        report = await tls_migration.migrate_plaintext_tls_config(store, dry_run=False)
        assert report["migrated"] == ["legacy-tls"]
        await db_session.commit()

        assert await tls_migration.check_plaintext_tls_readiness(force=True) is None

    @pytest.mark.asyncio
    async def test_clean_result_is_cached(self, store, db_session, wired_factory):
        assert await tls_migration.check_plaintext_tls_readiness() is None
        assert await tls_migration.check_plaintext_tls_readiness() is None
        assert wired_factory["n"] == 1


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_cloud_health_is_503_with_operator_message(
        self, store, db_session, wired_factory, cloud_mode
    ):
        await _seed_legacy_row(store, db_session)
        response = _health_client().get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["reason"] == "legacy_plaintext_tls_config"
        assert tls_migration.MIGRATION_COMMAND in body["detail"]

    @pytest.mark.asyncio
    async def test_cloud_health_recovers_after_migration(
        self, store, db_session, wired_factory, cloud_mode
    ):
        await _seed_legacy_row(store, db_session)
        assert _health_client().get("/health").status_code == 503

        await tls_migration.migrate_plaintext_tls_config(store, dry_run=False)
        await db_session.commit()
        tls_migration.reset_readiness_cache()

        response = _health_client().get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_local_mode_is_unaffected(self, store, db_session, wired_factory):
        await _seed_legacy_row(store, db_session)
        response = _health_client().get("/health")
        assert response.status_code == 200
        assert wired_factory["n"] == 0


class TestMigrationDefaults:
    @pytest.mark.asyncio
    async def test_helper_still_defaults_to_dry_run(self, store, db_session):
        await _seed_legacy_row(store, db_session)
        report = await tls_migration.migrate_plaintext_tls_config(store)
        assert report["dry_run"] is True
        assert report["migrated"] == []
        assert "legacy-tls" in report["affected"]

        row = (
            await db_session.execute(select(GatewayConnection).where(GatewayConnection.name == "legacy-tls"))
        ).scalar_one()
        assert row.ssl_config.get("client_key")  # untouched
