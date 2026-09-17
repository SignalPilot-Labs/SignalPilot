"""Per-user usage endpoints: /api/usage/org (admin) and /api/usage/me (read).

Auth is injected the same way as tests/test_secfix_admin_gates.py (the auth
middleware's dispatch is replaced so each test sets request.state.auth), but
the fake store carries a real sqlite session so the grouped SQL in
gateway/store/usage.py runs for real. The database is file-backed with a
NullPool because the TestClient runs every request on its own event loop.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import Request, Response
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.middleware.base import RequestResponseEndpoint

from gateway.api.deps import get_store
from gateway.db.models import GatewayAuditLog, GatewayBase, GatewayChatConversation, GatewayChatRun
from tests.mcp_connectors_support import _auth_middlewares, isolated_app

ORG = "org-1"
NOW = time.time()
RECENT = NOW - 60
TWO_DAYS_AGO = NOW - 2 * 86400 - 60
ANCIENT = NOW - 100 * 86400


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).date().isoformat()


def _dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=UTC)


_CURRENT_AUTH: dict[str, Any] = {}
_DB: dict[str, Any] = {}
_AUDITED: list[Any] = []


def _as_api_key(*scopes: str, user_id: str | None = "u1") -> None:
    _CURRENT_AUTH.clear()
    _CURRENT_AUTH.update({"auth_method": "api_key", "user_id": user_id, "org_id": ORG, "scopes": list(scopes)})


def _as_sandbox() -> None:
    _CURRENT_AUTH.clear()
    _CURRENT_AUTH.update(
        {
            "auth_method": "notebook_session",
            "user_id": "u1",
            "org_id": ORG,
            "scopes": ["read", "query", "execute", "write", "admin"],
            "execution_identity": "chat:run-1",
        }
    )


async def _controlled_dispatch(request: Request, call_next: RequestResponseEndpoint) -> Response:
    request.state.auth = dict(_CURRENT_AUTH)
    return await call_next(request)


def _run(id: str, user: str, conv: str, cost: float, ts: float, usage: dict | None, org: str = ORG) -> GatewayChatRun:
    return GatewayChatRun(
        id=id,
        org_id=org,
        user_id=user,
        conversation_id=conv,
        project_id="p1",
        user_message_id=f"m-{id}",
        status="completed",
        cost_usd=cost,
        usage_json=usage,
        created_at=_dt(ts),
        terminal_at=_dt(ts + 5),
    )


def _audit(id: str, user: str | None, ts: float, event: str, **kw: Any) -> GatewayAuditLog:
    return GatewayAuditLog(id=id, org_id=kw.pop("org", ORG), user_id=user, timestamp=ts, event_type=event, **kw)


def _conv(id: str, user: str, title: str) -> GatewayChatConversation:
    return GatewayChatConversation(id=id, org_id=ORG, user_id=user, title=title, created_at=NOW, updated_at=NOW)


async def _seed(session: AsyncSession) -> None:
    usage1 = {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read_input_tokens": 10,
        "cache_creation_input_tokens": 5,
    }
    usage2 = {"input_tokens": 200, "output_tokens": 20, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    session.add_all(
        [
            _conv("c1", "u1", "Alpha"),
            _conv("c2", "u2", "Beta"),
            _conv("c3", "u1", "Old"),
            _run("r1", "u1", "c1", 1.0, RECENT, usage1),
            _run("r2", "u1", "c1", 0.5, TWO_DAYS_AGO, None),
            _run("r3", "u2", "c2", 3.0, RECENT, usage2),
            _run("r-old", "u1", "c3", 99.0, ANCIENT, usage1),
            _run("r-other-org", "u1", "cX", 42.0, RECENT, usage1, org="org-2"),
            # Warehouse statements (connector-level rows).
            _audit("a1", "u1", RECENT, "sql", connection_name="wh", rows_returned=10, blocked=False),
            _audit("a2", "u2", TWO_DAYS_AGO, "sql", connection_name="wh2", rows_returned=5, blocked=False),
            # A refused query_database call only leaves the mcp_tool row.
            _audit(
                "a3", "u1", RECENT, "mcp_tool", agent_id="query_database", connection_name="wh",
                blocked=True, block_reason="DDL not allowed",
            ),
            # Not queries: a successful tool call, an admin event, an old row, another org.
            _audit("a4", "u1", RECENT, "mcp_tool", agent_id="list_tables", blocked=False),
            _audit("a5", "u1", RECENT, "api_key_create", blocked=False),
            _audit("a6", "u1", ANCIENT, "sql", connection_name="wh", rows_returned=999, blocked=False),
            _audit("a7", "u1", RECENT, "sql", connection_name="wh", rows_returned=7, blocked=False, org="org-2"),
        ]
    )
    await session.commit()


async def _init_db(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        await _seed(session)
    await engine.dispose()


async def _fake_get_store():
    store = AsyncMock()
    store.org_id = ORG
    store.user_id = _CURRENT_AUTH.get("user_id")
    store.session = _DB["factory"]()
    store.append_audit = AsyncMock(side_effect=lambda entry: _AUDITED.append(entry))
    try:
        yield store
    finally:
        await store.session.close()


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("gateway.auth.user.is_cloud_mode", lambda: True)
    monkeypatch.setattr("gateway.api.usage.is_cloud_mode", lambda: True)
    url = f"sqlite+aiosqlite:///{(tmp_path / 'usage.db').as_posix()}"
    asyncio.run(_init_db(url))
    engine = create_async_engine(url, poolclass=NullPool)
    _DB["factory"] = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    _AUDITED.clear()
    with isolated_app(monkeypatch) as app:
        app.dependency_overrides[get_store] = _fake_get_store
        if app.middleware_stack is None:
            app.middleware_stack = app.build_middleware_stack()
        middlewares = _auth_middlewares(app)
        assert middlewares, "APIKeyAuthMiddleware not on the stack"
        for middleware in middlewares:
            middleware.dispatch_func = _controlled_dispatch
        try:
            yield TestClient(app, raise_server_exceptions=False)
        finally:
            for middleware in middlewares:
                middleware.dispatch_func = middleware.dispatch
    asyncio.run(engine.dispose())
    _DB.clear()


def _by_user(body: dict) -> dict[str, dict]:
    return {m["user_id"]: m for m in body["members"]}


# ── /api/usage/org ───────────────────────────────────────────────────────────


class TestOrgUsage:
    def test_member_key_is_refused(self, client):
        _as_api_key("read", "write")
        response = client.get("/api/usage/org")
        assert response.status_code == 403
        assert _AUDITED == []

    def test_sandbox_token_is_refused(self, client):
        _as_sandbox()
        assert client.get("/api/usage/org").status_code == 403

    def test_admin_gets_members_sorted_by_cost(self, client):
        _as_api_key("read", "write", "admin")
        response = client.get("/api/usage/org")
        assert response.status_code == 200, response.text
        body = response.json()
        assert [m["user_id"] for m in body["members"]] == ["u2", "u1"]

        u1 = _by_user(body)["u1"]
        assert u1["chat_runs"] == 2
        assert u1["conversations"] == 1
        assert u1["cost_usd"] == pytest.approx(1.5)
        assert (u1["input_tokens"], u1["output_tokens"]) == (100, 50)
        assert (u1["cache_read_tokens"], u1["cache_creation_tokens"]) == (10, 5)
        assert (u1["queries"], u1["blocked_queries"], u1["rows_returned"]) == (2, 1, 10)
        assert u1["eval_runs"] is None
        assert u1["last_active_at"] == pytest.approx(RECENT, abs=1)

        u2 = _by_user(body)["u2"]
        assert u2["chat_runs"] == 1
        assert u2["input_tokens"] == 200
        assert (u2["queries"], u2["blocked_queries"], u2["rows_returned"]) == (1, 0, 5)

    def test_totals_cover_window_only(self, client):
        _as_api_key("admin")
        totals = client.get("/api/usage/org").json()["totals"]
        assert totals["chat_runs"] == 3
        assert totals["conversations"] == 2
        assert totals["cost_usd"] == pytest.approx(4.5)
        assert totals["input_tokens"] == 300
        assert (totals["queries"], totals["blocked_queries"], totals["rows_returned"]) == (3, 1, 15)

    def test_daily_is_zero_filled_for_every_day(self, client):
        _as_api_key("admin")
        body = client.get("/api/usage/org?days=30").json()
        daily = body["daily"]
        assert body["window"]["days"] == 30
        assert len(daily) == 30
        assert daily[-1]["date"] == _day(NOW)
        assert [p["date"] for p in daily] == sorted(p["date"] for p in daily)
        by_date = {p["date"]: p for p in daily}
        assert by_date[_day(RECENT)] == {"date": _day(RECENT), "chat_runs": 2, "cost_usd": 4.0, "queries": 2}
        assert by_date[_day(TWO_DAYS_AGO)] == {"date": _day(TWO_DAYS_AGO), "chat_runs": 1, "cost_usd": 0.5, "queries": 1}
        assert sum(p["chat_runs"] for p in daily) == 3
        assert sum(p["queries"] for p in daily) == 3
        zeros = [p for p in daily if p["date"] not in (_day(RECENT), _day(TWO_DAYS_AGO))]
        assert all(p["chat_runs"] == 0 and p["cost_usd"] == 0 and p["queries"] == 0 for p in zeros)

    def test_window_is_clamped(self, client):
        _as_api_key("admin")
        big = client.get("/api/usage/org?days=500").json()
        assert big["window"]["days"] == 90
        assert len(big["daily"]) == 90
        assert big["window"]["from_ts"] < big["window"]["to_ts"]
        small = client.get("/api/usage/org?days=0").json()
        assert small["window"]["days"] == 1
        assert len(small["daily"]) == 1
        assert small["totals"]["chat_runs"] == 2  # only today's runs

    def test_admin_access_is_audited(self, client):
        _as_api_key("admin")
        assert client.get("/api/usage/org?days=7").status_code == 200
        assert [e.event_type for e in _AUDITED] == ["usage_org_view"]
        assert _AUDITED[0].metadata == {"days": 7, "members": 2}


# ── /api/usage/me ────────────────────────────────────────────────────────────


class TestMyUsage:
    def test_requires_read_scope(self, client):
        _as_api_key("write")
        assert client.get("/api/usage/me").status_code == 403

    def test_key_without_user_is_refused_in_cloud_mode(self, client):
        _as_api_key("read", user_id=None)
        response = client.get("/api/usage/me")
        assert response.status_code == 403
        assert "identity" in response.json()["detail"].lower()

    def test_returns_only_the_callers_data(self, client):
        _as_api_key("read")
        response = client.get("/api/usage/me")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["user_id"] == "u1"
        totals = body["totals"]
        assert totals["chat_runs"] == 2
        assert totals["conversations"] == 1
        assert totals["cost_usd"] == pytest.approx(1.5)
        assert totals["input_tokens"] == 100
        assert (totals["queries"], totals["blocked_queries"], totals["rows_returned"]) == (2, 1, 10)
        assert len(body["daily"]) == 30
        assert sum(p["chat_runs"] for p in body["daily"]) == 2
        assert body["conversations"] == [
            {
                "conversation_id": "c1",
                "title": "Alpha",
                "chat_runs": 2,
                "cost_usd": 1.5,
                "last_activity_at": pytest.approx(RECENT, abs=1),
            }
        ]
        assert body["connections"] == [
            {"connection_name": "wh", "queries": 2, "rows_returned": 10, "blocked_queries": 1}
        ]
        assert _AUDITED == []

    def test_other_user_sees_their_own_slice(self, client):
        _as_api_key("read", user_id="u2")
        body = client.get("/api/usage/me?days=3").json()
        assert body["user_id"] == "u2"
        assert body["totals"]["chat_runs"] == 1
        assert body["totals"]["cost_usd"] == pytest.approx(3.0)
        assert body["totals"]["queries"] == 1
        assert [c["conversation_id"] for c in body["conversations"]] == ["c2"]
        assert [c["title"] for c in body["conversations"]] == ["Beta"]
        assert body["connections"] == [
            {"connection_name": "wh2", "queries": 1, "rows_returned": 5, "blocked_queries": 0}
        ]
        assert body["window"]["days"] == 3
        assert len(body["daily"]) == 3
