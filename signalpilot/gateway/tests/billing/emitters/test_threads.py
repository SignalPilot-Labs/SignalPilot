"""Thread emitter: the finalizer decision tree on a real SQLite schema."""

from __future__ import annotations

import time
import uuid
from datetime import timedelta

from gateway.billing import LedgerEntry, write_entry
from gateway.billing.emitters.threads import (
    emit_thread_credit,
    governed_query_count,
    normalize_prompt,
    prompt_hash,
)
from gateway.db.models import (
    GatewayChatMessage,
    GatewayChatRun,
    GatewayGovernedQueryExecution,
    GatewaySetting,
    GatewayStructuredQueryResult,
)

from .conftest import NOW, ORG, USER, BrokenSession, ledger_rows

PROMPT = "What was Q2 revenue, by region?"


async def _seed_run(session, *, status: str = "completed", prompt: str = PROMPT, user_id: str = USER) -> GatewayChatRun:
    conversation_id = str(uuid.uuid4())
    message = GatewayChatMessage(
        id=str(uuid.uuid4()),
        org_id=ORG,
        user_id=user_id,
        conversation_id=conversation_id,
        role="user",
        content=prompt,
        sequence=1,
        created_at=time.time(),
    )
    run = GatewayChatRun(
        id=str(uuid.uuid4()),
        org_id=ORG,
        user_id=user_id,
        conversation_id=conversation_id,
        project_id="proj-1",
        user_message_id=message.id,
        status=status,
        terminal_at=NOW,
    )
    session.add_all([message, run])
    await session.flush()
    return run


async def _seed_queries(session, run: GatewayChatRun, *, completed: int, with_result: int, blocked: int = 0) -> None:
    """Executions + their query ledger rows, as the query emitter would have left them."""
    for index in range(completed + blocked):
        ok = index < completed
        execution = GatewayGovernedQueryExecution(
            id=str(uuid.uuid4()),
            org_id=ORG,
            user_id=run.user_id,
            run_id=run.id,
            conversation_id=run.conversation_id,
            connection_name="warehouse",
            query_path="mcp",
            sql_hash=f"{index:064d}",
            status="completed" if ok else "failed",
            public_error_code=None if ok else "query_blocked",
            timeout_seconds=30,
            terminal_at=NOW,
        )
        session.add(execution)
        if ok and index < with_result:
            session.add(
                GatewayStructuredQueryResult(
                    id=str(uuid.uuid4()),
                    execution_id=execution.id,
                    org_id=ORG,
                    owner_user_id=run.user_id,
                    run_id=run.id,
                    saved_row_count=1,
                    source_completeness="unknown",
                    result_completeness="complete",
                    display_completeness="complete",
                )
            )
        await write_entry(
            session,
            LedgerEntry(
                org_id=ORG,
                entry_type="consume",
                credits=-1 if ok else 0,
                unit="query",
                quantity=1,
                reason="ok" if ok else "blocked",
                source="chat",
                idempotency_key=f"query:{execution.id}",
                occurred_at=NOW,
                ref_type="chat_run",
                ref_id=run.id,
                user_id=run.user_id,
            ),
        )
    await session.flush()


async def _thread_row(session, run_id: str):
    return next(row for row in await ledger_rows(session) if row.idempotency_key == f"thread:{run_id}")


class TestNormalization:
    def test_prompt_hash_ignores_case_punctuation_and_spacing(self) -> None:
        assert normalize_prompt("  What was Q2 revenue, by region?  ") == "what was q2 revenue by region"
        assert prompt_hash("What was Q2 revenue, by region?") == prompt_hash("what was q2 revenue by region")
        assert prompt_hash("revenue by region") != prompt_hash("revenue by country")


