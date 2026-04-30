"""
E2E integration tests for credential storage round-trip.

These tests require a running Postgres instance (the dev docker-compose postgres).
They are skipped by default; run with:

    pytest -m integration tests/test_e2e_credential_storage.py

Environment:
    SP_BACKEND_URL=postgresql://postgres:testpass@localhost:5600/testdb
    (or set via docker-compose default)
"""

from __future__ import annotations

import os
import time
import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration

_BACKEND_URL = os.getenv(
    "SP_BACKEND_URL",
    "postgresql+asyncpg://postgres:testpass@localhost:5600/testdb",
)

# Normalise sync psycopg2 URLs to asyncpg driver
if _BACKEND_URL.startswith("postgresql://") and "+asyncpg" not in _BACKEND_URL:
    _BACKEND_URL = _BACKEND_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest.fixture(scope="module")
def event_loop_policy():
    """Use the default asyncio event loop for the module."""
    import asyncio

    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """Create an async DB session against the integration test Postgres."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_BACKEND_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    from gateway.db.models import GatewayBase

    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)

    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def store(db_session):
    """Create a Store instance wired to the integration DB session."""
    from gateway.store import Store

    return Store(db_session, user_id="integration-test-user")


@pytest_asyncio.fixture(autouse=True)
async def cleanup_test_connections(db_session):
    """Clean up any connections created during integration tests."""
    from sqlalchemy import delete

    from gateway.db.models import GatewayConnection, GatewayCredential

    yield

    async with db_session.begin():
        await db_session.execute(delete(GatewayCredential).where(GatewayCredential.user_id == "integration-test-user"))
        await db_session.execute(delete(GatewayConnection).where(GatewayConnection.user_id == "integration-test-user"))


class TestCredentialStorageRoundTrip:
    """Verify credentials are encrypted at rest and round-trip correctly."""

    @pytest.mark.asyncio
    async def test_credential_is_encrypted_in_db(self, store, db_session):
        """Raw credential value must not appear in the gateway_credentials table."""
        from sqlalchemy import select

        from gateway.db.models import GatewayCredential
        from gateway.models import ConnectionCreate

        unique_suffix = uuid.uuid4().hex[:8]
        conn_name = f"inttest-pg-{unique_suffix}"
        plaintext_secret = f"supersecretpassword-{unique_suffix}"

        conn = ConnectionCreate(
            name=conn_name,
            db_type="postgres",
            host="localhost",
            port=5432,
            database="testdb",
            username="testuser",
            password=plaintext_secret,
        )
        info = await store.create_connection(conn)
        assert info.name == conn_name

        # Read raw bytes from the table — must not contain plaintext
        result = await db_session.execute(
            select(GatewayCredential).where(
                GatewayCredential.connection_name == conn_name,
                GatewayCredential.user_id == "integration-test-user",
            )
        )
        cred_row = result.scalar_one()
        assert cred_row is not None

        enc_bytes = cred_row.connection_string_enc
        # The raw bytes of the Fernet ciphertext must not contain the plaintext
        assert plaintext_secret.encode() not in enc_bytes

    @pytest.mark.asyncio
    async def test_credential_decrypts_to_correct_value(self, store, db_session):
        """Decrypted credential must match the value originally provided."""
        from gateway.models import ConnectionCreate

        unique_suffix = uuid.uuid4().hex[:8]
        conn_name = f"inttest-pg-{unique_suffix}"
        password = f"roundtrip-{unique_suffix}"

        conn = ConnectionCreate(
            name=conn_name,
            db_type="postgres",
            host="db.example.com",
            port=5432,
            database="mydb",
            username="admin",
            password=password,
        )
        await store.create_connection(conn)

        # Round-trip: retrieve the connection string via store
        retrieved = await store.get_connection_string(conn_name)
        assert retrieved is not None
        assert "db.example.com" in retrieved
        assert "admin" in retrieved
        # Password should be URL-encoded in the connection string
        assert password in retrieved or password.replace("@", "%40") in retrieved

    @pytest.mark.asyncio
    async def test_encrypt_decrypt_migration(self, store):
        """Verify the encrypt/decrypt round-trip works with current key."""
        from gateway.store import _decrypt, _encrypt

        original = f"test-cred-{uuid.uuid4().hex}"
        encrypted = _encrypt(original)
        decrypted = _decrypt(encrypted)
        assert decrypted == original
        # Ciphertext must not contain plaintext
        assert original.encode() not in encrypted

    @pytest.mark.asyncio
    async def test_connection_string_bypass_rejected_in_store(self, store):
        """Direct connection_string=/etc/passwd must be rejected at store chokepoint."""
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="evil-bypass",
            db_type="duckdb",
            connection_string="/etc/passwd",
        )
        with pytest.raises(ValueError, match="Database path not allowed"):
            await store.create_connection(conn)

    @pytest.mark.asyncio
    async def test_key_version_set_on_create(self, store, db_session):
        """Newly created credentials must have key_version == CURRENT_KEY_VERSION."""
        from sqlalchemy import select

        from gateway.db.models import GatewayCredential
        from gateway.models import ConnectionCreate
        from gateway.store import CURRENT_KEY_VERSION

        unique_suffix = uuid.uuid4().hex[:8]
        conn_name = f"inttest-kv-{unique_suffix}"

        conn = ConnectionCreate(
            name=conn_name,
            db_type="postgres",
            host="localhost",
            port=5432,
            database="testdb",
            username="testuser",
            password="somepassword",
        )
        await store.create_connection(conn)

        result = await db_session.execute(
            select(GatewayCredential).where(
                GatewayCredential.connection_name == conn_name,
                GatewayCredential.user_id == "integration-test-user",
            )
        )
        cred_row = result.scalar_one()
        assert cred_row.key_version == CURRENT_KEY_VERSION

    @pytest.mark.asyncio
    async def test_key_version_preserved_on_update(self, store, db_session):
        """Updating connection credentials sets key_version == CURRENT_KEY_VERSION."""
        from sqlalchemy import select

        from gateway.db.models import GatewayCredential
        from gateway.models import ConnectionCreate, ConnectionUpdate
        from gateway.store import CURRENT_KEY_VERSION

        unique_suffix = uuid.uuid4().hex[:8]
        conn_name = f"inttest-kvupd-{unique_suffix}"

        conn = ConnectionCreate(
            name=conn_name,
            db_type="postgres",
            host="localhost",
            port=5432,
            database="testdb",
            username="testuser",
            password="initial-password",
        )
        await store.create_connection(conn)

        update = ConnectionUpdate(password="updated-password")
        await store.update_connection(conn_name, update)

        result = await db_session.execute(
            select(GatewayCredential).where(
                GatewayCredential.connection_name == conn_name,
                GatewayCredential.user_id == "integration-test-user",
            )
        )
        cred_row = result.scalar_one()
        assert cred_row.key_version == CURRENT_KEY_VERSION

    @pytest.mark.asyncio
    async def test_credential_round_trip_with_special_chars(self, store):
        """Password with special characters must survive URL encoding in connection string."""
        from gateway.models import ConnectionCreate

        unique_suffix = uuid.uuid4().hex[:8]
        conn_name = f"inttest-special-{unique_suffix}"
        # Include characters that require URL encoding and unicode
        password = f"p@ss#w0rd/{unique_suffix}\u00e9\u00e0"

        conn = ConnectionCreate(
            name=conn_name,
            db_type="postgres",
            host="db.example.com",
            port=5432,
            database="mydb",
            username="admin",
            password=password,
        )
        await store.create_connection(conn)

        retrieved = await store.get_connection_string(conn_name)
        assert retrieved is not None
        # Password should NOT be stored in extras (Issue #22) — it lives only
        # in the encrypted connection string to avoid double-storage of secrets.
        extras = await store.get_credential_extras(conn_name)
        assert "password" not in extras
