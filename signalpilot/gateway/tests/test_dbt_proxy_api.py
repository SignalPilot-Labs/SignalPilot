"""FastAPI TestClient tests for the dbt-proxy run-token API.

Uses a minimal test app with only the dbt_proxy router and mocked app.state.
No lifespan/DB is needed — token operations are in-memory.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.dbt_proxy.api import get_store
from gateway.dbt_proxy.api import router as dbt_proxy_router
from gateway.dbt_proxy.config import DbtProxyConfig
from gateway.dbt_proxy.tokens import RunTokenStore
from gateway.models import DBType
from gateway.security.scope_guard import require_scopes


class _FakeStubConn:
    """Minimal connection stub with a postgres db_type for test apps."""

    db_type: DBType = DBType.postgres


class _FakeStoreWithPostgres:
    """Fake store stub that always returns a postgres connection."""

    async def get_connection(self, name: str) -> _FakeStubConn:
        return _FakeStubConn()


def _make_test_app(secret: str = "test-secret", enabled: bool = True) -> FastAPI:
    """Build a minimal FastAPI app with the dbt_proxy router and in-memory state."""
    app = FastAPI()
    app.include_router(dbt_proxy_router)

    config = DbtProxyConfig(
        sp_dbt_proxy_enabled=enabled,
        sp_gateway_run_token_secret=secret,
        sp_dbt_proxy_port=15432,
    )
    token_store = RunTokenStore(secret)
    app.state.dbt_proxy_config = config
    app.state.dbt_proxy_token_store = token_store

    # Inject local-mode auth state so RequireScope passes
    from fastapi import Request
    from starlette.middleware.base import BaseHTTPMiddleware

    class _LocalAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request.state.auth = {"auth_method": "local_key"}
            # Set minimal jwt_claims for resolve_user_id
            request.state._jwt_claims = {"sub": "test-user", "org_id": "test-org"}
            return await call_next(request)

    app.add_middleware(_LocalAuthMiddleware)

    # Override get_store to avoid needing a real DB connection
    fake_store = _FakeStoreWithPostgres()
    app.dependency_overrides[get_store] = lambda: fake_store

    return app


class TestDbtProxyApi:
    def test_mint_returns_201_with_token_and_host_port(self) -> None:
        run_id = uuid.uuid4()
        app = _make_test_app()
        with TestClient(app) as client:
            resp = client.post(
                "/api/dbt-proxy/run-tokens",
                json={
                    "run_id": str(run_id),
                    "connector_name": "my_conn",
                    "ttl_seconds": 300,
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "token" in data
        assert len(data["token"]) == 64  # SHA-256 hex
        assert data["host_port"] == 15432
        assert "expires_at" in data

    def test_remint_same_run_id_returns_409(self) -> None:
        run_id = uuid.uuid4()
        app = _make_test_app()
        with TestClient(app) as client:
            r1 = client.post(
                "/api/dbt-proxy/run-tokens",
                json={"run_id": str(run_id), "connector_name": "conn", "ttl_seconds": 300},
            )
            assert r1.status_code == 201
            r2 = client.post(
                "/api/dbt-proxy/run-tokens",
                json={"run_id": str(run_id), "connector_name": "conn", "ttl_seconds": 300},
            )
        assert r2.status_code == 409

    def test_delete_then_get_returns_404(self) -> None:
        run_id = uuid.uuid4()
        app = _make_test_app()
        with TestClient(app) as client:
            client.post(
                "/api/dbt-proxy/run-tokens",
                json={"run_id": str(run_id), "connector_name": "conn", "ttl_seconds": 300},
            )
            del_resp = client.delete(f"/api/dbt-proxy/run-tokens/{run_id}")
            assert del_resp.status_code == 204

            get_resp = client.get(f"/api/dbt-proxy/run-tokens/{run_id}")
        assert get_resp.status_code == 404

    def test_without_dbt_proxy_scope_returns_403(self) -> None:
        """API-key auth without dbt_proxy scope → 403 from RequireScope."""
        from unittest.mock import MagicMock
        from fastapi import HTTPException

        request = MagicMock()
        request.state.auth = {"auth_method": "api_key", "scopes": ["read", "query"]}
        with pytest.raises(HTTPException) as exc_info:
            require_scopes(request, "dbt_proxy")
        assert exc_info.value.status_code == 403

    def test_mint_does_not_log_org_id_or_connector_name(self) -> None:
        """Mint log line must not include org_id or connector_name."""
        import logging
        from unittest.mock import patch, MagicMock

        run_id = uuid.uuid4()
        app = _make_test_app()
        log_calls: list = []

        original_info = logging.Logger.info

        def capture_info(self, msg, *args, **kwargs):
            log_calls.append((msg,) + args)
            return original_info(self, msg, *args, **kwargs)

        with patch.object(logging.Logger, "info", capture_info):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/dbt-proxy/run-tokens",
                    json={
                        "run_id": str(run_id),
                        "connector_name": "my_conn",
                        "ttl_seconds": 300,
                    },
                )
        assert resp.status_code == 201

        for call_args in log_calls:
            full_msg = " ".join(str(a) for a in call_args)
            assert "test-org" not in full_msg
            assert "my_conn" not in full_msg

    def test_mint_rejects_bad_connector_name(self) -> None:
        """connector_name with invalid charset returns 422."""
        run_id = uuid.uuid4()
        app = _make_test_app()
        with TestClient(app) as client:
            resp = client.post(
                "/api/dbt-proxy/run-tokens",
                json={
                    "run_id": str(run_id),
                    "connector_name": "evil; drop",
                    "ttl_seconds": 300,
                },
            )
        assert resp.status_code == 422

    def test_mint_caps_ttl_in_cloud_mode(self) -> None:
        """In cloud mode, TTL is capped to 3600 regardless of request value."""
        from datetime import UTC, datetime

        run_id = uuid.uuid4()
        app = _make_test_app()

        # Patch is_cloud_mode directly so we avoid JWT auth flow triggering
        from unittest.mock import patch as _patch
        with _patch("gateway.dbt_proxy.api.is_cloud_mode", return_value=True):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/dbt-proxy/run-tokens",
                    json={
                        "run_id": str(run_id),
                        "connector_name": "my_conn",
                        "ttl_seconds": 86400,
                    },
                )
        assert resp.status_code == 201
        data = resp.json()
        expires_at = datetime.fromisoformat(data["expires_at"])
        max_allowed = datetime.now(tz=UTC).timestamp() + 3600
        assert expires_at.timestamp() <= max_allowed + 5  # 5s tolerance
