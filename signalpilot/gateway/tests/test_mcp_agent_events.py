import asyncio
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.agent_execution import events
from gateway.db.models import MCPAgentEvent, MCPAgentThread


@pytest_asyncio.fixture
async def event_factory(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "events.db"))
    async with engine.begin() as conn:
        await conn.run_sync(MCPAgentThread.__table__.create)
        await conn.run_sync(MCPAgentEvent.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("gateway.db.engine.get_session_factory", lambda: factory)
    async with factory() as db:
        db.add(
            MCPAgentThread(
                id="thread",
                org_id="org",
                user_id="owner",
                run_id="run",
                status="running",
                expires_at=time.time() + 600,
                lease_expires_at=time.time() + 600,
                retained_until=time.time() + 3600,
                updated_at=time.time(),
                event_sequence=0,
                attempt=1,
                request={"connection_name": "warehouse"},
                history=[],
                result={},
                snapshot_key="snapshot",
            )
        )
        await db.commit()
    yield factory
    await engine.dispose()


@pytest.mark.parametrize(
    "sql, forbidden",
    [
        ("SELECT name FROM my_orders WHERE id=42 AND state='secret' /* password */", ["42", "secret", "password"]),
        (
            "SELECT 'private', 123.45, -789, true FROM my_orders -- comment-secret",
            ["private", "123", "789", "comment-secret"],
        ),
        ("SELECT $$private$$ FROM my_orders", ["private"]),
        ("SELECT X'abcdef' FROM my_orders", ["abcdef"]),
        ("SELECT N'private' FROM my_orders", ["private"]),
        ("SELECT E'private' FROM my_orders", ["private"]),
        ("SELECT U&'private' FROM my_orders", ["private"]),
        ("SELECT 0x123abc FROM my_orders", ["123abc", "x123abc"]),
        ("SELECT $tag$private$tag$ FROM my_orders", ["private"]),
        ("SELECT B'10101' FROM my_orders", ["10101"]),
        ('SELECT "spa_credential" FROM my_orders', ["spa_credential"]),
        ('SELECT "sk-ant-private-value" FROM my_orders', ["private-value"]),
        ("SELECT 'unterminated-private", ["private"]),
        ("SELECT 1; SELECT 'private'", ["private"]),
    ],
)
def test_sql_preview_drops_literals_comments_or_fails_closed(sql, forbidden):
    preview = events.sql_preview(sql)
    for value in forbidden:
        assert value not in preview


def test_preview_structure_and_parse_bound(monkeypatch):
    preview = events.sql_preview("SELECT order_id FROM my_orders WHERE customer_id = 'private'")
    assert "order_id" in preview and "my_orders" in preview and "?" in preview
    monkeypatch.setattr("sqlglot.parse", lambda *args: pytest.fail("Must reject oversize before parsing"))
    assert events.sql_preview("a" * 20001) == "SQL preview unavailable"


async def test_monotonic_sequences_cursor_cap_and_active_binding(event_factory, monkeypatch):
    results = await asyncio.gather(
        *[events.append_event(event_factory, "thread", "run", "org", {"stage": "working"}) for _ in range(10)]
    )
    assert sorted(event["sequence"] for event in results) == list(range(1, 11))
    async with event_factory() as db:
        assert [e["sequence"] for e in await events.read_events(db, "org", "thread", "run", 5, 3)] == [6, 7, 8]
        assert await events.read_events(db, "wrong", "thread", "run") == []
    assert await events.append_event(event_factory, "thread", "run", "wrong", {}) is None
    assert await events.append_event(event_factory, "thread", "wrong", "org", {}) is None
    monkeypatch.setattr(events, "MAX_EVENTS", 10)
    assert await events.append_event(event_factory, "thread", "run", "org", {}) is None
    monkeypatch.setattr(events, "MAX_EVENTS", 2000)
    async with event_factory() as db:
        row = await db.get(MCPAgentThread, "thread")
        row.status = "cancelled"
        await db.commit()
    assert await events.append_event(event_factory, "thread", "run", "org", {}) is None


@pytest.mark.parametrize("fails", [False, True])
async def test_query_start_is_visible_before_executor_returns(event_factory, monkeypatch, fails):
    from gateway.mcp.context import (
        mcp_allowed_connection_var,
        mcp_execution_identity_var,
        mcp_org_id_var,
        mcp_scopes_var,
        mcp_user_id_var,
    )
    from gateway.mcp.tools.query import query_database

    entered, release = asyncio.Event(), asyncio.Event()

    @asynccontextmanager
    async def store():
        yield object()

    async def execute(*args, **kwargs):
        entered.set()
        await release.wait()
        if fails:
            raise RuntimeError("private database password")
        return SimpleNamespace(
            row_count=7, execution_ms=12, result_id="r", completeness="complete", pii_redacted=[], rows=[]
        )

    monkeypatch.setattr("gateway.mcp.tools.query._store_session", store)
    monkeypatch.setattr("gateway.mcp.tools.query.governed_query_executor.execute", execute)
    monkeypatch.setattr("gateway.mcp.audit._audit_tool_call", AsyncMock())
    tokens = [
        (v, v.set(value))
        for v, value in [
            (mcp_execution_identity_var, "agent:run"),
            (mcp_org_id_var, "org"),
            (mcp_user_id_var, "owner"),
            (mcp_scopes_var, ["query"]),
            (mcp_allowed_connection_var, "warehouse"),
        ]
    ]
    try:
        task = asyncio.create_task(query_database(sql="SELECT order_id FROM my_orders WHERE customer='private'"))
        await asyncio.wait_for(entered.wait(), 3)
        async with event_factory() as db:
            visible = await events.read_events(db, "org", "thread", "run")
        assert not task.done()
        assert [e["type"] for e in visible] == ["query_started"]
        assert "my_orders" in visible[0]["sql_preview"] and "private" not in json.dumps(visible)
        release.set()
        if fails:
            with pytest.raises(RuntimeError):
                await task
        else:
            await task
        async with event_factory() as db:
            visible = await events.read_events(db, "org", "thread", "run")
        assert [e["type"] for e in visible] == ["query_started", "query_failed" if fails else "query_finished"]
        if not fails:
            assert visible[-1]["row_count"] == 7 and visible[-1]["duration_ms"] == 12
        assert "private" not in json.dumps(visible)
        assert "rows" not in visible[-1]
        assert "Query" in visible[-1]["label"]
        # Cross-owner contexts cannot inject activity into this run.
        mcp_user_id_var.set("other")
        assert await events.current_event({"type": "tool_started", "tool": "list_tables"}) is None
        denied = await query_database(sql="select 1", connection_name="other")
        assert "outside agent scope" in denied
        async with event_factory() as db:
            assert len(await events.read_events(db, "org", "thread", "run")) == 2
    finally:
        release.set()
        for variable, token in reversed(tokens):
            variable.reset(token)


@pytest.mark.parametrize(
    "path", ["../secret", "/etc/passwd", ".env.production", ".git/config", "target/result", "folder/.env.test"]
)
def test_runtime_paths_and_raw_text_are_sanitized(path):
    value = events.sanitize_event(
        {
            "type": "progress",
            "stage": "local_tool",
            "tool": "Read",
            "path": path,
            "message": "secret",
            "stdout": "private rows",
        }
    )
    assert "path" not in value
    assert "secret" not in json.dumps(value) and "private rows" not in json.dumps(value)


async def test_polling_is_audited_without_consuming_query_quota(monkeypatch):
    from unittest.mock import Mock

    from gateway.mcp.audit import _audit_tool_call
    from gateway.mcp.context import mcp_org_id_var

    increment = Mock()
    store = SimpleNamespace(append_audit=AsyncMock())

    @asynccontextmanager
    async def store_session():
        yield store

    monkeypatch.setattr("gateway.governance.plan_limits.daily_query_counter.increment", increment)
    monkeypatch.setattr("gateway.mcp.audit._store_session", store_session)
    token = mcp_org_id_var.set("org")
    try:
        for name in ("get_signalpilot_agent", "wait_signalpilot_agent"):
            await _audit_tool_call(name, {}, None, 1)
        increment.assert_not_called()
        assert store.append_audit.await_count == 2
        await _audit_tool_call("query_database", {}, None, 1)
        increment.assert_called_once_with("org")
    finally:
        mcp_org_id_var.reset(token)
