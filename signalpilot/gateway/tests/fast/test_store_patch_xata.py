"""Verify that PATCH /connections persists Xata extras.

The update rebuilds credentials when Xata fields change. The update preserves
unspecified extras.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase
from gateway.models import ConnectionCreate, ConnectionUpdate
from gateway.store import Store

# Define test fixtures.

_ORG_ID = "test-org-xata"
_USER_ID = "test-user-xata"
_CONN_NAME = "xata-test-conn"


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """In-memory SQLite session. no Postgres required."""
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


# Run the following tests.


class TestPatchXataExtrasPreserved:
    @pytest.mark.asyncio
    async def test_patch_xata_api_url_persists_and_retains_org(self, store: Store) -> None:
        """PATCHing xata_api_url must persist the new value AND keep xata_org intact."""
        # Create a Xata connection with both xata_api_url and xata_org set.
        conn = ConnectionCreate(
            name=_CONN_NAME,
            db_type="xata",
            database="mydb",
            xata_api_key="xau_testkey",
            xata_organization="myorg",
            xata_project="prj_abc",
            xata_api_url="https://api.xata.io",
            xata_org="my-org",
        )
        await store.create_connection(conn)

        # PATCH: change only xata_api_url (omit xata_org. it must survive).
        update = ConnectionUpdate(xata_api_url="https://api.eu.example.com/db")
        result = await store.update_connection(_CONN_NAME, update)
        assert result is not None, "update_connection returned None — connection not found"

        # Re-fetch extras and assert both values are present.
        extras = await store.get_credential_extras(_CONN_NAME)

        assert extras.get("xata_api_url") == "https://api.eu.example.com/db", (
            f"xata_api_url not updated in extras; got {extras.get('xata_api_url')!r}"
        )
        assert extras.get("xata_organization") == "myorg", (
            "the org was wiped from extras on PATCH; got "
            f"{extras.get('xata_organization')!r}"
        )
