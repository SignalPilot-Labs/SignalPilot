"""Regression tests: extras-only credential fields survive PATCH without data-loss.

Covers two bugs fixed in round 4:
  1. trigger-tuple gap — extras-only fields (private_key, motherduck_token,
     connection_timeout, dataset, location, maximum_bytes_billed, …) now trigger
     a credential rebuild so patching them actually persists.
  2. rm_key wiped 'location' on every cred-rebuilding PATCH after round-3
     from_extras backfill; 'location' was removed from rm_key in round 4.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase
from gateway.models import ConnectionCreate, ConnectionUpdate
from gateway.store import Store

# ─── Fixtures ─────────────────────────────────────────────────────────────────

_ORG_ID = "test-org-extras"
_USER_ID = "test-user-extras"

_FAKE_PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----"
_FAKE_CREDENTIALS_JSON = json.dumps(
    {
        "type": "service_account",
        "project_id": "myproject",
        "private_key_id": "key1",
        "private_key": "-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----",
        "client_email": "sa@myproject.iam.gserviceaccount.com",
        "client_id": "12345",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """In-memory SQLite session — no Postgres required."""
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


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestPatchExtrasPreserved:
    @pytest.mark.asyncio
    async def test_patch_snowflake_warehouse_preserves_private_key(self, store: Store) -> None:
        """PATCHing warehouse on a Snowflake connection must preserve private_key in extras."""
        conn = ConnectionCreate(
            name="sf-conn",
            db_type="snowflake",
            account="myaccount",
            username="myuser",
            warehouse="old-warehouse",
            database="mydb",
            schema_name="public",
            private_key=_FAKE_PRIVATE_KEY,
        )
        await store.create_connection(conn)

        update = ConnectionUpdate(warehouse="new-warehouse")
        result = await store.update_connection("sf-conn", update)
        assert result is not None

        extras = await store.get_credential_extras("sf-conn")
        assert extras.get("private_key") == _FAKE_PRIVATE_KEY, (
            f"private_key was lost after PATCH warehouse; got {extras.get('private_key')!r}"
        )
        info = await store.get_connection("sf-conn")
        assert info is not None
        assert info.warehouse == "new-warehouse"

    @pytest.mark.asyncio
    async def test_patch_bigquery_dataset_triggers_rebuild_and_preserves_credentials_json(
        self, store: Store
    ) -> None:
        """PATCHing dataset (now a trigger field) must rewrite extras and preserve credentials_json."""
        conn = ConnectionCreate(
            name="bq-conn",
            db_type="bigquery",
            project="myproject",
            dataset="old-dataset",
            credentials_json=_FAKE_CREDENTIALS_JSON,
        )
        await store.create_connection(conn)

        update = ConnectionUpdate(dataset="new-dataset")
        result = await store.update_connection("bq-conn", update)
        assert result is not None

        extras = await store.get_credential_extras("bq-conn")
        assert extras.get("credentials_json") == _FAKE_CREDENTIALS_JSON, (
            f"credentials_json was lost after PATCH dataset; got {extras.get('credentials_json')!r}"
        )
        assert extras.get("dataset") == "new-dataset", (
            f"dataset was not updated in extras; got {extras.get('dataset')!r}"
        )

    @pytest.mark.asyncio
    async def test_patch_generic_host_preserves_connection_timeout(self, store: Store) -> None:
        """PATCHing host must preserve connection_timeout in extras."""
        conn = ConnectionCreate(
            name="pg-conn",
            db_type="postgres",
            host="old-host",
            port=5432,
            database="mydb",
            username="myuser",
            connection_timeout=30,
        )
        await store.create_connection(conn)

        update = ConnectionUpdate(host="new-host")
        result = await store.update_connection("pg-conn", update)
        assert result is not None

        extras = await store.get_credential_extras("pg-conn")
        assert extras.get("connection_timeout") == 30, (
            f"connection_timeout was lost after PATCH host; got {extras.get('connection_timeout')!r}"
        )

    @pytest.mark.asyncio
    async def test_patch_only_private_key_actually_persists(self, store: Store) -> None:
        """PATCHing only private_key must now trigger rebuild and persist the new value.

        Without the trigger-tuple fix, private_key was not in needs_cred_rebuild,
        so the extras were never rewritten and the new value was silently dropped.
        """
        conn = ConnectionCreate(
            name="sf-pk-conn",
            db_type="snowflake",
            account="myaccount",
            username="myuser",
            warehouse="mywarehouse",
            database="mydb",
            schema_name="public",
            private_key="OLD",
        )
        await store.create_connection(conn)

        update = ConnectionUpdate(private_key="NEW")
        result = await store.update_connection("sf-pk-conn", update)
        assert result is not None

        extras = await store.get_credential_extras("sf-pk-conn")
        assert extras.get("private_key") == "NEW", (
            f"private_key update was silently dropped; got {extras.get('private_key')!r}"
        )

    @pytest.mark.asyncio
    async def test_patch_bigquery_project_preserves_location(self, store: Store) -> None:
        """PATCHing project (cred-rebuild trigger) must NOT wipe location from extras.

        Without the rm_key fix, 'location' was popped from merged before
        ConnectionCreate reconstruction, causing _extract_credential_extras to
        see location=None and write None into extras_enc — silently dropping EU.
        """
        conn = ConnectionCreate(
            name="bq-loc-conn",
            db_type="bigquery",
            project="old-project",
            location="EU",
            credentials_json=_FAKE_CREDENTIALS_JSON,
        )
        await store.create_connection(conn)

        update = ConnectionUpdate(project="newproj")
        result = await store.update_connection("bq-loc-conn", update)
        assert result is not None

        extras = await store.get_credential_extras("bq-loc-conn")
        assert extras.get("location") == "EU", (
            f"location was wiped after PATCH project; got {extras.get('location')!r}"
        )
