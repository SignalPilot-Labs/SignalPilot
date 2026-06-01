"""Org-scoping tests for dbt-proxy run-token routes.

Covers M-2 (IDOR on revoke/get) and M-3 (connector ownership at mint time).
Uses dependency overrides to avoid needing a real DB.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from gateway.dbt_proxy.api import get_store
from gateway.dbt_proxy.api import router as dbt_proxy_router
from gateway.dbt_proxy.config import DbtProxyConfig
from gateway.dbt_proxy.tokens import RunTokenStore
from gateway.models import DBType

# ─── FakeStore ───────────────────────────────────────────────────────────────


@dataclass
class _StubConnection:
    db_type: DBType


class FakeStore:
    """Minimal store stub that returns a configurable connection for get_connection."""

    def __init__(self, connection: _StubConnection | None) -> None:
        self._connection = connection

    async def get_connection(self, name: str) -> _StubConnection | None:
        return self._connection


# ─── Test app factory ─────────────────────────────────────────────────────────

_DEFAULT_SECRET = "test-secret-org-scope"


def _make_test_app_with_org(
    org_id: str,
    fake_store: FakeStore | None = None,
    secret: str = _DEFAULT_SECRET,
) -> FastAPI:
    """Build a minimal FastAPI app with configurable org_id and store override."""
    app = FastAPI()
    app.include_router(dbt_proxy_router)

    config = DbtProxyConfig(
        sp_dbt_proxy_enabled=True,
        sp_gateway_run_token_secret=secret,
        sp_dbt_proxy_port=15432,
    )
    token_store = RunTokenStore(secret)
    app.state.dbt_proxy_config = config
    app.state.dbt_proxy_token_store = token_store

    class _LocalAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Any:
            request.state.auth = {"auth_method": "local_key"}
            request.state._jwt_claims = {"sub": "test-user", "org_id": org_id}
            return await call_next(request)

    app.add_middleware(_LocalAuthMiddleware)

    if fake_store is not None:
        app.dependency_overrides[get_store] = lambda: fake_store

    return app


def _postgres_store() -> FakeStore:
    return FakeStore(_StubConnection(db_type=DBType.postgres))


def _mysql_store() -> FakeStore:
    return FakeStore(_StubConnection(db_type=DBType.mysql))


def _none_store() -> FakeStore:
    return FakeStore(None)


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestDbtProxyOrgScoping:
    def test_mint_with_foreign_org_connector_returns_404(self) -> None:
        """FakeStore returns None (connector exists in org B, not visible to org A)."""
        app = _make_test_app_with_org("org-a", fake_store=_none_store())
        with TestClient(app) as client:
            resp = client.post(
                "/api/dbt-proxy/run-tokens",
                json={"run_id": str(uuid.uuid4()), "connector_name": "conn_b", "ttl_seconds": 300},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "connector_not_found"

    def test_mint_with_nonexistent_connector_returns_404(self) -> None:
        """FakeStore returns None for any connector name."""
        app = _make_test_app_with_org("org-a", fake_store=_none_store())
        with TestClient(app) as client:
            resp = client.post(
                "/api/dbt-proxy/run-tokens",
                json={"run_id": str(uuid.uuid4()), "connector_name": "does_not_exist", "ttl_seconds": 300},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "connector_not_found"

    def test_mint_with_non_postgres_connector_returns_404(self) -> None:
        """Non-postgres connector returns same 404 as missing — no type leak."""
        app = _make_test_app_with_org("org-a", fake_store=_mysql_store())
        with TestClient(app) as client:
            resp = client.post(
                "/api/dbt-proxy/run-tokens",
                json={"run_id": str(uuid.uuid4()), "connector_name": "mysql_conn", "ttl_seconds": 300},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "connector_not_found"

    def test_mint_with_postgres_connector_succeeds(self) -> None:
        """Postgres connector in caller's org → 201 with token."""
        app = _make_test_app_with_org("org-a", fake_store=_postgres_store())
        with TestClient(app) as client:
            resp = client.post(
                "/api/dbt-proxy/run-tokens",
                json={"run_id": str(uuid.uuid4()), "connector_name": "pg_conn", "ttl_seconds": 300},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "token" in data
        assert len(data["token"]) == 64

    def test_revoke_foreign_org_run_id_returns_204_and_does_not_revoke(self) -> None:
        """Critical: revoke by a different org returns 204 but does NOT remove the token."""
        secret = _DEFAULT_SECRET
        # Mint a token as "other-org" directly into the store
        app = _make_test_app_with_org("test-org", fake_store=_postgres_store(), secret=secret)
        token_store: RunTokenStore = app.state.dbt_proxy_token_store

        run_id = uuid.uuid4()

        asyncio.run(
            token_store.mint(
                run_id=run_id,
                org_id="other-org",
                user_id="other-user",
                connector_name="conn",
                ttl_seconds=300,
            )
        )

        with TestClient(app) as client:
            del_resp = client.delete(f"/api/dbt-proxy/run-tokens/{run_id}")

        assert del_resp.status_code == 204

        # Token must still be present — the revoke must NOT have executed
        claims = asyncio.run(token_store.get(run_id))
        assert claims is not None
        assert claims.org_id == "other-org"

    def test_get_foreign_org_run_id_returns_404(self) -> None:
        """GET for a run_id that belongs to another org → 404 with same error_code as genuine miss."""
        secret = _DEFAULT_SECRET
        app = _make_test_app_with_org("test-org", fake_store=_postgres_store(), secret=secret)
        token_store: RunTokenStore = app.state.dbt_proxy_token_store

        run_id = uuid.uuid4()

        asyncio.run(
            token_store.mint(
                run_id=run_id,
                org_id="other-org",
                user_id="other-user",
                connector_name="conn",
                ttl_seconds=300,
            )
        )

        with TestClient(app) as client:
            get_resp = client.get(f"/api/dbt-proxy/run-tokens/{run_id}")

        assert get_resp.status_code == 404
        detail = get_resp.json()["detail"]
        assert detail["error_code"] == "run_token_not_found"
        assert f"run_id={run_id}" in detail["message"]

    def test_revoke_own_org_token_succeeds(self) -> None:
        """Mint via API as test-org, DELETE → 204, then token is gone."""
        app = _make_test_app_with_org("test-org", fake_store=_postgres_store())
        token_store: RunTokenStore = app.state.dbt_proxy_token_store
        run_id = uuid.uuid4()

        with TestClient(app) as client:
            mint_resp = client.post(
                "/api/dbt-proxy/run-tokens",
                json={"run_id": str(run_id), "connector_name": "pg_conn", "ttl_seconds": 300},
            )
            assert mint_resp.status_code == 201

            del_resp = client.delete(f"/api/dbt-proxy/run-tokens/{run_id}")

        assert del_resp.status_code == 204

        claims = asyncio.run(token_store.get(run_id))
        assert claims is None

    def test_get_own_org_token_returns_info(self) -> None:
        """Mint via API as test-org, GET → 200 with expected fields."""
        app = _make_test_app_with_org("test-org", fake_store=_postgres_store())
        run_id = uuid.uuid4()

        with TestClient(app) as client:
            mint_resp = client.post(
                "/api/dbt-proxy/run-tokens",
                json={"run_id": str(run_id), "connector_name": "pg_conn", "ttl_seconds": 300},
            )
            assert mint_resp.status_code == 201

            get_resp = client.get(f"/api/dbt-proxy/run-tokens/{run_id}")

        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["run_id"] == str(run_id)
        assert "expires_at" in data
        assert data["host_port"] == 15432
        assert data["sessions_open"] == 0
