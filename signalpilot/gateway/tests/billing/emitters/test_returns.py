"""Thread returns: +50 reversing the thread row, once, only when it was billed."""

from __future__ import annotations

from datetime import timedelta

from gateway.billing import LedgerEntry, period_summary, write_entry
from gateway.billing.emitters.returns import return_thread

from .conftest import NOW, ORG, USER, BrokenSession, ledger_rows


async def _thread(session, run_id: str, credits: int, reason: str) -> int:
    new_id = await write_entry(
        session,
        LedgerEntry(
            org_id=ORG,
            entry_type="consume",
            credits=credits,
            unit="thread",
            quantity=1,
            reason=reason,
            source="chat",
            idempotency_key=f"thread:{run_id}",
            occurred_at=NOW,
            ref_type="chat_run",
            ref_id=run_id,
            user_id=USER,
        ),
    )
    assert new_id is not None
    return new_id


class TestReturn:
    async def test_returns_fifty_reversing_the_thread_row(self, session, team) -> None:
        original = await _thread(session, "run-1", -50, "ok")
        new_id = await return_thread(session, "run-1", "flagged_wrong", memo="wrong total", entitlement=team, now=NOW)
        await session.commit()
        assert new_id is not None
        rows = await ledger_rows(session)
        assert len(rows) == 2
        row = rows[1]
        assert (row.entry_type, row.credits, row.reason, row.unit, row.source) == (
            "return",
            50,
            "flagged_wrong",
            "thread",
            "chat",
        )
        assert row.reverses == original
        assert row.idempotency_key == f"return:{original}"
        assert (row.ref_type, row.ref_id, row.user_id) == ("chat_run", "run-1", USER)
        assert row.payload == {"run_id": "run-1", "memo": "wrong total", "original_reason": "ok"}
        summary = await period_summary(session, ORG, NOW.date())
        assert (summary.consumed, summary.returned, summary.available) == (50, 50, 0)

    async def test_return_after_period_close_lands_in_the_current_period(self, session, team) -> None:
        await _thread(session, "run-1", -50, "ok")
        later = NOW + timedelta(days=40)
        await return_thread(session, "run-1", entitlement=team, now=later)
        await session.commit()
        row = (await ledger_rows(session))[1]
        assert row.billing_period.isoformat() == "2026-10-01"

    async def test_unbilled_thread_returns_nothing(self, session, team) -> None:
        await _thread(session, "run-1", 0, "low_evidence")
        assert await return_thread(session, "run-1", entitlement=team) is None
        await session.commit()
        assert len(await ledger_rows(session)) == 1

    async def test_unknown_run_returns_nothing(self, session, team) -> None:
        assert await return_thread(session, "missing", entitlement=team) is None

    async def test_only_once(self, session, team) -> None:
        await _thread(session, "run-1", -50, "ok")
        first = await return_thread(session, "run-1", entitlement=team)
        second = await return_thread(session, "run-1", "manual", entitlement=team)
        await session.commit()
        assert first is not None and second is None
        assert len(await ledger_rows(session)) == 2

    async def test_invalid_reason_is_swallowed(self, session, team) -> None:
        await _thread(session, "run-1", -50, "ok")
        assert await return_thread(session, "run-1", "discount", entitlement=team) is None

    async def test_unmetered_org_writes_nothing(self, session, unmetered) -> None:
        await _thread(session, "run-1", -50, "ok")
        assert await return_thread(session, "run-1", entitlement=unmetered) is None

    async def test_never_raises(self, team) -> None:
        assert await return_thread(BrokenSession(), "run-1", entitlement=team) is None
