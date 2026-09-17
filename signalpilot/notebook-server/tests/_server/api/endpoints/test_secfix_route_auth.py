"""SP-15: the chat conversation and gateway_connections routes are edit-gated.

Runs the real routers behind the real auth middleware stack (session +
authentication middleware, AuthBackend, handle_error) so a decorator that is
present but not enforced would fail these tests.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

import signalpilot._plugins.ui  # noqa: F401  (import order: avoids a circular import)
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.routing import Mount

from signalpilot._server.api.auth import (
    CustomAuthenticationMiddleware,
    CustomSessionMiddleware,
    on_auth_error,
)
from signalpilot._server.api.endpoints import chat, datasources
from signalpilot._server.api.middleware import AuthBackend
from signalpilot._server.errors import handle_error
from signalpilot._session.model import SessionMode
from signalpilot._server.tokens import AuthToken

TOKEN = "secfix-access-token"
REJECT = (401, 403)


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Starlette:
    async def fake_gw(
        method: str, path: str, body: dict[str, Any] | None = None
    ) -> Any:
        return {"ok": True, "method": method, "path": path}

    async def fake_trace_list(request: Any) -> dict[str, Any]:
        return {"conversations": [{"id": "c1"}]}

    async def fake_trace_get(request: Any, cid: str) -> dict[str, Any]:
        return {"id": cid}

    monkeypatch.setattr(chat, "_gw", fake_gw)
    monkeypatch.setattr(chat, "_trace_list_conversations", fake_trace_list)
    monkeypatch.setattr(chat, "_trace_get_conversation", fake_trace_get)

    import signalpilot._gateway as gw_mod

    monkeypatch.setattr(gw_mod, "get_gateway_client", lambda: None)

    application = Starlette(
        routes=[
            Mount("/api/chat", app=chat.router),
            Mount("/api/datasources", app=datasources.router),
        ],
        middleware=[
            Middleware(CustomSessionMiddleware, secret_key="test-secret"),
            Middleware(
                CustomAuthenticationMiddleware,
                backend=AuthBackend(should_authenticate=True),
                on_error=on_auth_error,
            ),
        ],
        exception_handlers={HTTPException: handle_error},
    )
    application.state.session_manager = SimpleNamespace(
        mode=SessionMode.EDIT, auth_token=AuthToken(TOKEN)
    )
    return application


ROUTES = [
    ("POST", "/api/chat/conversations", {"title": "t"}),
    ("GET", "/api/chat/conversations", None),
    ("GET", "/api/chat/conversations/c1", None),
    ("DELETE", "/api/chat/conversations/c1", None),
    ("POST", "/api/chat/conversations/c1/messages", {"role": "user", "content": "hi"}),
    ("GET", "/api/chat/conversations/c1/messages", None),
    ("GET", "/api/datasources/gateway_connections", None),
]


async def _call(
    app: Starlette, method: str, path: str, body: Any, headers: dict[str, str]
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=body, headers=headers)


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_rejected_without_access_token(
    app: Starlette, method: str, path: str, body: Any
) -> None:
    response = await _call(app, method, path, body, {})
    assert response.status_code in REJECT, response.text


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_rejected_with_wrong_access_token(
    app: Starlette, method: str, path: str, body: Any
) -> None:
    response = await _call(
        app, method, path, body, {"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code in REJECT, response.text


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_accepted_with_access_token(
    app: Starlette, method: str, path: str, body: Any
) -> None:
    response = await _call(
        app, method, path, body, {"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 200, response.text


async def test_read_only_mode_is_rejected(app: Starlette) -> None:
    app.state.session_manager = SimpleNamespace(
        mode=SessionMode.RUN, auth_token=AuthToken(TOKEN)
    )
    for method, path, body in ROUTES:
        response = await _call(
            app, method, path, body, {"Authorization": f"Bearer {TOKEN}"}
        )
        assert response.status_code in REJECT, (path, response.text)
