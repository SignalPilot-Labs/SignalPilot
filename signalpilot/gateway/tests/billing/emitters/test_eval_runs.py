"""Eval-run emitter: allowance position, the 31st run, idempotency, and the store hook."""

from __future__ import annotations

from datetime import timedelta

from gateway.billing import unit_quantity
from gateway.billing.emitters.eval_runs import emit_eval_run_credit
from gateway.db.models import GatewayEvalRun
from gateway.store import evals as evals_store

from .conftest import NOW, ORG, BrokenSession, ledger_rows


class TestAllowance:
    async def test_first_thirty_runs_are_included(self, session, team) -> None:
        for index in range(30):
            new_id = await emit_eval_run_credit(
                session, org_id=ORG, run_id=f"run-{index}", trigger="manual", entitlement=team, now=NOW
            )
            assert new_id is not None
        await session.commit()
        rows = await ledger_rows(session)
        assert len(rows) == 30
        assert all(
            (row.credits, row.reason, row.unit, row.source) == (0, "included", "eval_run", "eval") for row in rows
        )
        assert [row.payload["allowance_position"] for row in rows] == list(range(1, 31))
        assert rows[0].payload == {"allowance_position": 1, "included": 30, "trigger": "manual"}
        assert rows[0].idempotency_key == "eval_run:run-0"
        assert (rows[0].ref_type, rows[0].ref_id) == ("eval_run", "run-0")

    async def test_thirty_first_run_costs_fifty(self, session, team) -> None:
        for index in range(30):
            await emit_eval_run_credit(session, org_id=ORG, run_id=f"run-{index}", entitlement=team, now=NOW)
        await emit_eval_run_credit(session, org_id=ORG, run_id="run-30", entitlement=team, now=NOW)
        await session.commit()
        row = (await ledger_rows(session))[-1]
        assert (row.credits, row.reason) == (-50, "ok")
        assert row.payload["allowance_position"] == 31
        assert await unit_quantity(session, ORG, NOW.date(), "eval_run") == 31

    async def test_allowance_resets_each_period(self, session, team) -> None:
        for index in range(30):
            await emit_eval_run_credit(session, org_id=ORG, run_id=f"aug-{index}", entitlement=team, now=NOW)
        next_period = NOW + timedelta(days=30)
        await emit_eval_run_credit(session, org_id=ORG, run_id="oct-0", entitlement=team, now=next_period)
        await session.commit()
        row = (await ledger_rows(session))[-1]
        assert (row.credits, row.reason, row.payload["allowance_position"]) == (0, "included", 1)
        assert row.billing_period.isoformat() == "2026-10-01"

    async def test_zero_allowance_bills_from_the_first_run(self, session, team) -> None:
        from dataclasses import replace

        none_included = replace(team, included_eval_runs=0)
        await emit_eval_run_credit(session, org_id=ORG, run_id="run-0", entitlement=none_included, now=NOW)
        await session.commit()
        (row,) = await ledger_rows(session)
        assert (row.credits, row.reason) == (-50, "ok")


class TestContract:
    async def test_idempotent_per_run(self, session, team) -> None:
        first = await emit_eval_run_credit(session, org_id=ORG, run_id="run-0", entitlement=team, now=NOW)
        second = await emit_eval_run_credit(session, org_id=ORG, run_id="run-0", entitlement=team, now=NOW)
        await session.commit()
        assert first is not None and second is None
        assert len(await ledger_rows(session)) == 1

    async def test_unmetered_org_writes_nothing(self, session, unmetered) -> None:
        assert await emit_eval_run_credit(session, org_id=ORG, run_id="run-0", entitlement=unmetered) is None
        await session.commit()
        assert await ledger_rows(session) == []

    async def test_never_raises(self, team) -> None:
        assert await emit_eval_run_credit(BrokenSession(), org_id=ORG, run_id="run-0", entitlement=team) is None


class TestStoreHook:
    async def test_update_run_to_running_writes_the_row(self, session, team, monkeypatch) -> None:
        async def fake_entitlement(org_id: str):
            assert org_id == ORG
            return team

        monkeypatch.setattr("gateway.billing.emitters._base.get_entitlement", fake_entitlement)
        session.add(
            GatewayEvalRun(id="run-x", org_id=ORG, status="preparing", trigger="schedule", created_at=NOW.isoformat())
        )
        await session.commit()
        await evals_store.update_run(session, org_id=ORG, run_id="run-x", status="running", eval_set_name="core")
        run = await session.get(GatewayEvalRun, "run-x")
        assert run.status == "running"
        (row,) = await ledger_rows(session)
        assert row.idempotency_key == "eval_run:run-x"
        assert row.payload["trigger"] == "schedule"

    async def test_other_status_writes_do_not_bill(self, session, team, monkeypatch) -> None:
        async def fake_entitlement(org_id: str):
            return team

        monkeypatch.setattr("gateway.billing.emitters._base.get_entitlement", fake_entitlement)
        session.add(GatewayEvalRun(id="run-y", org_id=ORG, status="running", trigger="manual", created_at="x"))
        await session.commit()
        await evals_store.update_run(session, org_id=ORG, run_id="run-y", status="completed")
        assert await ledger_rows(session) == []
