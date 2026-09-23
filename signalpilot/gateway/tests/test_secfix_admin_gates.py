"""Security fixes 2026-09-15: admin gates on PII config, org secrets, chat state routes.

SP-03: PII configuration writes require an org admin (like connection CRUD).
SP-06: PUT /api/org/secrets requires admin scope + org admin; the runtime GET
       path used by the sandbox keeps working.
SP-14: state-changing chat routes refuse the sandbox run token.

Auth is injected by replacing the APIKeyAuthMiddleware instance's dispatch_func
so each test sets request.state.auth directly (exactly what the real middleware
stores for an API key or a notebook-session token); get_store is a fake. The
app lifespan is not started, so no database is needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import Request, Response
from fastapi.testclient import TestClient
from starlette.middleware.base import RequestResponseEndpoint

from gateway.api.deps import get_store
from gateway.api.org_secrets import OrgSecretsResponse
from tests.mcp_connectors_support import _auth_middlewares, isolated_app

REFUSED = "This action requires an interactive user"

_CURRENT_AUTH: dict[str, Any] = {"auth_method": "api_key", "user_id": "u1", "org_id": "org-1", "scopes": []}


def _as_api_key(*scopes: str) -> None:
    _CURRENT_AUTH.clear()
    _CURRENT_AUTH.update({"auth_method": "api_key", "user_id": "u1", "org_id": "org-1", "scopes": list(scopes)})


def _as_sandbox() -> None:
    """Exactly the shape a chat run token resolves to: admin scope, execution identity."""
    _CURRENT_AUTH.clear()
    _CURRENT_AUTH.update(
        {
            "auth_method": "notebook_session",
            "user_id": "u1",
            "org_id": "org-1",
            "scopes": ["read", "query", "execute", "write", "admin"],
            "execution_identity": "chat:run-1",
        }
    )


async def _controlled_dispatch(request: Request, call_next: RequestResponseEndpoint) -> Response:
    request.state.auth = dict(_CURRENT_AUTH)
    return await call_next(request)


def _fake_store() -> AsyncMock:
    store = AsyncMock()
    store.org_id = "org-1"
    store.user_id = "u1"
    store._require_org_id = lambda: "org-1"
    store.get_connection.return_value = None
    store.set_pii_config.return_value = {"enabled": True, "rules": {"email": "hash"}}
    store.get_pii_config.return_value = {"enabled": False, "rules": {}}
    return store


async def _fake_get_store() -> AsyncMock:
    return _fake_store()


@pytest.fixture
def client(monkeypatch):
    # Cloud mode: the org role comes from the token, so a sandbox token without an
    # org_role claim is a basic member. Local mode treats every caller as admin.
    monkeypatch.setattr("gateway.auth.user.is_cloud_mode", lambda: True)
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


# ── SP-03 ────────────────────────────────────────────────────────────────────


class TestPiiConfigRequiresOrgAdmin:
    def test_member_write_key_cannot_set_pii(self, client):
        _as_api_key("read", "write")
        response = client.put("/api/connections/wh/pii", json={"enabled": False, "rules": {}})
        assert response.status_code == 403
        assert "admin" in response.json()["detail"].lower()

    def test_member_write_key_cannot_detect_pii(self, client):
        _as_api_key("read", "write")
        assert client.post("/api/connections/wh/detect-pii").status_code == 403
        assert client.post("/api/connections/wh/detect-and-save-pii").status_code == 403

    def test_sandbox_token_cannot_set_pii(self, client):
        _as_sandbox()
        response = client.put("/api/connections/wh/pii", json={"enabled": False, "rules": {}})
        assert response.status_code == 403

    def test_admin_can_set_pii(self, client):
        _as_api_key("read", "write", "admin")
        response = client.put("/api/connections/wh/pii", json={"enabled": True, "rules": {"email": "hash"}})
        assert response.status_code == 200, response.text
        assert response.json() == {"enabled": True, "rules": {"email": "hash"}}

    def test_admin_detect_pii_reaches_handler(self, client):
        _as_api_key("read", "write", "admin")
        # The fake store has no such connection: the handler answered, not the gate.
        assert client.post("/api/connections/wh/detect-pii").status_code == 404

    def test_read_of_pii_config_is_unchanged_for_members(self, client):
        _as_api_key("read")
        response = client.get("/api/connections/wh/pii")
        assert response.status_code == 200
        assert response.json() == {"enabled": False, "rules": {}}


# ── SP-06 ────────────────────────────────────────────────────────────────────


@pytest.fixture
def secrets_handlers(monkeypatch):
    monkeypatch.setattr("gateway.api.org_secrets.org_secrets_store.set_org_anthropic_key", AsyncMock())
    monkeypatch.setattr("gateway.api.org_secrets.org_secrets_store.clear_org_anthropic_key", AsyncMock())
    monkeypatch.setattr("gateway.api.org_secrets._stop_active_notebook_sessions_for_org", AsyncMock(return_value=0))
    monkeypatch.setattr(
        "gateway.api.org_secrets._response_for_row",
        AsyncMock(return_value=OrgSecretsResponse(has_key=True, key_preview="sk-ant-a...")),
    )
    monkeypatch.setattr("gateway.api.org_secrets.org_secrets_store.resolve_anthropic_key", AsyncMock(return_value="sk-ant-x"))


class TestOrgSecretsRequireAdmin:
    def test_write_key_cannot_rotate_org_key(self, client, secrets_handlers):
        _as_api_key("read", "write")
        response = client.put("/api/org/secrets", json={"anthropic_api_key": "sk-ant-evil"})
        assert response.status_code == 403

    def test_sandbox_token_cannot_rotate_org_key(self, client, secrets_handlers):
        _as_sandbox()
        response = client.put("/api/org/secrets", json={"anthropic_api_key": None})
        assert response.status_code == 403

    def test_admin_key_rotates_org_key(self, client, secrets_handlers):
        _as_api_key("read", "write", "admin")
        response = client.put("/api/org/secrets", json={"anthropic_api_key": "sk-ant-new"})
        assert response.status_code == 200, response.text
        assert response.json()["has_key"] is True

    def test_sandbox_still_reads_runtime_key(self, client, secrets_handlers):
        """The notebook runtime fetches the org key with its session token."""
        _as_sandbox()
        response = client.get("/api/org/secrets/anthropic-key")
        assert response.status_code == 200, response.text
        assert response.json() == {"anthropic_api_key": "sk-ant-x"}

    def test_member_metadata_read_unchanged(self, client, secrets_handlers):
        _as_api_key("read")
        assert client.get("/api/org/secrets").status_code == 200


# ── SP-14 ────────────────────────────────────────────────────────────────────


@pytest.fixture
def chat_enabled(monkeypatch):
    monkeypatch.setattr("gateway.api.chat_routes.runs.chat_store.queue_steering_message", AsyncMock(return_value=None))
    monkeypatch.setattr("gateway.api.chat_routes.runs.chat_store.submit_clarification", AsyncMock(return_value=None))
    monkeypatch.setattr("gateway.api.chat_routes.runs.decide_query_proposal", AsyncMock(return_value=None))


_STATE_ROUTES = [
    ("/api/chat/runs/run-1/steer", {"message": "stop"}),
    ("/api/chat/runs/run-1/clarification", {"message": "yes"}),
    ("/api/chat/runs/run-1/retry", None),
    ("/api/chat/conversations/conv-1/runs", {"message": "hi"}),
    ("/api/chat/query-proposals/prop-1/decision", {"decision": "approve", "scope": "run_once"}),
]


class TestChatStateRoutesRefuseSandboxToken:
    @pytest.mark.parametrize("path,body", _STATE_ROUTES, ids=[p for p, _ in _STATE_ROUTES])
    def test_sandbox_token_refused(self, client, chat_enabled, path, body):
        _as_sandbox()
        response = client.post(path, json=body) if body is not None else client.post(path)
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == REFUSED

    def test_interactive_user_reaches_steer_handler(self, client, chat_enabled):
        _as_api_key("read", "write")
        response = client.post("/api/chat/runs/run-1/steer", json={"message": "stop"})
        # The stubbed store knows no such run: the guard let the user through.
        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Run not found"

    def test_interactive_user_reaches_clarification_handler(self, client, chat_enabled):
        _as_api_key("read", "write")
        response = client.post("/api/chat/runs/run-1/clarification", json={"message": "yes"})
        assert response.status_code == 404, response.text

    def test_interactive_user_reaches_decision_handler(self, client, chat_enabled, monkeypatch):
        monkeypatch.setenv("SP_FEATURE_CHAT_QUERY_APPROVAL", "1")
        _as_api_key("read", "write")
        response = client.post(
            "/api/chat/query-proposals/prop-1/decision", json={"decision": "approve", "scope": "run_once"}
        )
        assert response.status_code == 404, response.text

    def test_sandbox_token_still_cancels_and_streams(self, client, chat_enabled, monkeypatch):
        """Routes not in the finding keep accepting the run token (no UX change)."""
        monkeypatch.setattr("gateway.api.chat_routes.runs.chat_store.request_cancellation", AsyncMock(return_value=None))
        monkeypatch.setattr("gateway.api.chat_routes.runs.chat_store.list_run_events", AsyncMock(return_value=None))
        _as_sandbox()
        assert client.post("/api/chat/runs/run-1/cancel").status_code == 404
        assert client.get("/api/chat/runs/run-1/events").status_code == 404
