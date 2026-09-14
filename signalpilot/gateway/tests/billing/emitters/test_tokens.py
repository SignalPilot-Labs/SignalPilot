"""Token emitter: cost x 100, BYOK is free, payload carries counts and key source."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from gateway.billing.emitters.tokens import emit_token_credit, token_credits, usage_counts
from gateway.db.models import GatewayChatRun
from gateway.store.standalone_chat import worker as worker_store

from .conftest import NOW, ORG, USER, BrokenSession, ledger_rows

USAGE = {
    "input_tokens": 1200,
    "output_tokens": 340,
    "cache_creation_input_tokens": 50,
    "cache_read_input_tokens": 9000,
    "server_tool_use": {"web_search_requests": 0},
}


def _run(**overrides):
    base = {"id": str(uuid.uuid4()), "org_id": ORG, "user_id": USER}
    base.update(overrides)
    return SimpleNamespace(**base)


class TestRounding:
    @pytest.mark.parametrize(
        ("cost", "credits"),
        [(None, 0), (0.0, 0), (0.004, 0), (0.005, 1), (0.1234, 12), (0.125, 13), (1.0, 100), (2.499, 250)],
    )
    def test_cost_to_credits(self, cost, credits) -> None:
        assert token_credits(cost) == credits

    def test_usage_counts_keeps_only_token_integers(self) -> None:
        assert usage_counts(USAGE) == {
            "input_tokens": 1200,
            "output_tokens": 340,
            "cache_creation_input_tokens": 50,
            "cache_read_input_tokens": 9000,
        }
        assert usage_counts(None) == {}


class TestEmit:
    async def test_platform_key_consumes_credits(self, session, team) -> None:
        run = _run()
        new_id = await emit_token_credit(
            session, run, cost_usd=0.1234, usage=USAGE, key_source="platform", entitlement=team, now=NOW
        )
        await session.commit()
        assert new_id is not None
        (row,) = await ledger_rows(session)
        assert (row.credits, row.reason, row.unit, row.source) == (-12, "ok", "tokens", "chat")
        assert row.idempotency_key == f"tokens:chat:{run.id}"
        assert (row.ref_type, row.ref_id, row.user_id) == ("chat_run", run.id, USER)
        assert row.payload["input_tokens"] == 1200
        assert row.payload["cache_read_input_tokens"] == 9000
        assert row.payload["key_source"] == "platform"
        assert row.payload["cost_usd"] == 0.1234
        assert "model" not in row.payload

    async def test_org_key_is_byok_and_free(self, session, team) -> None:
        await emit_token_credit(session, _run(), cost_usd=3.5, usage=USAGE, key_source="org", entitlement=team)
        await session.commit()
        (row,) = await ledger_rows(session)
        assert (row.credits, row.reason) == (0, "byok")
        assert row.payload["key_source"] == "org"
        assert row.payload["cost_usd"] == 3.5

    async def test_improvement_token_is_service_work(self, session, team) -> None:
        await emit_token_credit(session, _run(), cost_usd=0.5, usage=None, key_source="improvement", entitlement=team)
        await session.commit()
        (row,) = await ledger_rows(session)
        assert (row.credits, row.reason) == (0, "service_identity")

    async def test_model_name_from_usage(self, session, team) -> None:
        usage = {**USAGE, "modelUsage": {"claude-opus-4-1": {"inputTokens": 1}}}
        await emit_token_credit(session, _run(), cost_usd=0.01, usage=usage, key_source="platform", entitlement=team)
        await session.commit()
        (row,) = await ledger_rows(session)
        assert row.payload["model"] == "claude-opus-4-1"

    async def test_unknown_key_source_bills_as_platform_free_of_cost(self, session, team) -> None:
        await emit_token_credit(session, _run(), cost_usd=None, usage=USAGE, key_source="???", entitlement=team)
        await session.commit()
        (row,) = await ledger_rows(session)
        assert (row.credits, row.reason, row.payload["key_source"]) == (0, "ok", "none")

    async def test_idempotent_per_run(self, session, team) -> None:
        run = _run()
        first = await emit_token_credit(session, run, cost_usd=0.2, usage=None, key_source="platform", entitlement=team)
        second = await emit_token_credit(
            session, run, cost_usd=0.9, usage=None, key_source="platform", entitlement=team
        )
        await session.commit()
        assert first is not None and second is None
        (row,) = await ledger_rows(session)
        assert row.credits == -20

    async def test_unmetered_org_writes_nothing(self, session, unmetered) -> None:
        assert (
            await emit_token_credit(
                session, _run(), cost_usd=1.0, usage=None, key_source="platform", entitlement=unmetered
            )
            is None
        )
        await session.commit()
        assert await ledger_rows(session) == []

    async def test_never_raises(self, team) -> None:
        assert (
            await emit_token_credit(
                BrokenSession(), _run(), cost_usd=1.0, usage=None, key_source="platform", entitlement=team
            )
            is None
        )


class TestStoreHook:
    async def test_record_run_usage_writes_the_row_in_the_same_commit(self, session, team, monkeypatch) -> None:
        async def fake_entitlement(org_id: str):
            return team

        monkeypatch.setattr("gateway.billing.emitters._base.get_entitlement", fake_entitlement)
        run = GatewayChatRun(
            id="run-t",
            org_id=ORG,
            user_id=USER,
            conversation_id="conv",
            project_id="proj",
            user_message_id="msg",
            status="running",
            lease_owner="worker-1",
        )
        session.add(run)
        await session.commit()
        ok = await worker_store.record_run_usage(
            session, run_id="run-t", worker_id="worker-1", cost_usd=0.42, usage=USAGE, key_source="platform"
        )
        assert ok is True
        assert run.cost_usd == 0.42
        (row,) = await ledger_rows(session)
        assert (row.credits, row.idempotency_key) == (-42, "tokens:chat:run-t")

    async def test_record_run_usage_default_key_source_is_none(self, session, team, monkeypatch) -> None:
        async def fake_entitlement(org_id: str):
            return team

        monkeypatch.setattr("gateway.billing.emitters._base.get_entitlement", fake_entitlement)
        session.add(
            GatewayChatRun(
                id="run-u",
                org_id=ORG,
                user_id=USER,
                conversation_id="conv",
                project_id="proj",
                user_message_id="msg",
                status="running",
                lease_owner="worker-1",
            )
        )
        await session.commit()
        await worker_store.record_run_usage(session, run_id="run-u", worker_id="worker-1", cost_usd=0.1, usage=None)
        (row,) = await ledger_rows(session)
        assert row.payload["key_source"] == "none"
