"""Credit ledger: idempotent writes, sign rules, and the period summary aggregate.

Runs on in-memory SQLite (``create_all`` of the shared metadata). The CHECK
constraints and the unique key are enforced there too, so the sign rules
and duplicate handling exercise the real schema. The partial index and the
JSONB variant are Postgres-only and are covered by the schema parity test.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.billing import (
    GatewayCreditLedger,
    LedgerEntry,
    has_entry,
    period_summary,
    unit_quantity,
    write_entry,
)
from gateway.db.models import GatewayBase

ORG = "org_test"
PERIOD = date(2026, 9, 1)
AT = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await engine.dispose()


def _entry(**overrides) -> LedgerEntry:
    base = {
        "org_id": ORG,
        "entry_type": "consume",
        "credits": -1,
        "unit": "query",
        "reason": "ok",
        "source": "chat",
        "idempotency_key": "query:1",
        "quantity": 1,
        "occurred_at": AT,
    }
    base.update(overrides)
    return LedgerEntry(**base)


class TestWriteEntry:
    async def test_returns_id_and_persists_row(self, session: AsyncSession) -> None:
        new_id = await write_entry(session, _entry(payload={"tables": ["orders"]}, ref_type="audit", ref_id="7"))
        await session.commit()
        assert isinstance(new_id, int)
        row = (await session.execute(select(GatewayCreditLedger).where(GatewayCreditLedger.id == new_id))).scalar_one()
        assert row.org_id == ORG
        assert row.credits == -1
        assert row.billing_period == PERIOD
        assert row.quantity == Decimal("1")
        assert row.payload == {"tables": ["orders"]}
        assert row.ref_id == "7"
        assert row.created_at is not None

    async def test_duplicate_idempotency_key_returns_none_without_raising(self, session: AsyncSession) -> None:
        first = await write_entry(session, _entry())
        second = await write_entry(session, _entry(credits=-50, unit="thread"))
        await session.commit()
        assert first is not None
        assert second is None
        rows = (await session.execute(select(GatewayCreditLedger))).scalars().all()
        assert len(rows) == 1
        assert rows[0].credits == -1
        assert await has_entry(session, "query:1")
        assert not await has_entry(session, "query:2")

    async def test_billing_period_defaults_to_utc_month_of_occurred_at(self, session: AsyncSession) -> None:
        late = datetime(2026, 9, 30, 23, 30, tzinfo=UTC)
        await write_entry(session, _entry(idempotency_key="a", occurred_at=late))
        await write_entry(session, _entry(idempotency_key="b", occurred_at=late, billing_period=date(2026, 10, 1)))
        await session.commit()
        periods = (
            (await session.execute(select(GatewayCreditLedger.billing_period).order_by(GatewayCreditLedger.id)))
            .scalars()
            .all()
        )
        assert periods == [date(2026, 9, 1), date(2026, 10, 1)]

    async def test_return_row_can_reverse_an_earlier_row(self, session: AsyncSession) -> None:
        thread_id = await write_entry(session, _entry(idempotency_key="thread:r1", unit="thread", credits=-50))
        ret_id = await write_entry(
            session,
            _entry(
                idempotency_key=f"return:{thread_id}",
                entry_type="return",
                unit="thread",
                credits=50,
                reason="flagged_wrong",
                reverses=thread_id,
            ),
        )
        await session.commit()
        row = (await session.execute(select(GatewayCreditLedger).where(GatewayCreditLedger.id == ret_id))).scalar_one()
        assert row.reverses == thread_id


class TestSignRules:
    @pytest.mark.parametrize(
        ("entry_type", "credits"),
        [("grant", -1), ("purchase", -5), ("return", -50), ("consume", 1), ("expire", 10)],
    )
    async def test_python_validation_rejects_wrong_sign(
        self, session: AsyncSession, entry_type: str, credits: int
    ) -> None:
        with pytest.raises(ValueError):
            await write_entry(session, _entry(entry_type=entry_type, credits=credits, unit="included"))

    @pytest.mark.parametrize(
        ("entry_type", "credits"),
        [("grant", 0), ("grant", 5000), ("consume", 0), ("consume", -1), ("adjust", -7), ("adjust", 7), ("expire", -3)],
    )
    async def test_valid_signs_are_accepted(self, session: AsyncSession, entry_type: str, credits: int) -> None:
        new_id = await write_entry(
            session,
            _entry(entry_type=entry_type, credits=credits, unit="manual", idempotency_key=f"{entry_type}:{credits}"),
        )
        await session.commit()
        assert new_id is not None

    @pytest.mark.parametrize("field", ["entry_type", "unit", "source"])
    async def test_enum_values_are_validated(self, session: AsyncSession, field: str) -> None:
        with pytest.raises(ValueError):
            await write_entry(session, _entry(**{field: "bogus"}))

    async def test_database_check_constraint_backstops_sign_rule(self, session: AsyncSession) -> None:
        """Bypass the Python validation to prove the CHECK exists in the schema."""
        session.add(
            GatewayCreditLedger(
                org_id=ORG,
                entry_type="consume",
                credits=5,
                unit="query",
                quantity=1,
                occurred_at=AT,
                billing_period=PERIOD,
                source="chat",
                reason="ok",
                idempotency_key="bad-sign",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    async def test_database_check_constraint_backstops_enum(self, session: AsyncSession) -> None:
        session.add(
            GatewayCreditLedger(
                org_id=ORG,
                entry_type="bogus",
                credits=0,
                unit="query",
                quantity=1,
                occurred_at=AT,
                billing_period=PERIOD,
                source="chat",
                reason="ok",
                idempotency_key="bad-enum",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


FIXTURE_ROWS = [
    # (entry_type, credits, unit, reason, key)
    ("grant", 5000, "included", "period_grant", f"grant:{ORG}:2026-09-01:included"),
    ("grant", 1000, "enterprise", "enterprise_grant", f"enterprise:{ORG}:g1"),
    ("purchase", 500, "manual", "manual", "manual:p1"),
    ("consume", -50, "thread", "ok", "thread:r1"),
    ("consume", -50, "thread", "ok", "thread:r2"),
    ("consume", 0, "thread", "failed", "thread:r3"),
    ("consume", -37, "query", "ok", "query:a1"),
    ("consume", -6000, "tokens", "ok", "tokens:chat:r1"),
    ("consume", 0, "eval_run", "included", "eval_run:e1"),
    ("consume", -50, "eval_run", "ok", "eval_run:e2"),
    ("return", 50, "thread", "flagged_wrong", "return:r1"),
    ("expire", -100, "included", "period_expire", f"expire:{ORG}:2026-09-01"),
    ("adjust", -13, "manual", "manual", "manual:adj1"),
]


async def _seed(session: AsyncSession) -> None:
    for entry_type, credits, unit, reason, key in FIXTURE_ROWS:
        assert (
            await write_entry(
                session,
                _entry(
                    entry_type=entry_type, credits=credits, unit=unit, reason=reason, idempotency_key=key, quantity=1
                ),
            )
            is not None
        )
    # Noise: another org and another period must not leak into the summary.
    await write_entry(session, _entry(org_id="org_other", credits=-999, idempotency_key="query:other"))
    await write_entry(
        session,
        _entry(credits=-999, idempotency_key="query:aug", occurred_at=datetime(2026, 8, 31, 23, 59, tzinfo=UTC)),
    )
    await session.commit()


class TestPeriodSummary:
    async def test_math_over_fixture_set(self, session: AsyncSession) -> None:
        await _seed(session)
        summary = await period_summary(session, ORG, PERIOD)
        assert summary.granted == 6000
        assert summary.purchased == 500
        assert summary.consumed == 50 + 50 + 37 + 6000 + 50
        assert summary.returned == 50
        assert summary.expired == 100
        assert summary.adjusted == -13
        credited = 6000 + 500 + 50 - 13
        assert summary.credited == credited
        assert summary.available == credited - 6187 - 100
        assert summary.overage == 0

    async def test_overage_when_consumption_exceeds_credit(self, session: AsyncSession) -> None:
        await write_entry(session, _entry(entry_type="grant", credits=100, unit="included", idempotency_key="g"))
        await write_entry(session, _entry(credits=-160, unit="tokens", idempotency_key="t"))
        await write_entry(session, _entry(entry_type="return", credits=10, unit="thread", idempotency_key="r"))
        await session.commit()
        summary = await period_summary(session, ORG, PERIOD)
        assert summary.available == -50
        assert summary.overage == 50

    async def test_empty_period_is_all_zero(self, session: AsyncSession) -> None:
        summary = await period_summary(session, ORG, date(2026, 1, 1))
        assert (summary.granted, summary.consumed, summary.available, summary.overage) == (0, 0, 0, 0)

    async def test_period_argument_is_normalised_to_first_of_month(self, session: AsyncSession) -> None:
        await write_entry(session, _entry(entry_type="grant", credits=7, unit="included", idempotency_key="g"))
        await session.commit()
        summary = await period_summary(session, ORG, date(2026, 9, 19))
        assert summary.period == PERIOD
        assert summary.granted == 7

    async def test_unit_quantity_counts_consume_rows_for_allowance_position(self, session: AsyncSession) -> None:
        await _seed(session)
        assert await unit_quantity(session, ORG, PERIOD, "eval_run") == Decimal("2")
        assert await unit_quantity(session, ORG, PERIOD, "thread") == Decimal("3")
        assert await unit_quantity(session, ORG, PERIOD, "seat_day") == Decimal("0")