class TestDecision:
    async def test_successful_thread_costs_fifty(self, session, team) -> None:
        run = await _seed_run(session)
        await _seed_queries(session, run, completed=3, with_result=3)
        new_id = await emit_thread_credit(session, run, entitlement=team, now=NOW)
        await session.commit()
        assert new_id is not None
        row = await _thread_row(session, run.id)
        assert (row.credits, row.reason, row.unit, row.source) == (-50, "ok", "thread", "chat")
        assert (row.ref_type, row.ref_id, row.user_id) == ("chat_run", run.id, USER)
        assert row.payload["governed_queries"] == 3
        assert row.payload["evidence_share"] == 1.0
        assert row.payload["prompt_hash"] == prompt_hash(PROMPT)

    async def test_failed_run_is_free(self, session, team) -> None:
        run = await _seed_run(session, status="failed")
        run.public_error_code = "analysis_failed"
        await _seed_queries(session, run, completed=2, with_result=2)
        await emit_thread_credit(session, run, entitlement=team, now=NOW)
        await session.commit()
        row = await _thread_row(session, run.id)
        assert (row.credits, row.reason) == (0, "failed")
        assert row.payload["error_code"] == "analysis_failed"

    async def test_cancelled_run_is_free(self, session, team) -> None:
        run = await _seed_run(session, status="cancelled")
        await emit_thread_credit(session, run, entitlement=team, now=NOW)
        await session.commit()
        assert (await _thread_row(session, run.id)).reason == "failed"

    async def test_zero_queries_is_free(self, session, team) -> None:
        run = await _seed_run(session)
        await _seed_queries(session, run, completed=0, with_result=0, blocked=2)
        await emit_thread_credit(session, run, entitlement=team, now=NOW)
        await session.commit()
        row = await _thread_row(session, run.id)
        assert (row.credits, row.reason) == (0, "zero_queries")
        assert await governed_query_count(session, org_id=ORG, run_id=run.id) == 0

    async def test_low_evidence_is_free(self, session, team) -> None:
        run = await _seed_run(session)
        await _seed_queries(session, run, completed=5, with_result=3)
        await emit_thread_credit(session, run, entitlement=team, now=NOW)
        await session.commit()
        row = await _thread_row(session, run.id)
        assert (row.credits, row.reason) == (0, "low_evidence")
        assert row.payload["evidence_share"] == 0.6

    async def test_eighty_percent_evidence_is_billed(self, session, team) -> None:
        run = await _seed_run(session)
        await _seed_queries(session, run, completed=5, with_result=4)
        await emit_thread_credit(session, run, entitlement=team, now=NOW)
        await session.commit()
        assert (await _thread_row(session, run.id)).reason == "ok"

    async def test_cited_result_ids_in_final_message_take_precedence(self, session, team) -> None:
        run = await _seed_run(session)
        await _seed_queries(session, run, completed=2, with_result=2)
        final = GatewayChatMessage(
            id=str(uuid.uuid4()),
            org_id=ORG,
            user_id=USER,
            conversation_id=run.conversation_id,
            role="assistant",
            content="answer",
            metadata_json={"cited_result_ids": []},
            sequence=2,
            created_at=time.time(),
        )
        await emit_thread_credit(session, run, final_message=final, entitlement=team, now=NOW)
        await session.commit()
        row = await _thread_row(session, run.id)
        assert (row.reason, row.payload["evidence_backed"]) == ("low_evidence", 0)

    async def test_repeat_within_24h_is_free(self, session, team) -> None:
        first = await _seed_run(session)
        await _seed_queries(session, first, completed=1, with_result=1)
        await emit_thread_credit(session, first, entitlement=team, now=NOW)
        second = await _seed_run(session, prompt="what was q2 revenue by region")
        await _seed_queries(session, second, completed=1, with_result=1)
        await emit_thread_credit(session, second, entitlement=team, now=NOW + timedelta(hours=3))
        await session.commit()
        assert (await _thread_row(session, first.id)).credits == -50
        row = await _thread_row(session, second.id)
        assert (row.credits, row.reason) == (0, "repeat")

    async def test_repeat_after_24h_is_billed(self, session, team) -> None:
        first = await _seed_run(session)
        await _seed_queries(session, first, completed=1, with_result=1)
        await emit_thread_credit(session, first, entitlement=team, now=NOW)
        second = await _seed_run(session)
        await _seed_queries(session, second, completed=1, with_result=1)
        await emit_thread_credit(session, second, entitlement=team, now=NOW + timedelta(hours=25))
        await session.commit()
        assert (await _thread_row(session, second.id)).credits == -50

    async def test_repeat_is_per_user(self, session, team) -> None:
        first = await _seed_run(session)
        await _seed_queries(session, first, completed=1, with_result=1)
        await emit_thread_credit(session, first, entitlement=team, now=NOW)
        other = await _seed_run(session, user_id="user_2")
        await _seed_queries(session, other, completed=1, with_result=1)
        await emit_thread_credit(session, other, entitlement=team, now=NOW + timedelta(hours=1))
        await session.commit()
        assert (await _thread_row(session, other.id)).credits == -50

    async def test_tuning_user_is_free(self, session, team) -> None:
        session.add(GatewaySetting(org_id=ORG, settings_json={"tuning_users": [USER]}))
        run = await _seed_run(session)
        await _seed_queries(session, run, completed=3, with_result=3)
        await emit_thread_credit(session, run, entitlement=team, now=NOW)
        await session.commit()
        row = await _thread_row(session, run.id)
        assert (row.credits, row.reason) == (0, "tuning")


class TestContract:
    async def test_idempotent_per_run(self, session, team) -> None:
        run = await _seed_run(session)
        await _seed_queries(session, run, completed=1, with_result=1)
        first = await emit_thread_credit(session, run, entitlement=team, now=NOW)
        second = await emit_thread_credit(session, run, entitlement=team, now=NOW)
        await session.commit()
        assert first is not None and second is None
        assert sum(1 for row in await ledger_rows(session) if row.unit == "thread") == 1

    async def test_unmetered_org_writes_nothing(self, session, unmetered) -> None:
        run = await _seed_run(session)
        assert await emit_thread_credit(session, run, entitlement=unmetered, now=NOW) is None
        await session.commit()
        assert all(row.unit != "thread" for row in await ledger_rows(session))

    async def test_never_raises(self, team) -> None:
        run = GatewayChatRun(id="r", org_id=ORG, user_id=USER, conversation_id="c", project_id="p", user_message_id="m")
        assert await emit_thread_credit(BrokenSession(), run, entitlement=team) is None
