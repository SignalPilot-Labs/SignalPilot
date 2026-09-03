"""Order-independent app harness for the Connectors API tests.

``gateway.main.app`` is a process-wide singleton, so state left behind by
earlier test modules reaches these tests:

- ``app.dependency_overrides`` entries that were never popped;
- a fake ``dispatch_func`` installed on the live ``APIKeyAuthMiddleware``
  instance (module-scoped clients in the auth/scope suites do this) which
  stamps every later request with a stale ``api_key`` identity;
- the cached ``gateway.db.engine`` engine/session factory and the local dev
  key file under whatever ``SP_DATA_DIR`` was current at import time.

``isolated_app`` snapshots and restores the overrides, puts the real auth
dispatcher back, pins the local dev key to a known value, and points the
global session factory at the test database for the duration of one test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi import Depends, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api.mcp import connectors as connectors_api
from gateway.db.models import GatewayBase
from gateway.mcp_connectors.probe import ProbeResult
from gateway.mcp_connectors.tools import tool_info_from_upstream

BASE = "/api/mcp"
TEST_LOCAL_API_KEY = "sp_local_connectors_test_key"


def _auth_middlewares(app: Any) -> list[Any]:
    """Every APIKeyAuthMiddleware instance on the built middleware stack (none before first start)."""
    from gateway.http import APIKeyAuthMiddleware

    found: list[Any] = []
    current = app.middleware_stack
    while current is not None:
        if isinstance(current, APIKeyAuthMiddleware):
            found.append(current)
        current = getattr(current, "app", None)
    return found


async def _no_eval_credentials() -> bool:
    return False


@contextmanager
def isolated_app(monkeypatch: pytest.MonkeyPatch, *, session_factory: Any = None) -> Iterator[Any]:
    """Yield ``gateway.main.app`` with process-wide state neutralised for one test.

    Overrides added inside the block are dropped on exit and the snapshot taken
    on entry is restored, so this is safe to nest under fixtures of other
    modules. The auth middleware is healed (real ``dispatch`` reinstated) and
    left healed: that is the correct state for every module that follows.
    """
    import gateway.db.engine as db_engine
    import gateway.store as store_pkg
    from gateway.main import app

    saved_overrides = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    for middleware in _auth_middlewares(app):
        middleware.dispatch_func = middleware.dispatch
    monkeypatch.setattr("gateway.http.middleware.auth._eval_credentials_active", _no_eval_credentials)
    monkeypatch.setattr(store_pkg, "get_local_api_key", lambda: TEST_LOCAL_API_KEY)
    if session_factory is not None:
        monkeypatch.setattr(db_engine, "get_session_factory", lambda: session_factory)
    try:
        yield app
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved_overrides)


# ── API harness shared by the connector test modules ─────────────────────────


def tool_stub(name: str, **annotations: Any) -> SimpleNamespace:
    """An SDK-shaped Tool with the given camelCase annotations."""
    return SimpleNamespace(
        name=name,
        title=None,
        description=f"{name} from provider",
        inputSchema={"type": "object", "properties": {}},
        annotations=SimpleNamespace(model_dump=lambda exclude_none=True: annotations, title=None),
    )


async def probe_ok(url: str, **_kwargs: Any) -> ProbeResult:
    """A reachable Streamable-HTTP server with three tools (one read-only, one destructive, one plain)."""
    return ProbeResult(
        transport="http",
        auth="key" if _kwargs.get("headers") else "none",
        server_name="Vendor Docs",
        protocol_version="2025-11-25",
        tools=[
            tool_info_from_upstream(tool_stub("search", readOnlyHint=True)),
            tool_info_from_upstream(tool_stub("delete_page", destructiveHint=True)),
            tool_info_from_upstream(tool_stub("create_page")),
        ],
    )


class Harness:
    def __init__(self, client: TestClient, state: dict[str, str], session_factory: Any) -> None:
        self.client = client
        self.state = state
        self.session_factory = session_factory

    def as_user(self, user_id: str, role: str = "basic_member") -> Harness:
        self.state["user"] = user_id
        self.state["role"] = role
        return self


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Connectors API on a fresh in-memory database, authenticated as the local dev key.

    Identity and org role come from ``harness.as_user(...)``; the probe and the
    SSRF DNS step are stubbed (example hosts have no DNS here).
    """
    monkeypatch.setenv("SP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("SP_ENCRYPTION_KEY_OLD", raising=False)
    monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
    monkeypatch.delenv("SP_FEATURE_CHAT_MCP_CONNECTORS", raising=False)
    import gateway.store.crypto as crypto

    monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)
    monkeypatch.setattr(connectors_api, "probe_url", probe_ok)

    async def _no_dns(url: str) -> str:
        from gateway.mcp_connectors.ssrf import validate_url_syntax

        return validate_url_syntax(url)

    # The create/patch routes re-run the SSRF guard; example hosts have no DNS here.
    monkeypatch.setattr(connectors_api, "validate_remote_url", _no_dns)

    async def _make():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(GatewayBase.metadata.create_all)
        return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    engine, Session = asyncio.run(_make())
    from gateway.api.deps import get_store
    from gateway.auth.user import resolve_org_role
    from gateway.db.engine import get_db
    from gateway.store import Store

    state = {"user": "admin-a", "role": "admin"}

    async def _db():
        async with Session() as session:
            yield session

    async def _store(request: Request, db: AsyncSession = Depends(get_db)):
        auth = getattr(request.state, "auth", None) or {}
        if auth.get("auth_method") == "notebook_session":
            return Store(db, org_id=auth["org_id"], user_id=auth["user_id"])
        return Store(db, org_id="local", user_id=state["user"])

    with isolated_app(monkeypatch, session_factory=Session) as app:
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_store] = _store
        app.dependency_overrides[resolve_org_role] = lambda: state["role"]
        client = TestClient(app, headers={"Authorization": f"Bearer {TEST_LOCAL_API_KEY}"})
        try:
            yield Harness(client, state, Session)
        finally:
            asyncio.run(engine.dispose())


def create_connector(h: Harness, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"scope": "personal", "name": "Vendor Docs", "url": "https://mcp.vendor.example/mcp"}
    body.update(overrides)
    response = h.client.post(f"{BASE}/connectors", json=body)
    assert response.status_code == 201, response.text
    return response.json()
