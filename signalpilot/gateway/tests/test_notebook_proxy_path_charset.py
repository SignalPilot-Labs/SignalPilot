"""Tests for the notebook-proxy forwarded-path charset gate.

The query string was already validated against response splitting; the sibling
{path:path} segment is concatenated into the same upstream URL and gets the same
treatment on both the HTTP and WS routes.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from gateway.notebook_proxy import routes as proxy_routes
from gateway.notebook_proxy.auth import ProxySession, resolve_proxy_session

_UNSAFE_PATHS = [
    "foo\r\nX-Injected: 1",
    "foo\nX-Injected: 1",
    "foo\rX-Injected: 1",
    "api/kernels\r\n\r\nGET /admin HTTP/1.1",
    "foo bar",
    "foo\x00bar",
]

_SAFE_PATHS = [
    "",
    "api/kernels",
    "api/contents/work/notebook.ipynb",
    "lab/tree/dir~name/file-1.2_3.py",
    "api/contents/a%20b/c",
]


class TestPathPattern:
    @pytest.mark.parametrize("path", _UNSAFE_PATHS)
    def test_unsafe_path_rejected(self, path: str) -> None:
        with pytest.raises(HTTPException) as exc:
            proxy_routes._validate_upstream_path(path)
        assert exc.value.status_code == 400

    @pytest.mark.parametrize("path", _SAFE_PATHS)
    def test_safe_path_allowed(self, path: str) -> None:
        proxy_routes._validate_upstream_path(path)


@pytest.fixture
def app_client(monkeypatch):
    """App with the proxy router and a stubbed session; records proxy usage."""
    forwarded: list[str] = []

    class _StubProxy:
        def __init__(self, upstream_base, *, http_client=None, upstream_token=None):
            self._base = upstream_base
            self._token = upstream_token

        async def forward_http(self, request, upstream_path):
            forwarded.append(upstream_path)
            from fastapi.responses import PlainTextResponse

            return PlainTextResponse("ok")

        async def forward_ws(self, ws, upstream_url, accept_subprotocol=None):
            forwarded.append(upstream_url)
            await ws.accept(subprotocol=accept_subprotocol)
            await ws.close()

    monkeypatch.setattr(proxy_routes, "NotebookProxy", _StubProxy)
    monkeypatch.setattr(proxy_routes, "_get_proxy_client", lambda request: object())

    app = FastAPI()
    app.include_router(proxy_routes.router)
    app.dependency_overrides[resolve_proxy_session] = lambda: ProxySession(
        session_id="sess-1",
        user_id="user-1",
        org_id="org-1",
        upstream_base="http://10.42.0.5:2718",
        upstream_token="pod-notebook-token",
    )
    with TestClient(app) as client:
        yield client, forwarded


class TestHttpRoute:
    # Starlette's {path:path} regex already refuses to match a decoded newline,
    # so CR/LF cannot reach the handler; these are the chars that can.
    @pytest.mark.parametrize("encoded", ["foo%00bar", "foo%20bar", "foo%7Cbar", "foo%08bar"])
    def test_unsafe_path_rejected_and_never_forwarded(self, app_client, encoded: str) -> None:
        client, forwarded = app_client
        resp = client.get(f"/notebook/sess-1/{encoded}")
        assert resp.status_code == 400
        assert forwarded == []

    def test_crlf_path_never_reaches_upstream(self, app_client) -> None:
        client, forwarded = app_client
        resp = client.get("/notebook/sess-1/foo%0d%0aX-Injected:%201")
        assert resp.status_code in (400, 404)
        assert forwarded == []

    def test_legitimate_path_still_proxied(self, app_client) -> None:
        client, forwarded = app_client
        resp = client.get("/notebook/sess-1/api/kernels")
        assert resp.status_code == 200
        assert forwarded == ["api/kernels"]


class TestWebSocketRoute:
    @pytest.mark.parametrize("encoded", ["ws%00x", "ws%20x", "ws%08x"])
    def test_unsafe_path_closed_before_accept(self, app_client, encoded: str) -> None:
        client, forwarded = app_client
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/notebook/sess-1/{encoded}"):
                pass
        assert forwarded == []

    def test_crlf_path_never_reaches_upstream(self, app_client) -> None:
        client, forwarded = app_client
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/notebook/sess-1/ws%0d%0aX-Injected:%201"):
                pass
        assert forwarded == []

    def test_legitimate_ws_path_bridged(self, app_client) -> None:
        client, forwarded = app_client
        with client.websocket_connect("/notebook/sess-1/ws"):
            pass
        assert forwarded and forwarded[0].startswith("ws://10.42.0.5:2718/ws")
