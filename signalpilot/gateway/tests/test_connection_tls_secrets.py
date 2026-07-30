"""Tests that TLS certificates and private keys never reach plaintext storage.

The ssh_tunnel path has always stripped its secrets before writing the metadata
column; ssl_config did not, so a client_key PEM sat in a plaintext JSON column and
flowed out of every read-scoped list/get and the export manifest.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase, GatewayConnection
from gateway.models import ConnectionCreate, ConnectionUpdate
from gateway.store import Store

_ORG_ID = "test-org-tls"
_USER_ID = "test-user-tls"

_CLIENT_KEY = "-----BEGIN PRIVATE KEY-----\nTLSCLIENTKEYMATERIAL\n-----END PRIVATE KEY-----"
_CLIENT_CERT = "-----BEGIN CERTIFICATE-----\nTLSCLIENTCERT\n-----END CERTIFICATE-----"
_CA_CERT = "-----BEGIN CERTIFICATE-----\nTLSCACERT\n-----END CERTIFICATE-----"

_SSL_CONFIG = {
    "enabled": True,
    "mode": "verify-full",
    "ca_cert": _CA_CERT,
    "client_cert": _CLIENT_CERT,
    "client_key": _CLIENT_KEY,
}


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def store(db_session: AsyncSession) -> Store:
    return Store(db_session, org_id=_ORG_ID, user_id=_USER_ID)


def _conn(name: str = "tls-conn") -> ConnectionCreate:
    return ConnectionCreate(
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


async def _row(session: AsyncSession, name: str) -> GatewayConnection:
    result = await session.execute(select(GatewayConnection).where(GatewayConnection.name == name))
    return result.scalar_one()


class TestTlsSecretsNotInPlaintextColumn:
    @pytest.mark.asyncio
    async def test_create_does_not_persist_pem_in_metadata_column(self, store, db_session):
        """The plaintext ssl_config column keeps mode metadata only."""
        await store.create_connection(_conn())

        row = await _row(db_session, "tls-conn")
        assert row.ssl_config == {"enabled": True, "mode": "verify-full"}
        assert _CLIENT_KEY not in json.dumps(row.ssl_config)

    @pytest.mark.asyncio
    async def test_tls_material_lands_in_encrypted_extras(self, store):
        """The certs/key are still available to the connector, via the encrypted extras."""
        await store.create_connection(_conn())

        extras = await store.get_credential_extras("tls-conn")
        assert extras["ssl_config"]["client_key"] == _CLIENT_KEY
        assert extras["ssl_config"]["client_cert"] == _CLIENT_CERT
        assert extras["ssl_config"]["ca_cert"] == _CA_CERT

    @pytest.mark.asyncio
    async def test_update_does_not_persist_pem_in_metadata_column(self, store, db_session):
        """PATCHing ssl_config keeps the same split: metadata plain, secrets encrypted."""
        await store.create_connection(_conn())

        rotated_key = _CLIENT_KEY.replace("MATERIAL", "ROTATED")
        await store.update_connection(
            "tls-conn",
            ConnectionUpdate(ssl_config={**_SSL_CONFIG, "mode": "verify-ca", "client_key": rotated_key}),
        )

        row = await _row(db_session, "tls-conn")
        assert row.ssl_config == {"enabled": True, "mode": "verify-ca"}
        extras = await store.get_credential_extras("tls-conn")
        assert extras["ssl_config"]["client_key"] == rotated_key

    @pytest.mark.asyncio
    async def test_unrelated_patch_preserves_stored_tls_material(self, store):
        """A PATCH of another field must not drop the encrypted certs/key."""
        await store.create_connection(_conn())
        await store.update_connection("tls-conn", ConnectionUpdate(port=5433))

        extras = await store.get_credential_extras("tls-conn")
        assert extras["ssl_config"]["client_key"] == _CLIENT_KEY


class TestTlsSecretsRedactedOnRead:
    @pytest.mark.asyncio
    async def test_get_and_list_never_return_the_private_key(self, store):
        await store.create_connection(_conn())

        info = await store.get_connection("tls-conn")
        assert info.ssl_config.model_dump() == {
            "enabled": True,
            "mode": "verify-full",
            "ca_cert": None,
            "client_cert": None,
            "client_key": None,
        }
        listed = await store.list_connections()
        assert _CLIENT_KEY not in json.dumps([c.model_dump() for c in listed])

    @pytest.mark.asyncio
    async def test_legacy_plaintext_row_is_redacted_on_read(self, store, db_session):
        """Rows written before the split still must not leak through a response."""
        await store.create_connection(_conn())
        row = await _row(db_session, "tls-conn")
        row.ssl_config = dict(_SSL_CONFIG)  # simulate a pre-fix row
        await db_session.commit()

        info = await store.get_connection("tls-conn")
        assert info.ssl_config.client_key is None
        assert info.ssl_config.client_cert is None
        assert info.ssl_config.ca_cert is None
        assert info.ssl_config.mode == "verify-full"

    @pytest.mark.asyncio
    async def test_export_manifest_excludes_tls_secrets(self, store):
        """Even the credential-bearing export carries TLS mode only."""
        from gateway.api.connections.porting import ExportRequest, export_connections

        await store.create_connection(_conn())

        request = SimpleNamespace(
            headers={},
            client=None,
            state=SimpleNamespace(auth={"auth_method": "local_key"}),
        )
        manifest = await export_connections(
            ExportRequest(include_credentials=True, confirm=True),
            store,
            request,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )

        blob = json.dumps(manifest)
        assert _CLIENT_KEY not in blob
        assert _CLIENT_CERT not in blob
        assert _CA_CERT not in blob
        assert manifest["connections"][0]["ssl_config"] == {"enabled": True, "mode": "verify-full"}


class TestTlsMigrationHelper:
    @pytest.mark.asyncio
    async def test_dry_run_reports_without_writing(self, store, db_session):
        from gateway.store.tls_migration import migrate_plaintext_tls_config

        await store.create_connection(_conn())
        row = await _row(db_session, "tls-conn")
        row.ssl_config = dict(_SSL_CONFIG)
        await db_session.commit()

        report = await migrate_plaintext_tls_config(store)
        assert report["dry_run"] is True
        assert report["affected"] == {"tls-conn": ["ca_cert", "client_cert", "client_key"]}
        assert report["migrated"] == []
        row = await _row(db_session, "tls-conn")
        assert row.ssl_config["client_key"] == _CLIENT_KEY

    @pytest.mark.asyncio
    async def test_apply_moves_material_and_scrubs_the_column(self, store, db_session):
        from gateway.store.tls_migration import migrate_plaintext_tls_config

        await store.create_connection(_conn())
        row = await _row(db_session, "tls-conn")
        row.ssl_config = dict(_SSL_CONFIG)
        await db_session.commit()

        report = await migrate_plaintext_tls_config(store, dry_run=False)
        assert report["migrated"] == ["tls-conn"]
        assert report["failed"] == {}

        row = await _row(db_session, "tls-conn")
        assert row.ssl_config == {"enabled": True, "mode": "verify-full"}
        extras = await store.get_credential_extras("tls-conn")
        assert extras["ssl_config"]["client_key"] == _CLIENT_KEY
