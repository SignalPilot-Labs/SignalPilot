"""Verify the access restrictions stored in an evaluation credential.

The evaluated agent controls its container and can read the MCP key. The stored
credential restricts the agent to one task and one connection until expiration.
Request changes cannot expand this access.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request
from starlette.responses import JSONResponse

from gateway.db.models import GatewayBase
from gateway.store import Store

ORG = "org-eval"
OTHER_ORG = "org-other"
PINNED = "warehouse-under-test"


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(session_factory) -> AsyncSession:
    async with session_factory() as session:
        yield session


@pytest.fixture
def store(db_session) -> Store:
    return Store(db_session, org_id=ORG, user_id="user-1")


async def _mint(store: Store, **binding):
    return await store.create_api_key(
        "eval-run-1-task-a",
        ["read", "write"],
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        eval_binding={
            "run_id": "run-20260101-000000-aaaaaa",
            "task_id": "task-a",
            "connection": PINNED,
            "doc_ids": ["doc-1"],
            **binding,
        },
    )


class TestBindingSurvivesValidation:
    async def test_validation_returns_the_binding(self, store: Store) -> None:
        """Whatever the request looks like, validating the key yields the pin."""
        _, raw = await _mint(store)
        record = await store.validate_stored_api_key(raw)
        assert record is not None
        assert record.eval_connection == PINNED
        assert record.eval_run_id == "run-20260101-000000-aaaaaa"
        assert record.eval_task_id == "task-a"
        assert record.eval_doc_ids == ["doc-1"]

    async def test_a_request_with_no_headers_is_still_pinned(self, store: Store) -> None:
        """Verify that key-only authorization retains the connection restriction."""
        _, raw = await _mint(store)
        record = await store.validate_stored_api_key(raw)
        assert record.eval_connection == PINNED

    async def test_an_ordinary_key_is_not_pinned(self, store: Store) -> None:
        _, raw = await store.create_api_key("workspace key", ["read"])
        record = await store.validate_stored_api_key(raw)
        assert record is not None
        assert record.eval_connection is None
        assert record.eval_run_id is None

    async def test_eval_key_without_a_pin_is_refused(self, store: Store) -> None:
        with pytest.raises(ValueError, match="non-empty connection pin"):
            await store.create_api_key(
                "broken-eval-key",
                ["read", "query"],
                eval_binding={"run_id": "run-x", "connection": ""},
            )

    async def test_store_credential_lookups_cannot_escape_the_pin(self, db_session) -> None:
        pinned = Store(db_session, org_id=ORG, user_id="eval", eval_connection=PINNED)
        assert await pinned.get_connection("other-warehouse") is None
        assert await pinned.get_connection_string("other-warehouse") is None
        assert await pinned.get_credential_extras("other-warehouse") == {}

    async def test_store_audit_reads_are_forced_to_the_pin(self, db_session) -> None:
        pinned = Store(db_session, org_id=ORG, user_id="eval", eval_connection=PINNED)
        with patch(
            "gateway.store.store.audit_log.read_audit",
            new=AsyncMock(return_value=[]),
        ) as read:
            await pinned.read_audit(connection_name=None)
        assert read.await_args.kwargs["connection_name"] == PINNED

    async def test_rest_middleware_carries_the_stored_pin(
        self, store: Store, session_factory, monkeypatch
    ) -> None:
        from gateway.http.middleware.auth import APIKeyAuthMiddleware

        _, raw = await _mint(store)
        monkeypatch.setattr("gateway.db.engine.get_session_factory", lambda: session_factory)
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/connections",
                "headers": [(b"x-api-key", raw.encode())],
                "query_string": b"",
                "scheme": "http",
                "server": ("test", 80),
                "client": ("127.0.0.1", 1),
            }
        )

        async def downstream(req):
            return JSONResponse(req.state.auth)

        response = await APIKeyAuthMiddleware(lambda *_: None).dispatch(request, downstream)
        assert response.status_code == 200
        assert request.state.auth["eval_connection"] == PINNED
        assert request.state.auth["eval_run_id"] == "run-20260101-000000-aaaaaa"

    async def test_rest_store_receives_the_pin(self, db_session) -> None:
        from gateway.api.deps import get_store

        request = SimpleNamespace(state=SimpleNamespace(auth={"eval_connection": PINNED}))
        scoped = await get_store(request, ORG, "eval", db_session)
        assert scoped.eval_connection == PINNED

    async def test_local_no_key_cannot_bypass_an_active_eval_key(
        self, store: Store, session_factory, monkeypatch
    ) -> None:
        from gateway.http.middleware.auth import APIKeyAuthMiddleware

        await _mint(store)
        monkeypatch.setattr("gateway.db.engine.get_session_factory", lambda: session_factory)
        monkeypatch.setattr("gateway.runtime.mode.is_local_mode", lambda: True)
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/connections",
                "headers": [],
                "query_string": b"",
                "scheme": "http",
                "server": ("test", 80),
                "client": ("127.0.0.1", 1),
            }
        )

        async def downstream(_request):
            pytest.fail("active eval credentials must disable local no-key access")

        response = await APIKeyAuthMiddleware(lambda *_: None).dispatch(request, downstream)
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "headers",
        [
            [(b"authorization", b"Bearer x")],
            [(b"cookie", b"__session=fake-local-jwt")],
        ],
    )
    async def test_local_passthrough_auth_cannot_bypass_an_active_eval_key(
        self, headers, store: Store, session_factory, monkeypatch
    ) -> None:
        from gateway.http.middleware.auth import APIKeyAuthMiddleware

        await _mint(store)
        monkeypatch.setattr("gateway.db.engine.get_session_factory", lambda: session_factory)
        monkeypatch.setattr("gateway.runtime.mode.is_local_mode", lambda: True)
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/connections",
                "headers": headers,
                "query_string": b"",
                "scheme": "http",
                "server": ("test", 80),
                "client": ("127.0.0.1", 1),
            }
        )

        async def downstream(_request):
            pytest.fail("local JWT/cookie passthrough bypassed the active eval gate")

        response = await APIKeyAuthMiddleware(lambda *_: None).dispatch(request, downstream)
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "path",
        [
            "/api/settings",
            "/api/evals/runs",
            f"/api/connections/{PINNED}-decoy/schema",
        ],
    )
    async def test_eval_key_cannot_call_unrelated_rest_routes(
        self, path, store: Store, session_factory, monkeypatch
    ) -> None:
        from gateway.http.middleware.auth import APIKeyAuthMiddleware

        _, raw = await _mint(store)
        monkeypatch.setattr("gateway.db.engine.get_session_factory", lambda: session_factory)
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": path,
                "headers": [(b"x-api-key", raw.encode())],
                "query_string": b"",
                "scheme": "http",
                "server": ("test", 80),
                "client": ("127.0.0.1", 1),
            }
        )

        async def downstream(_request):
            pytest.fail("eval key reached an unrelated REST route")

        response = await APIKeyAuthMiddleware(lambda *_: None).dispatch(request, downstream)
        assert response.status_code == 403


class TestExpiryAndRevocation:
    async def test_an_expired_eval_key_stops_validating(self, store: Store) -> None:
        """Verify that credential expiration limits access after a gateway failure."""
        _, raw = await store.create_api_key(
            "eval-old",
            ["read"],
            expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            eval_binding={"run_id": "run-x", "connection": PINNED},
        )
        assert await store.validate_stored_api_key(raw) is None

    async def test_run_scoped_revocation_removes_every_task_key(
        self, session_factory, monkeypatch
    ) -> None:
        """Recovery revokes by run id, so per-task keys go too."""
        from gateway.evals import runner

        async with session_factory() as session:
            store = Store(session, org_id=ORG, user_id="u")
            _, raw_a = await _mint(store, task_id="task-a")
            _, raw_b = await _mint(store, task_id="task-b")
            _, raw_other = await store.create_api_key("unrelated", ["read"])
            await session.commit()

        monkeypatch.setattr(runner, "get_session_factory", lambda: session_factory)
        await runner.revoke_run_keys(ORG, "run-20260101-000000-aaaaaa")

        async with session_factory() as session:
            store = Store(session, org_id=ORG, user_id="u")
            assert await store.validate_stored_api_key(raw_a) is None
            assert await store.validate_stored_api_key(raw_b) is None
            # An unrelated workspace key is untouched.
            assert await store.validate_stored_api_key(raw_other) is not None

    async def test_revocation_does_not_cross_orgs(self, session_factory, monkeypatch) -> None:
        from gateway.evals import runner

        async with session_factory() as session:
            other = Store(session, org_id=OTHER_ORG, user_id="u")
            _, raw_other = await other.create_api_key(
                "eval-theirs",
                ["read"],
                eval_binding={"run_id": "run-20260101-000000-aaaaaa", "connection": "theirs"},
            )
            await session.commit()

        monkeypatch.setattr(runner, "get_session_factory", lambda: session_factory)
        # Same run id, different org: must not touch the other tenant's key.
        await runner.revoke_run_keys(ORG, "run-20260101-000000-aaaaaa")

        async with session_factory() as session:
            other = Store(session, org_id=OTHER_ORG, user_id="u")
            assert await other.validate_stored_api_key(raw_other) is not None
