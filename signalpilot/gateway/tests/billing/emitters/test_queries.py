"""Governed query emitter: one row per execution, outcome and source rules, never raises."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from gateway.billing import service_identity
from gateway.billing.emitters.queries import (
    COUNTED_QUERY_PATHS,
    derive_source,
    emit_query_credit,
    query_outcome,
)
from gateway.db.models import GatewayGovernedQueryExecution

from .conftest import NOW, ORG, USER, BrokenSession, ledger_rows


def _execution(**overrides) -> GatewayGovernedQueryExecution:
    base = {
        "id": str(uuid.uuid4()),
        "org_id": ORG,
        "user_id": USER,
        "connection_name": "warehouse",
        "query_path": "mcp",
        "sql_hash": "a" * 64,
        "status": "completed",
        "timeout_seconds": 30,
        "run_id": None,
        "conversation_id": None,
        "terminal_at": NOW,
    }
    base.update(overrides)
    return GatewayGovernedQueryExecution(**base)


class TestOutcome:
    def test_completed_costs_one_credit(self) -> None:
        assert query_outcome(_execution()) == (-1, "ok")

    @pytest.mark.parametrize("code", ["runtime_required", "aggregate_required", "result_too_large"])
    def test_route_rejections_reached_the_warehouse(self, code: str) -> None:
        assert query_outcome(_execution(status="failed", public_error_code=code)) == (-1, "ok")

    @pytest.mark.parametrize("code", ["query_blocked", "credentials_missing", "query_failed", "query_timeout"])
    def test_blocked_or_refused_is_free(self, code: str) -> None:
        assert query_outcome(_execution(status="failed", public_error_code=code)) == (0, "blocked")

    def test_cancelled_is_free(self) -> None:
        assert query_outcome(_execution(status="cancelled", public_error_code="query_cancelled")) == (0, "blocked")


class TestSource:
    def test_mapping(self) -> None:
        assert derive_source(_execution(query_path="dashboard")) == "dashboard"
        assert derive_source(_execution(query_path="mcp", run_id="run-1")) == "chat"
        assert derive_source(_execution(query_path="dataset_ref", run_id="run-1")) == "chat"
        assert derive_source(_execution(query_path="mcp")) == "mcp"
        assert derive_source(_execution(query_path="sdk")) == "notebook"
        assert derive_source(_execution(query_path="direct_api")) == "notebook"
        assert derive_source(_execution(query_path="mcp", user_id="eval-runner")) == "eval"

    def test_eval_context_var_wins(self) -> None:
        from gateway.mcp.context import mcp_eval_run_var

        token = mcp_eval_run_var.set("eval-run-1")
        try:
            assert derive_source(_execution(query_path="mcp", run_id="run-1")) == "eval"
        finally:
            mcp_eval_run_var.reset(token)

    def test_every_execution_path_is_counted(self) -> None:
        assert COUNTED_QUERY_PATHS == {"direct_api", "mcp", "sdk", "dashboard", "dataset_ref"}


class TestEmit:
    async def test_completed_query_in_same_transaction(self, session, team) -> None:
        execution = _execution(run_id="run-1", conversation_id="conv-1", row_count=12)
        session.add(execution)
        new_id = await emit_query_credit(session, execution, entitlement=team)
        await session.commit()
        rows = await ledger_rows(session)
        assert new_id is not None and len(rows) == 1
        row = rows[0]
        assert (row.credits, row.reason, row.unit, row.source) == (-1, "ok", "query", "chat")
        assert row.idempotency_key == f"query:{execution.id}"
        assert (row.ref_type, row.ref_id) == ("chat_run", "run-1")
        assert row.user_id == USER
        assert row.billing_period.isoformat() == "2026-09-01"
        assert row.payload["execution_id"] == execution.id
        assert row.payload["row_count"] == 12

    async def test_rollback_drops_the_ledger_row_with_the_execution(self, session, team) -> None:
        execution = _execution()
        session.add(execution)
        await emit_query_credit(session, execution, entitlement=team)
        await session.rollback()
        assert await ledger_rows(session) == []

    async def test_blocked_writes_zero_credit_row(self, session, team) -> None:
        execution = _execution(status="failed", public_error_code="query_blocked")
        await emit_query_credit(session, execution, entitlement=team)
        await session.commit()
        (row,) = await ledger_rows(session)
        assert (row.credits, row.reason) == (0, "blocked")
        assert (row.ref_type, row.ref_id) == ("query_execution", execution.id)
        assert row.payload["error_code"] == "query_blocked"

    async def test_service_user_writes_zero_credit_row(self, session, team) -> None:
        await emit_query_credit(session, _execution(user_id="gateway"), entitlement=team)
        await session.commit()
        (row,) = await ledger_rows(session)
        assert (row.credits, row.reason) == (0, "service_identity")

    async def test_service_identity_context_wins_over_user_id(self, session, team) -> None:
        with service_identity():
            await emit_query_credit(session, _execution(), entitlement=team)
        await session.commit()
        (row,) = await ledger_rows(session)
        assert row.reason == "service_identity"

    async def test_explicit_source_override(self, session, team) -> None:
        await emit_query_credit(session, _execution(), source="schedule", entitlement=team)
        await session.commit()
        (row,) = await ledger_rows(session)
        assert row.source == "schedule"

    async def test_exactly_one_row_per_execution(self, session, team) -> None:
        execution = _execution()
        first = await emit_query_credit(session, execution, entitlement=team)
        execution.status = "failed"
        execution.public_error_code = "result_persistence_failed"
        second = await emit_query_credit(session, execution, entitlement=team)
        await session.commit()
        assert first is not None and second is None
        assert len(await ledger_rows(session)) == 1

    async def test_unmetered_org_writes_nothing(self, session, unmetered) -> None:
        assert await emit_query_credit(session, _execution(), entitlement=unmetered) is None
        await session.commit()
        assert await ledger_rows(session) == []

    async def test_unknown_query_path_is_ignored(self, session, team) -> None:
        assert await emit_query_credit(session, _execution(query_path="metadata"), entitlement=team) is None
        await session.commit()
        assert await ledger_rows(session) == []

    async def test_never_raises_into_the_caller(self, team) -> None:
        assert await emit_query_credit(BrokenSession(), _execution(), entitlement=team) is None

    async def test_occurred_at_falls_back_to_now(self, session, team) -> None:
        before = datetime.now(UTC)
        await emit_query_credit(session, _execution(terminal_at=None), entitlement=team)
        await session.commit()
        (row,) = await ledger_rows(session)
        assert row.occurred_at >= before.replace(tzinfo=None) or row.occurred_at >= before
