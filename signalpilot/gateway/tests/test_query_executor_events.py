"""Governed query executor: chat event status parity, typed replay rows and
gateway-database failure classification (chat failure plan sections C and D).

The executor runs against an in-memory SQLite gateway database with a fake
warehouse connector; ``chat_store.append_event`` is captured instead of
written so no chat run row is needed.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase
from gateway.governance import query_executor_route, query_executor_run, query_planner
from gateway.governance.query_executor import (
    GovernedQueryContext,
    GovernedQueryError,
    GovernedQueryExecutor,
)
from gateway.governance.query_executor_types import encode_value, logical_type
from gateway.store import standalone_chat as chat_store

_SQL = "SELECT order_id, total, ordered_on FROM orders"


class _Connector:
    def __init__(self, rows: list[dict[str, Any]] | Exception) -> None:
        self._rows = rows
        self.calls = 0

    async def execute(self, _sql: str, params: Any = None, timeout: Any = None) -> list[dict[str, Any]]:
        self.calls += 1
        if isinstance(self._rows, Exception):
            raise self._rows
        return [dict(row) for row in self._rows]

    async def cancel_current_query(self) -> bool:
        return False

    def get_last_query_id(self) -> None:
        return None

    def get_last_query_stats(self) -> dict[str, Any]:
        return {}


def _rows(count: int = 2) -> list[dict[str, Any]]:
    return [
        {"order_id": i, "total": Decimal("12.50") if i % 2 else Decimal("3"), "ordered_on": datetime(2026, 1, i + 1, tzinfo=UTC)}
        for i in range(1, count + 1)
    ]


@pytest_asyncio.fixture
async def store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        fake = SimpleNamespace(session=session, user_id="user-a", _require_org_id=lambda: "org-a")

        async def get_connection(_name: str):
            return SimpleNamespace(db_type="postgres", pii_enabled=False, pii_rules=None)

        async def load_settings():
            return SimpleNamespace(blocked_tables=[])

        async def get_connection_string(_name: str) -> str:
            return "postgresql://user:pw@warehouse/db"

        async def get_credential_extras(_name: str) -> dict[str, Any]:
            return {}

        fake.get_connection = get_connection
        fake.load_settings = load_settings
        fake.get_connection_string = get_connection_string
        fake.get_credential_extras = get_credential_extras
        yield fake
    await engine.dispose()


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch):
    """Wire the executor to a fake connector; return (executor, events, set_rows)."""
    events: list[tuple[str, dict[str, Any]]] = []
    state: dict[str, Any] = {"connector": _Connector(_rows())}

    async def append_event(_db: Any, *, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    @asynccontextmanager
    async def connection(*_args: Any, **_kwargs: Any):
        yield state["connector"]

    async def require_execution_plan(*_args: Any, **_kwargs: Any):
        return SimpleNamespace(
            scout_row_limit=None,
            used_at=None,
            estimated_cost_usd=0.0,
            estimated_scan_rows=None,
            estimated_scan_bytes=None,
            estimated_output_rows=None,
            estimated_output_bytes=None,
            estimate_quality="approximate",
            purpose="test",
            proposal_id=None,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    # The SP_FEATURE_CHAT_* variables are kill switches (unset means on), so
    # the harness turns them off explicitly; a test re-enables what it needs.
    monkeypatch.setenv("SP_FEATURE_CHAT_SIZE_ROUTER", "0")
    monkeypatch.setenv("SP_FEATURE_CHAT_QUERY_APPROVAL", "0")
    monkeypatch.setenv("SP_FEATURE_CHAT_RUNTIME_RESULTS", "0")
    monkeypatch.setattr(chat_store, "append_event", append_event)
    monkeypatch.setattr(query_executor_run.pool_manager, "connection", connection)
    monkeypatch.setattr(
        query_executor_route, "load_annotations", lambda _o, _c: SimpleNamespace(blocked_tables=[], pii_columns={})
    )
    monkeypatch.setattr(query_planner, "require_execution_plan", require_execution_plan)

    def set_connector(connector: _Connector) -> None:
        state["connector"] = connector

    return GovernedQueryExecutor(), events, set_connector


def _context() -> GovernedQueryContext:
    return GovernedQueryContext(path="mcp", conversation_id="conv-a", run_id="run-a", plan_id="plan-a")


def _completed(events: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [payload for event_type, payload in events if event_type == "query_completed"]


async def _run(executor: GovernedQueryExecutor, store: Any, *, row_limit: int = 100):
    return await executor.execute(
        store, connection_name="production", sql=_SQL, row_limit=row_limit, timeout_seconds=10, context=_context()
    )


@pytest.mark.asyncio
async def test_query_completed_carries_status_on_all_four_paths(store, harness, monkeypatch):
    executor, events, set_connector = harness

    await _run(executor, store)
    await _run(executor, store)
    assert [p["status"] for p in _completed(events)] == ["completed", "reused"]
    assert _completed(events)[1]["reused"] is True

    set_connector(_Connector(RuntimeError("relation orders does not exist")))
    with pytest.raises(GovernedQueryError) as failed:
        await executor.execute(
            store, connection_name="production", sql="SELECT 1 AS one", row_limit=10, timeout_seconds=10, context=_context()
        )
    assert failed.value.code == "query_failed"
    assert _completed(events)[2]["status"] == "failed"
    assert _completed(events)[2]["error_code"] == "query_failed"

    monkeypatch.setenv("SP_FEATURE_CHAT_SIZE_ROUTER", "true")
    set_connector(_Connector([{"n": i} for i in range(10_001)]))
    with pytest.raises(GovernedQueryError) as rejected:
        await executor.execute(
            store, connection_name="production", sql="SELECT n FROM big", row_limit=10, timeout_seconds=10, context=_context()
        )
    assert rejected.value.code == "runtime_required"
    assert _completed(events)[3]["status"] == "rejected"
    assert _completed(events)[3]["actual_rows_exceeded"] == 10_000

    assert all("status" in payload for payload in _completed(events))


@pytest.mark.asyncio
async def test_decimal_column_is_numeric_on_first_and_reused_execution(store, harness):
    executor, events, _set_connector = harness

    first = await _run(executor, store)
    second = await _run(executor, store)

    assert [p["status"] for p in _completed(events)] == ["completed", "reused"]
    assert second.result_id == first.result_id
    for result in (first, second):
        totals = [row["total"] for row in result.rows]
        assert totals == [12.5, 3, 12.5, 3][: len(totals)]
        assert isinstance(totals[0], float) and isinstance(totals[1], int)
        assert result.rows[0]["ordered_on"] == "2026-01-02T00:00:00+00:00"
    assert first.rows == second.rows
    by_name = {column["name"]: column["logical_type"] for column in first.columns}
    assert by_name == {"order_id": "integer", "total": "number", "ordered_on": "timestamp"}
    assert second.columns == first.columns


@pytest.mark.asyncio
async def test_gateway_database_errors_are_retryable_not_query_failed(store, harness):
    executor, events, set_connector = harness
    set_connector(_Connector(OperationalError("SELECT 1", {}, Exception("connection was closed"))))

    with pytest.raises(GovernedQueryError) as raised:
        await _run(executor, store)

    assert raised.value.code == "gateway_db_unavailable"
    assert raised.value.retryable is True
    assert str(raised.value) == "SignalPilot's own database was unavailable; retry"
    (payload,) = _completed(events)
    assert payload["status"] == "failed"
    assert payload["error_code"] == "gateway_db_unavailable"
    assert payload["retryable"] is True


def test_typed_encoder_keeps_numbers_numeric_and_names_driver_types() -> None:
    assert encode_value(Decimal("3")) == 3 and isinstance(encode_value(Decimal("3")), int)
    assert encode_value(Decimal("2.75")) == 2.75 and isinstance(encode_value(Decimal("2.75")), float)
    assert encode_value(datetime(2026, 9, 17, 8, 0, tzinfo=UTC)) == "2026-09-17T08:00:00+00:00"
    assert encode_value(b"\x00\xff") == "AP8="
    assert encode_value({"k": [Decimal("1.5"), None]}) == {"k": [1.5, None]}
    assert logical_type(Decimal("1")) == "number"
    assert logical_type(datetime(2026, 1, 1).date()) == "date"
    assert logical_type(b"x") == "bytes"
