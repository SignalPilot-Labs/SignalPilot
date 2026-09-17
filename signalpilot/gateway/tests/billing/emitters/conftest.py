"""Fixtures for the emitter tests: in-memory SQLite schema, entitlements, ledger readers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.billing import GatewayCreditLedger, OrgEntitlement, local_entitlement
from gateway.db.models import GatewayBase

ORG = "org_billable"
USER = "user_1"
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(session_factory):
    async with session_factory() as sess:
        yield sess


@pytest.fixture
def team() -> OrgEntitlement:
    """A billable Team org: 10 seats, 30 models, 30 eval runs, 5,000 credits."""
    return OrgEntitlement(
        org_id=ORG,
        tier="team",
        status="active",
        included_seats=10,
        included_models=30,
        included_eval_runs=30,
        included_credits=5_000,
    )


@pytest.fixture
def enterprise() -> OrgEntitlement:
    return OrgEntitlement(
        org_id=ORG,
        tier="enterprise",
        status="active",
        included_seats=100,
        included_models=100,
        included_eval_runs=30,
        included_credits=75_000,
    )


@pytest.fixture
def unmetered() -> OrgEntitlement:
    """Local mode: everything on, nothing metered."""
    return local_entitlement(ORG)


async def ledger_rows(session: AsyncSession, org_id: str = ORG) -> list[GatewayCreditLedger]:
    stmt = select(GatewayCreditLedger).where(GatewayCreditLedger.org_id == org_id).order_by(GatewayCreditLedger.id)
    return list((await session.execute(stmt)).scalars())


class BrokenSession:
    """A session whose every use raises, to prove emitters never propagate."""

    def get_bind(self):
        raise RuntimeError("no bind")

    async def execute(self, *_args, **_kwargs):
        raise RuntimeError("boom")
