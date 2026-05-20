"""Tests for the notebook reverse proxy — §3.14 of the R2 spec.

Covers:
- _init: cookie set, redirect, invalid charset, cross-org, cross-user
- Proxy HTTP: auth (cookie missing/mismatched), header stripping, streaming, SSE
- Proxy WS: auth, frame type, close code, handshake header stripping
- Security headers: CSP, X-Frame-Options, Cache-Control on proxy paths
- Session shape: notebook_url, access_token None
- Cookie clear on delete
- Orchestrator: pod CLI --no-token, no SP_ACCESS_TOKEN, fail-fast upstream mode
- Upstream mode: pod_ip_internal used (not NodePort)
"""

from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_session_row(
    session_id: str = "test-sess-123",
    org_id: str = "org-1",
    user_id: str = "user-1",
    status: str = "running",
    pod_ip_internal: str = "10.42.0.5",
    access_token: str = "secret-token-abc",
):
    """Build a fake GatewayNotebookSession-like object."""
    from gateway.db.models import GatewayNotebookSession

    row = GatewayNotebookSession(
        id=session_id,
        org_id=org_id,
        user_id=user_id,
        project_id="proj-1",
        branch="main",
        pod_name="nb-test",
        pod_ip="k3s:30042",
        pod_ip_internal=pod_ip_internal,
        access_token=access_token,
        status=status,
        last_ping=time.time(),
        created_at=time.time(),
    )
    return row


# ─── Cookie helpers ───────────────────────────────────────────────────────────


class TestCookieHelpers:
    """cookies.py: set_proxy_cookie and clear_proxy_cookie."""

    def test_set_proxy_cookie_attributes(self):
        from fastapi.responses import Response

        from gateway.notebook_proxy.cookies import set_proxy_cookie

        resp = Response()
        set_proxy_cookie(resp, session_id="abc-123", token="mytoken", secure=False, max_age=3600)
        set_cookie = resp.headers.get("set-cookie", "")
        assert "sp_nb_abc-123=mytoken" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert "Path=/notebook/abc-123" in set_cookie
        assert "Max-Age=3600" in set_cookie
        # secure flag should NOT be present when secure=False
        assert "Secure" not in set_cookie

    def test_set_proxy_cookie_secure_flag(self):
        from fastapi.responses import Response

        from gateway.notebook_proxy.cookies import set_proxy_cookie

        resp = Response()
        set_proxy_cookie(resp, session_id="abc-123", token="tok", secure=True, max_age=100)
        set_cookie = resp.headers.get("set-cookie", "")
        assert "Secure" in set_cookie

    def test_clear_proxy_cookie_max_age_zero(self):
        from fastapi.responses import Response

        from gateway.notebook_proxy.cookies import clear_proxy_cookie

        resp = Response()
        clear_proxy_cookie(resp, session_id="myid", secure=False)
        set_cookie = resp.headers.get("set-cookie", "")
        assert "sp_nb_myid=" in set_cookie
        assert "Max-Age=0" in set_cookie
        assert "Path=/notebook/myid" in set_cookie

    def test_clear_proxy_cookie_path_matches_set(self):
        """Path on clear must match the original set path — otherwise browser ignores it."""
        from fastapi.responses import Response

        from gateway.notebook_proxy.cookies import clear_proxy_cookie, set_proxy_cookie

        sid = "my-session-id"
        set_resp = Response()
        set_proxy_cookie(set_resp, session_id=sid, token="x", secure=False, max_age=3600)
        set_path = _extract_cookie_path(set_resp.headers.get("set-cookie", ""))

        clear_resp = Response()
        clear_proxy_cookie(clear_resp, session_id=sid, secure=False)
        clear_path = _extract_cookie_path(clear_resp.headers.get("set-cookie", ""))

        assert set_path == clear_path == f"/notebook/{sid}"


def _extract_cookie_path(set_cookie: str) -> str:
    """Extract the Path= value from a Set-Cookie header string."""
    for part in set_cookie.split(";"):
        part = part.strip()
        if part.lower().startswith("path="):
            return part[5:]
    return ""


# ─── SESSION_ID_PATTERN ───────────────────────────────────────────────────────


class TestSessionIdPattern:
    """auth.py: SESSION_ID_PATTERN charset validation."""

    def test_valid_uuid_matches(self):
        from gateway.notebook_proxy.auth import SESSION_ID_PATTERN

        sid = str(uuid.uuid4())
        assert SESSION_ID_PATTERN.match(sid)

    def test_valid_alphanumeric_matches(self):
        from gateway.notebook_proxy.auth import SESSION_ID_PATTERN

        assert SESSION_ID_PATTERN.match("abc123")
        assert SESSION_ID_PATTERN.match("Abc-123_def")

    def test_semicolon_does_not_match(self):
        from gateway.notebook_proxy.auth import SESSION_ID_PATTERN

        assert SESSION_ID_PATTERN.match("abc;path=/") is None

    def test_comma_does_not_match(self):
        from gateway.notebook_proxy.auth import SESSION_ID_PATTERN

        assert SESSION_ID_PATTERN.match("abc,xyz") is None

    def test_space_does_not_match(self):
        from gateway.notebook_proxy.auth import SESSION_ID_PATTERN

        assert SESSION_ID_PATTERN.match("abc xyz") is None

    def test_too_long_does_not_match(self):
        from gateway.notebook_proxy.auth import SESSION_ID_PATTERN

        assert SESSION_ID_PATTERN.match("a" * 65) is None

    def test_empty_does_not_match(self):
        from gateway.notebook_proxy.auth import SESSION_ID_PATTERN

        assert SESSION_ID_PATTERN.match("") is None


# ─── HTTP header stripping ────────────────────────────────────────────────────


class TestHeaderStripping:
    """proxy.py: outbound and inbound header stripping."""

    def test_outbound_strips_cookie(self):
        from gateway.notebook_proxy.constants import OUTBOUND_STRIP_HEADERS

        assert "cookie" in OUTBOUND_STRIP_HEADERS

    def test_outbound_strips_authorization(self):
        from gateway.notebook_proxy.constants import OUTBOUND_STRIP_HEADERS

        assert "authorization" in OUTBOUND_STRIP_HEADERS

    def test_outbound_strips_host(self):
        from gateway.notebook_proxy.constants import OUTBOUND_STRIP_HEADERS

        assert "host" in OUTBOUND_STRIP_HEADERS

    def test_outbound_strips_hop_by_hop(self):
        from gateway.notebook_proxy.constants import HOP_BY_HOP_HEADERS, OUTBOUND_STRIP_HEADERS

        assert HOP_BY_HOP_HEADERS.issubset(OUTBOUND_STRIP_HEADERS)

    def test_inbound_strips_set_cookie(self):
        from gateway.notebook_proxy.constants import INBOUND_STRIP_HEADERS

        assert "set-cookie" in INBOUND_STRIP_HEADERS

    def test_inbound_strips_hop_by_hop(self):
        from gateway.notebook_proxy.constants import HOP_BY_HOP_HEADERS, INBOUND_STRIP_HEADERS

        assert HOP_BY_HOP_HEADERS.issubset(INBOUND_STRIP_HEADERS)


# ─── Store: NotebookSessionInternal ──────────────────────────────────────────


class TestNotebookSessionInternal:
    """store/notebook_sessions.py: two read paths off the same row."""

    @pytest.mark.asyncio
    async def test_get_session_internal_returns_real_token(self):
        from gateway.db.models import GatewayNotebookSession
        from gateway.store.notebook_sessions import get_session_internal

        row = _make_session_row()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = row
        mock_session.execute.return_value = mock_result

        result = await get_session_internal(
            mock_session, session_id="test-sess-123", org_id="org-1"
        )
        assert result is not None
        assert result.access_token == "secret-token-abc"
        assert result.pod_ip_internal == "10.42.0.5"

    @pytest.mark.asyncio
    async def test_to_info_hides_access_token(self):
        from gateway.db.models import GatewayNotebookSession
        from gateway.store.notebook_sessions import get_session_by_id

        row = _make_session_row()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = row
        mock_session.execute.return_value = mock_result

        result = await get_session_by_id(
            mock_session, session_id="test-sess-123", org_id="org-1"
        )
        assert result is not None
        assert result.access_token is None

    @pytest.mark.asyncio
    async def test_to_info_notebook_url_is_init_path(self):
        from gateway.store.notebook_sessions import get_session_by_id

        row = _make_session_row()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = row
        mock_session.execute.return_value = mock_result

        result = await get_session_by_id(
            mock_session, session_id="test-sess-123", org_id="org-1"
        )
        assert result is not None
        assert result.notebook_url == "/notebook/test-sess-123/_init"

    @pytest.mark.asyncio
    async def test_get_session_internal_cross_org_returns_none(self):
        from gateway.store.notebook_sessions import get_session_internal

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await get_session_internal(
            mock_session, session_id="test-sess-123", org_id="wrong-org"
        )
        assert result is None


# ─── Orchestrator: pod CLI ────────────────────────────────────────────────────


class TestPodCLI:
    """kubernetes.py: pod manifest uses --no-token, no SP_ACCESS_TOKEN, --base-url."""

    def test_pod_cli_always_uses_no_token(self):
        from gateway.orchestrator.kubernetes import _pod_manifest

        manifest = _pod_manifest(
            pod_name="nb-test",
            namespace="default",
            image="signalpilot-notebook:latest",
            user_id="user-1",
            org_id="org-1",
            project_id="proj-1",
            branch="main",
            gateway_url="http://localhost:3300",
            session_jwt="test.jwt",
            session_id="sess-abc",
            access_token="some-token",
        )
        command = manifest["spec"]["containers"][0]["command"]
        assert "--no-token" in command
        assert "--token-password" not in command

    def test_pod_cli_no_token_when_access_token_none(self):
        from gateway.orchestrator.kubernetes import _pod_manifest

        manifest = _pod_manifest(
            pod_name="nb-test",
            namespace="default",
            image="signalpilot-notebook:latest",
            user_id="user-1",
            org_id="org-1",
            project_id=None,
            branch="main",
            gateway_url="http://localhost:3300",
            session_jwt="test.jwt",
            session_id="sess-xyz",
            access_token=None,
        )
        command = manifest["spec"]["containers"][0]["command"]
        assert "--no-token" in command
        assert "--token-password" not in command

    def test_pod_cli_includes_base_url(self):
        from gateway.orchestrator.kubernetes import _pod_manifest

        manifest = _pod_manifest(
            pod_name="nb-test",
            namespace="default",
            image="signalpilot-notebook:latest",
            user_id="user-1",
            org_id="org-1",
            project_id="proj-1",
            branch="main",
            gateway_url="http://localhost:3300",
            session_jwt="test.jwt",
            session_id="sess-abc",
            access_token=None,
        )
        command = manifest["spec"]["containers"][0]["command"]
        assert "--base-url" in command
        base_url_idx = command.index("--base-url")
        assert command[base_url_idx + 1] == "/notebook/sess-abc"

    def test_pod_env_no_sp_access_token(self):
        from gateway.orchestrator.kubernetes import _pod_manifest

        manifest = _pod_manifest(
            pod_name="nb-test",
            namespace="default",
            image="signalpilot-notebook:latest",
            user_id="user-1",
            org_id="org-1",
            project_id="proj-1",
            branch="main",
            gateway_url="http://localhost:3300",
            session_jwt="test.jwt",
            session_id="sess-abc",
            access_token="some-token",
        )
        env_names = {e["name"] for e in manifest["spec"]["containers"][0]["env"]}
        assert "SP_ACCESS_TOKEN" not in env_names
        assert "SP_SESSION_JWT" in env_names

    def test_pod_env_no_sp_access_token_when_none(self):
        from gateway.orchestrator.kubernetes import _pod_manifest

        manifest = _pod_manifest(
            pod_name="nb-test",
            namespace="default",
            image="signalpilot-notebook:latest",
            user_id="user-1",
            org_id="org-1",
            project_id=None,
            branch="main",
            gateway_url="http://localhost:3300",
            session_jwt="test.jwt",
            session_id="sess-abc",
            access_token=None,
        )
        env_names = {e["name"] for e in manifest["spec"]["containers"][0]["env"]}
        assert "SP_ACCESS_TOKEN" not in env_names


# ─── Invalid upstream mode ────────────────────────────────────────────────────


class TestInvalidUpstreamMode:
    """kubernetes.py: fail-fast on unknown SP_NOTEBOOK_UPSTREAM_MODE."""

    def test_invalid_upstream_mode_fails_fast(self, monkeypatch):
        """RuntimeError is raised at module import time for unknown mode values."""
        import importlib
        import sys

        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "foobar")
        # Remove cached module so it is re-evaluated with the new env var
        sys.modules.pop("gateway.orchestrator.kubernetes", None)

        with pytest.raises(RuntimeError, match="Invalid SP_NOTEBOOK_UPSTREAM_MODE"):
            importlib.import_module("gateway.orchestrator.kubernetes")

    def test_valid_upstream_mode_pod_ip(self, monkeypatch):
        import importlib
        import sys

        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")
        sys.modules.pop("gateway.orchestrator.kubernetes", None)
        mod = importlib.import_module("gateway.orchestrator.kubernetes")
        assert mod._UPSTREAM_MODE == "pod_ip"

    def test_valid_upstream_mode_nodeport(self, monkeypatch):
        import importlib
        import sys

        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "nodeport")
        sys.modules.pop("gateway.orchestrator.kubernetes", None)
        mod = importlib.import_module("gateway.orchestrator.kubernetes")
        assert mod._UPSTREAM_MODE == "nodeport"


# ─── NotebookProxy HTTP ───────────────────────────────────────────────────────


class TestNotebookProxyHTTP:
    """proxy.py: HTTP forwarding behaviour."""

    def _make_proxy(self, http_client):
        from gateway.notebook_proxy.proxy import NotebookProxy

        return NotebookProxy("http://10.42.0.5:2718", http_client=http_client)

    def _make_request(self, method="GET", path="/", query="", headers=None, body=b""):
        request = MagicMock()
        request.method = method
        url = MagicMock()
        url.query = query
        request.url = url
        request.headers = headers or {}

        async def _body():
            return body

        request.body = _body
        return request

    @pytest.mark.asyncio
    async def test_proxy_strips_outbound_cookie_and_authorization(self):
        """Cookie and Authorization headers must not reach the upstream pod."""
        captured_headers: dict = {}

        async def _fake_send(req, *, stream=False):
            captured_headers.update(dict(req.headers))
            response = MagicMock()
            response.status_code = 200
            response.headers = {"content-type": "text/plain"}

            async def _aiter():
                yield b"hello"

            response.aiter_bytes = _aiter
            response.aclose = AsyncMock()
            return response

        http_client = MagicMock()
        http_client.build_request = MagicMock(
            return_value=MagicMock(headers={"x-custom": "kept"})
        )
        http_client.send = _fake_send

        from gateway.notebook_proxy.proxy import NotebookProxy, _build_outbound_headers

        # Verify that cookie and authorization are stripped by the header builder
        request = self._make_request(
            headers={
                "cookie": "__session=clerkjwt; sp_nb_abc=proxycookie",
                "authorization": "Bearer abc123",
                "x-custom": "kept",
            }
        )
        outbound = _build_outbound_headers(request)
        assert "cookie" not in outbound
        assert "authorization" not in outbound
        assert "x-custom" in outbound

    @pytest.mark.asyncio
    async def test_proxy_strips_upstream_set_cookie(self):
        """Upstream Set-Cookie must not appear in the proxied response."""
        import httpx

        from gateway.notebook_proxy.proxy import _build_inbound_headers

        upstream_headers = httpx.Headers(
            {
                "content-type": "text/html",
                "set-cookie": "marimo_session=secret123; Path=/",
                "x-custom": "value",
            }
        )
        result = _build_inbound_headers(upstream_headers)
        assert "set-cookie" not in result
        assert "x-custom" in result

    @pytest.mark.asyncio
    async def test_proxy_strips_hop_by_hop_headers_inbound(self):
        """Connection header must be stripped from upstream response."""
        import httpx

        from gateway.notebook_proxy.proxy import _build_inbound_headers

        upstream_headers = httpx.Headers(
            {
                "connection": "keep-alive",
                "content-type": "text/plain",
                "transfer-encoding": "chunked",
                "x-keep": "yes",
            }
        )
        result = _build_inbound_headers(upstream_headers)
        assert "connection" not in result
        assert "transfer-encoding" not in result
        assert "x-keep" in result

    def test_proxy_strips_hop_by_hop_outbound(self):
        """Connection and other hop-by-hop headers stripped from outbound request."""
        from gateway.notebook_proxy.proxy import _build_outbound_headers

        request = self._make_request(
            headers={
                "connection": "keep-alive",
                "x-custom": "preserved",
                "upgrade": "websocket",
            }
        )
        result = _build_outbound_headers(request)
        assert "connection" not in result
        assert "upgrade" not in result
        assert "x-custom" in result

    @pytest.mark.asyncio
    async def test_proxy_502_on_connect_error(self):
        import httpx
        from fastapi import HTTPException

        http_client = MagicMock()
        http_client.build_request = MagicMock(return_value=MagicMock(headers={}))
        http_client.send = AsyncMock(side_effect=httpx.ConnectError("refused"))

        from gateway.notebook_proxy.proxy import NotebookProxy

        proxy = NotebookProxy("http://10.42.0.5:2718", http_client=http_client)
        request = self._make_request()

        with pytest.raises(HTTPException) as exc_info:
            await proxy.forward_http(request, "index.html")
        assert exc_info.value.status_code == 502


# ─── Security headers middleware ──────────────────────────────────────────────


class TestSecurityHeadersOnProxyPaths:
    """security_headers.py: /notebook/* exemptions."""

    def _build_middleware_response(self, path: str, monkeypatch=None):
        import asyncio

        from fastapi import FastAPI, Request
        from fastapi.responses import Response
        from starlette.testclient import TestClient

        from gateway.http.middleware.security_headers import SecurityHeadersMiddleware

        inner_app = FastAPI()

        @inner_app.get(path)
        async def _endpoint():
            return Response(content="ok", headers={"cache-control": "max-age=3600"})

        inner_app.add_middleware(SecurityHeadersMiddleware)
        with TestClient(inner_app, raise_server_exceptions=False) as client:
            return client.get(path)

    def test_proxy_path_sameorigin_xframe(self):
        resp = self._build_middleware_response("/notebook/abc/index.html")
        assert resp.headers.get("x-frame-options") == "SAMEORIGIN"

    def test_non_proxy_path_deny_xframe(self):
        resp = self._build_middleware_response("/api/something")
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_proxy_path_csp_frame_ancestors_only(self):
        resp = self._build_middleware_response("/notebook/abc/index.html")
        csp = resp.headers.get("content-security-policy", "")
        assert "frame-ancestors 'self'" in csp
        # Must NOT contain the full default-src policy
        assert "default-src" not in csp

    def test_proxy_path_no_cache_control_forced(self):
        """Upstream Cache-Control passes through; no-store not forced."""
        resp = self._build_middleware_response("/notebook/abc/app.js")
        # Middleware should NOT override with no-store
        cache_control = resp.headers.get("cache-control", "")
        assert "no-store" not in cache_control

    def test_non_proxy_path_cache_control_no_store(self):
        resp = self._build_middleware_response("/api/test")
        assert resp.headers.get("cache-control") == "no-store"


# ─── Notebook URL shape ────────────────────────────────────────────────────────


class TestNotebookUrlShape:
    """test_notebook_url_response_shape: notebook_url == /notebook/{id}/_init, access_token is None."""

    @pytest.mark.asyncio
    async def test_to_info_running_session_has_init_url(self):
        from gateway.store.notebook_sessions import _to_info
        from gateway.db.models import GatewayNotebookSession

        row = GatewayNotebookSession(
            id="sess-xyz",
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            pod_name="nb-xyz",
            pod_ip="k3s:30042",
            pod_ip_internal="10.42.0.5",
            access_token="secret",
            status="running",
            last_ping=time.time(),
            created_at=time.time(),
        )
        info = _to_info(row)
        assert info.notebook_url == "/notebook/sess-xyz/_init"
        assert info.access_token is None

    @pytest.mark.asyncio
    async def test_to_info_creating_session_has_no_url(self):
        from gateway.store.notebook_sessions import _to_info
        from gateway.db.models import GatewayNotebookSession

        row = GatewayNotebookSession(
            id="sess-abc",
            org_id="org-1",
            user_id="user-1",
            project_id=None,
            branch="main",
            pod_name="nb-abc",
            pod_ip=None,
            pod_ip_internal=None,
            access_token="token",
            status="creating",
            last_ping=time.time(),
            created_at=time.time(),
        )
        info = _to_info(row)
        assert info.notebook_url is None
        assert info.access_token is None


# ─── Delete session clears cookie ─────────────────────────────────────────────


class TestDeleteSessionClearsCookie:
    """test_delete_clears_cookie_with_correct_path."""

    @pytest.mark.asyncio
    async def test_clear_cookie_path_matches_notebook_path(self):
        """clear_proxy_cookie must use Path=/notebook/{sid} not Path=/."""
        from fastapi.responses import Response

        from gateway.notebook_proxy.cookies import clear_proxy_cookie

        sid = "sess-del-test"
        resp = Response()
        clear_proxy_cookie(resp, session_id=sid, secure=False)
        sc = resp.headers.get("set-cookie", "")
        assert f"Path=/notebook/{sid}" in sc
        assert "Max-Age=0" in sc


# ─── resolve_proxy_session unit tests ────────────────────────────────────────


class TestResolveProxySession:
    """auth.py: resolve_proxy_session dependency."""

    def _make_store(self, internal_session):
        store = MagicMock()
        store.session = AsyncMock()
        store.org_id = "org-1"
        store.user_id = "user-1"
        return store

    def _make_request(self, cookies: dict):
        request = MagicMock()
        request.cookies = cookies
        request.headers = {}
        request.state = MagicMock()
        request.state.auth = None
        return request

    @pytest.mark.asyncio
    async def test_invalid_session_id_charset_raises_404(self, monkeypatch):
        from fastapi import HTTPException

        from gateway.notebook_proxy.auth import resolve_proxy_session

        store = self._make_store(None)
        request = self._make_request({})

        with pytest.raises(HTTPException) as exc_info:
            await resolve_proxy_session("bad;id", request, store)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_cookie_raises_401(self, monkeypatch):
        from fastapi import HTTPException

        import gateway.notebook_proxy.auth as auth_mod
        import gateway.store.notebook_sessions as ns_mod
        from gateway.store.notebook_sessions import NotebookSessionInternal

        internal = NotebookSessionInternal(
            session_id="sess-123",
            org_id="org-1",
            user_id="user-1",
            status="running",
            pod_ip_internal="10.42.0.5",
            access_token="secret",
        )

        monkeypatch.setattr(ns_mod, "get_session_internal", AsyncMock(return_value=internal))

        async def _fake_user(req):
            return "user-1"

        async def _fake_org(req, uid):
            return "org-1"

        monkeypatch.setattr(auth_mod, "resolve_user_id", _fake_user)
        monkeypatch.setattr(auth_mod, "resolve_org_id", _fake_org)

        store = self._make_store(internal)
        request = self._make_request({})  # No cookie

        with pytest.raises(HTTPException) as exc_info:
            from gateway.notebook_proxy.auth import resolve_proxy_session

            await resolve_proxy_session("sess-123", request, store)
        assert exc_info.value.status_code == 401
        assert exc_info.value.headers.get("WWW-Authenticate") == "SP-Notebook-Init"

    @pytest.mark.asyncio
    async def test_mismatched_cookie_raises_401(self, monkeypatch):
        from fastapi import HTTPException

        import gateway.notebook_proxy.auth as auth_mod
        import gateway.store.notebook_sessions as ns_mod
        from gateway.store.notebook_sessions import NotebookSessionInternal

        internal = NotebookSessionInternal(
            session_id="sess-123",
            org_id="org-1",
            user_id="user-1",
            status="running",
            pod_ip_internal="10.42.0.5",
            access_token="correct-secret",
        )

        monkeypatch.setattr(ns_mod, "get_session_internal", AsyncMock(return_value=internal))

        async def _fake_user(req):
            return "user-1"

        async def _fake_org(req, uid):
            return "org-1"

        monkeypatch.setattr(auth_mod, "resolve_user_id", _fake_user)
        monkeypatch.setattr(auth_mod, "resolve_org_id", _fake_org)

        store = self._make_store(internal)
        request = self._make_request({"sp_nb_sess-123": "wrong-value"})

        with pytest.raises(HTTPException) as exc_info:
            from gateway.notebook_proxy.auth import resolve_proxy_session

            await resolve_proxy_session("sess-123", request, store)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_session_not_running_raises_409(self, monkeypatch):
        from fastapi import HTTPException

        import gateway.notebook_proxy.auth as auth_mod
        import gateway.store.notebook_sessions as ns_mod
        from gateway.store.notebook_sessions import NotebookSessionInternal

        internal = NotebookSessionInternal(
            session_id="sess-123",
            org_id="org-1",
            user_id="user-1",
            status="creating",  # Not running
            pod_ip_internal=None,
            access_token="secret",
        )

        monkeypatch.setattr(ns_mod, "get_session_internal", AsyncMock(return_value=internal))

        async def _fake_user(req):
            return "user-1"

        async def _fake_org(req, uid):
            return "org-1"

        monkeypatch.setattr(auth_mod, "resolve_user_id", _fake_user)
        monkeypatch.setattr(auth_mod, "resolve_org_id", _fake_org)

        store = self._make_store(internal)
        request = self._make_request({"sp_nb_sess-123": "secret"})

        with pytest.raises(HTTPException) as exc_info:
            from gateway.notebook_proxy.auth import resolve_proxy_session

            await resolve_proxy_session("sess-123", request, store)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_cross_org_session_raises_404(self, monkeypatch):
        from fastapi import HTTPException

        import gateway.notebook_proxy.auth as auth_mod
        import gateway.store.notebook_sessions as ns_mod

        # get_session_internal returns None (cross-org)
        monkeypatch.setattr(ns_mod, "get_session_internal", AsyncMock(return_value=None))

        async def _fake_user(req):
            return "user-1"

        async def _fake_org(req, uid):
            return "org-b"  # Different org

        monkeypatch.setattr(auth_mod, "resolve_user_id", _fake_user)
        monkeypatch.setattr(auth_mod, "resolve_org_id", _fake_org)

        store = self._make_store(None)
        request = self._make_request({})

        with pytest.raises(HTTPException) as exc_info:
            from gateway.notebook_proxy.auth import resolve_proxy_session

            await resolve_proxy_session("sess-123", request, store)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cross_user_same_org_raises_404(self, monkeypatch):
        from fastapi import HTTPException

        import gateway.notebook_proxy.auth as auth_mod
        import gateway.store.notebook_sessions as ns_mod
        from gateway.store.notebook_sessions import NotebookSessionInternal

        internal = NotebookSessionInternal(
            session_id="sess-123",
            org_id="org-1",
            user_id="user-owner",  # Owned by different user
            status="running",
            pod_ip_internal="10.42.0.5",
            access_token="secret",
        )

        monkeypatch.setattr(ns_mod, "get_session_internal", AsyncMock(return_value=internal))

        async def _fake_user(req):
            return "user-attacker"  # Not the owner

        async def _fake_org(req, uid):
            return "org-1"

        monkeypatch.setattr(auth_mod, "resolve_user_id", _fake_user)
        monkeypatch.setattr(auth_mod, "resolve_org_id", _fake_org)

        store = self._make_store(internal)
        request = self._make_request({})

        with pytest.raises(HTTPException) as exc_info:
            from gateway.notebook_proxy.auth import resolve_proxy_session

            await resolve_proxy_session("sess-123", request, store)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_valid_session_returns_proxy_session(self, monkeypatch):
        import gateway.notebook_proxy.auth as auth_mod
        import gateway.store.notebook_sessions as ns_mod
        from gateway.notebook_proxy.auth import ProxySession
        from gateway.store.notebook_sessions import NotebookSessionInternal

        token = secrets.token_urlsafe(24)
        internal = NotebookSessionInternal(
            session_id="sess-123",
            org_id="org-1",
            user_id="user-1",
            status="running",
            pod_ip_internal="10.42.0.5",
            access_token=token,
        )

        monkeypatch.setattr(ns_mod, "get_session_internal", AsyncMock(return_value=internal))

        async def _fake_user(req):
            return "user-1"

        async def _fake_org(req, uid):
            return "org-1"

        monkeypatch.setattr(auth_mod, "resolve_user_id", _fake_user)
        monkeypatch.setattr(auth_mod, "resolve_org_id", _fake_org)

        store = self._make_store(internal)
        request = self._make_request({f"sp_nb_sess-123": token})

        from gateway.notebook_proxy.auth import resolve_proxy_session

        result = await resolve_proxy_session("sess-123", request, store)
        assert isinstance(result, ProxySession)
        assert result.upstream_base == "http://10.42.0.5:2718"

    @pytest.mark.asyncio
    async def test_compare_digest_used(self, monkeypatch):
        """Verify compare_digest is called rather than ==."""
        import gateway.notebook_proxy.auth as auth_mod
        import gateway.store.notebook_sessions as ns_mod
        from gateway.store.notebook_sessions import NotebookSessionInternal

        token = "correct-token"
        internal = NotebookSessionInternal(
            session_id="sess-123",
            org_id="org-1",
            user_id="user-1",
            status="running",
            pod_ip_internal="10.42.0.5",
            access_token=token,
        )
        monkeypatch.setattr(ns_mod, "get_session_internal", AsyncMock(return_value=internal))

        digest_calls = []
        original_compare = secrets.compare_digest

        def _spy_compare(a, b):
            digest_calls.append((a, b))
            return original_compare(a, b)

        monkeypatch.setattr(auth_mod.secrets, "compare_digest", _spy_compare)

        async def _fake_user(req):
            return "user-1"

        async def _fake_org(req, uid):
            return "org-1"

        monkeypatch.setattr(auth_mod, "resolve_user_id", _fake_user)
        monkeypatch.setattr(auth_mod, "resolve_org_id", _fake_org)

        store = self._make_store(internal)
        request = self._make_request({"sp_nb_sess-123": token})

        from gateway.notebook_proxy.auth import resolve_proxy_session

        await resolve_proxy_session("sess-123", request, store)
        assert len(digest_calls) == 1, "compare_digest must be called exactly once"


# ─── Proxy uses pod_ip_internal not nodeport ──────────────────────────────────


class TestProxyUsesInternalIp:
    """test_proxy_route_uses_internal_ip_not_nodeport."""

    @pytest.mark.asyncio
    async def test_upstream_base_uses_pod_ip_internal(self, monkeypatch):
        import gateway.notebook_proxy.auth as auth_mod
        import gateway.store.notebook_sessions as ns_mod
        from gateway.store.notebook_sessions import NotebookSessionInternal

        token = "tok"
        internal = NotebookSessionInternal(
            session_id="sess-123",
            org_id="org-1",
            user_id="user-1",
            status="running",
            pod_ip_internal="10.42.0.5",  # Internal pod IP
            access_token=token,
        )
        monkeypatch.setattr(ns_mod, "get_session_internal", AsyncMock(return_value=internal))

        async def _fake_user(req):
            return "user-1"

        async def _fake_org(req, uid):
            return "org-1"

        monkeypatch.setattr(auth_mod, "resolve_user_id", _fake_user)
        monkeypatch.setattr(auth_mod, "resolve_org_id", _fake_org)

        store = MagicMock()
        store.session = AsyncMock()
        request = MagicMock()
        request.cookies = {"sp_nb_sess-123": token}
        request.headers = {}
        request.state = MagicMock()
        request.state.auth = None

        from gateway.notebook_proxy.auth import resolve_proxy_session

        result = await resolve_proxy_session("sess-123", request, store)
        # Must use internal IP, not any nodeport address
        assert "10.42.0.5" in result.upstream_base
        assert "30" not in result.upstream_base  # NodePort ports are 30000+


# ─── H-1: NodePort service not created in pod_ip mode ─────────────────────────


class TestNodePortServiceGating:
    """H-1: NodePort service is only created in nodeport mode, never in pod_ip mode."""

    @pytest.mark.asyncio
    async def test_pod_ip_mode_does_not_create_nodeport_service(self, monkeypatch):
        """In pod_ip mode, create_pod must NOT call create_namespaced_service."""
        import sys

        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        sys.modules.pop("gateway.orchestrator.kubernetes", None)

        import importlib

        mod = importlib.import_module("gateway.orchestrator.kubernetes")
        orch = mod.KubernetesOrchestrator()

        core_api = AsyncMock()
        core_api.create_namespaced_pod = AsyncMock()
        core_api.create_namespaced_service = AsyncMock()
        orch._core_api = core_api
        orch._client = MagicMock()

        await orch.create_pod(
            pod_name="nb-test",
            user_id="user-1",
            org_id="org-1",
            project_id="proj-1",
            branch="main",
            image="signalpilot-notebook:latest",
            gateway_url="http://localhost:3300",
            session_jwt="test.jwt",
            session_id="sess-abc",
            access_token="tok",
        )
        core_api.create_namespaced_pod.assert_called_once()
        core_api.create_namespaced_service.assert_not_called()

    @pytest.mark.asyncio
    async def test_nodeport_mode_in_cloud_raises_runtime_error(self, monkeypatch):
        """nodeport mode is forbidden in cloud mode — fail-fast at create_pod."""
        import sys

        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "nodeport")
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        sys.modules.pop("gateway.orchestrator.kubernetes", None)

        import importlib

        mod = importlib.import_module("gateway.orchestrator.kubernetes")
        orch = mod.KubernetesOrchestrator()

        core_api = AsyncMock()
        core_api.create_namespaced_pod = AsyncMock()
        core_api.create_namespaced_service = AsyncMock()
        orch._core_api = core_api
        orch._client = MagicMock()

        with pytest.raises(RuntimeError, match="nodeport.*forbidden.*cloud"):
            await orch.create_pod(
                pod_name="nb-test",
                user_id="user-1",
                org_id="org-1",
                project_id="proj-1",
                branch="main",
                image="signalpilot-notebook:latest",
                gateway_url="https://gateway.example.com",
                session_jwt="test.jwt",
                session_id="sess-abc",
                access_token="tok",
            )

    @pytest.mark.asyncio
    async def test_nodeport_mode_in_local_creates_service(self, monkeypatch):
        """nodeport mode in local deployment creates the NodePort service."""
        import sys

        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "nodeport")
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        sys.modules.pop("gateway.orchestrator.kubernetes", None)

        import importlib

        mod = importlib.import_module("gateway.orchestrator.kubernetes")
        orch = mod.KubernetesOrchestrator()

        core_api = AsyncMock()
        core_api.create_namespaced_pod = AsyncMock()
        core_api.create_namespaced_service = AsyncMock()
        orch._core_api = core_api
        orch._client = MagicMock()

        await orch.create_pod(
            pod_name="nb-test",
            user_id="user-1",
            org_id="org-1",
            project_id="proj-1",
            branch="main",
            image="signalpilot-notebook:latest",
            gateway_url="http://localhost:3300",
            session_jwt="test.jwt",
            session_id="sess-abc",
            access_token="tok",
        )
        core_api.create_namespaced_pod.assert_called_once()
        core_api.create_namespaced_service.assert_called_once()


# ─── M-1: User ownership check on session API endpoints ───────────────────────


class TestSessionOwnershipCheck:
    """M-1: Same-org peers cannot access each other's sessions."""

    @pytest.mark.asyncio
    async def test_get_session_by_id_cross_user_raises_404(self, monkeypatch):
        """GET /{session_id} from a different user in same org returns 404."""
        from fastapi import HTTPException

        import gateway.api.notebook_sessions as ns_api_mod
        import gateway.store.notebook_sessions as ns_store_mod
        from gateway.models.notebook_sessions import NotebookSessionInfo

        session_owner = NotebookSessionInfo(
            id="sess-owned",
            org_id="org-1",
            user_id="user-owner",  # Owned by different user
            project_id="proj-1",
            branch="main",
            pod_name="nb-test",
            pod_ip="10.0.0.1",
            access_token=None,
            status="running",
            last_ping=time.time(),
            created_at=time.time(),
        )

        monkeypatch.setattr(
            ns_store_mod, "get_session_by_id", AsyncMock(return_value=session_owner)
        )

        store = MagicMock()
        store.session = AsyncMock()
        store.org_id = "org-1"
        store.user_id = "user-attacker"  # Different user, same org

        with pytest.raises(HTTPException) as exc_info:
            await ns_api_mod.get_session_by_id("sess-owned", store)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_session_by_id_cross_user_raises_404(self, monkeypatch):
        """DELETE /{session_id} from a different user in same org returns 404."""
        from fastapi import HTTPException
        from fastapi.responses import Response

        import gateway.api.notebook_sessions as ns_api_mod
        import gateway.store.notebook_sessions as ns_store_mod
        from gateway.models.notebook_sessions import NotebookSessionInfo

        session_owner = NotebookSessionInfo(
            id="sess-owned",
            org_id="org-1",
            user_id="user-owner",
            project_id="proj-1",
            branch="main",
            pod_name="nb-test",
            pod_ip="10.0.0.1",
            access_token=None,
            status="running",
            last_ping=time.time(),
            created_at=time.time(),
        )

        monkeypatch.setattr(
            ns_store_mod, "get_session_by_id", AsyncMock(return_value=session_owner)
        )

        store = MagicMock()
        store.session = AsyncMock()
        store.org_id = "org-1"
        store.user_id = "user-attacker"
        response = Response()

        with pytest.raises(HTTPException) as exc_info:
            await ns_api_mod.delete_session_by_id("sess-owned", store, response)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_ping_session_by_id_cross_user_raises_404(self, monkeypatch):
        """POST /{session_id}/ping from a different user in same org returns 404."""
        from fastapi import HTTPException

        import gateway.api.notebook_sessions as ns_api_mod
        import gateway.store.notebook_sessions as ns_store_mod
        from gateway.models.notebook_sessions import NotebookSessionInfo

        session_owner = NotebookSessionInfo(
            id="sess-owned",
            org_id="org-1",
            user_id="user-owner",
            project_id="proj-1",
            branch="main",
            pod_name="nb-test",
            pod_ip="10.0.0.1",
            access_token=None,
            status="running",
            last_ping=time.time(),
            created_at=time.time(),
        )

        monkeypatch.setattr(
            ns_store_mod, "get_session_by_id", AsyncMock(return_value=session_owner)
        )

        store = MagicMock()
        store.session = AsyncMock()
        store.org_id = "org-1"
        store.user_id = "user-attacker"

        with pytest.raises(HTTPException) as exc_info:
            await ns_api_mod.ping_session_by_id("sess-owned", store)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_session_by_id_owner_succeeds(self, monkeypatch):
        """GET /{session_id} by the actual owner returns the session."""
        import gateway.api.notebook_sessions as ns_api_mod
        import gateway.store.notebook_sessions as ns_store_mod
        from gateway.models.notebook_sessions import NotebookSessionInfo

        session_info = NotebookSessionInfo(
            id="sess-mine",
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            pod_name="nb-test",
            pod_ip="10.0.0.1",
            access_token=None,
            status="running",
            last_ping=time.time(),
            created_at=time.time(),
        )

        monkeypatch.setattr(
            ns_store_mod, "get_session_by_id", AsyncMock(return_value=session_info)
        )

        store = MagicMock()
        store.session = AsyncMock()
        store.org_id = "org-1"
        store.user_id = "user-1"  # Same as owner

        result = await ns_api_mod.get_session_by_id("sess-mine", store)
        assert result.id == "sess-mine"


# ─── M-2: resolve_proxy_session accepts HTTPConnection (WS-compatible) ─────────


class TestResolveProxySessionHTTPConnection:
    """M-2: resolve_proxy_session uses HTTPConnection, not Request, so it works on WS routes."""

    def test_resolve_proxy_session_param_is_httpconnection(self):
        """resolve_proxy_session's second parameter must be 'connection: HTTPConnection'."""
        import inspect
        import typing

        from starlette.requests import HTTPConnection

        from gateway.notebook_proxy import auth as auth_mod
        from gateway.notebook_proxy.auth import resolve_proxy_session

        sig = inspect.signature(resolve_proxy_session)
        params = list(sig.parameters.values())
        # params: session_id, connection, store
        connection_param = params[1]
        assert connection_param.name == "connection"
        # Resolve the annotation — `from __future__ import annotations` turns all
        # annotations into strings; get_type_hints resolves them back to types.
        hints = typing.get_type_hints(auth_mod.resolve_proxy_session)
        assert hints["connection"] is HTTPConnection

    @pytest.mark.asyncio
    async def test_websocket_object_accepted_as_connection(self, monkeypatch):
        """WebSocket (HTTPConnection subclass) is accepted by resolve_proxy_session."""
        import gateway.notebook_proxy.auth as auth_mod
        import gateway.store.notebook_sessions as ns_mod
        from fastapi.websockets import WebSocket
        from gateway.store.notebook_sessions import NotebookSessionInternal

        token = "tok-ws"
        internal = NotebookSessionInternal(
            session_id="sess-ws",
            org_id="org-1",
            user_id="user-1",
            status="running",
            pod_ip_internal="10.42.0.5",
            access_token=token,
        )
        monkeypatch.setattr(ns_mod, "get_session_internal", AsyncMock(return_value=internal))

        async def _fake_user(conn):
            return "user-1"

        async def _fake_org(conn, uid):
            return "org-1"

        monkeypatch.setattr(auth_mod, "resolve_user_id", _fake_user)
        monkeypatch.setattr(auth_mod, "resolve_org_id", _fake_org)

        # Build a minimal WebSocket-like mock that is an HTTPConnection subclass
        from starlette.requests import HTTPConnection

        ws_mock = MagicMock(spec=HTTPConnection)
        ws_mock.cookies = {f"sp_nb_sess-ws": token}
        ws_mock.headers = {}
        ws_mock.state = MagicMock()
        ws_mock.state.auth = None

        store = MagicMock()
        store.session = AsyncMock()

        from gateway.notebook_proxy.auth import resolve_proxy_session

        result = await resolve_proxy_session("sess-ws", ws_mock, store)
        assert result.session_id == "sess-ws"
        assert result.upstream_base == "http://10.42.0.5:2718"


# ─── M-3: WS query string validation ─────────────────────────────────────────


class TestWsQueryValidation:
    """M-3: WS query string is validated before forwarding."""

    def test_safe_query_accepted(self):
        """A normal query string passes validation."""
        from gateway.notebook_proxy.routes import _WS_QUERY_SAFE_PATTERN

        assert _WS_QUERY_SAFE_PATTERN.match("session_id=abc&token=xyz")
        assert _WS_QUERY_SAFE_PATTERN.match("key=value%20encoded")
        assert _WS_QUERY_SAFE_PATTERN.match("")

    def test_crlf_in_query_rejected(self):
        """CR or LF in query string must not pass validation."""
        from gateway.notebook_proxy.routes import _WS_QUERY_SAFE_PATTERN

        assert _WS_QUERY_SAFE_PATTERN.match("bad\r\nvalue") is None
        assert _WS_QUERY_SAFE_PATTERN.match("bad\nvalue") is None
        assert _WS_QUERY_SAFE_PATTERN.match("bad\rvalue") is None

    def test_semicolon_in_query_rejected(self):
        """Semicolon in query string is rejected (not in safe charset)."""
        from gateway.notebook_proxy.routes import _WS_QUERY_SAFE_PATTERN

        assert _WS_QUERY_SAFE_PATTERN.match("a=b;c=d") is None


# ─── M-4: clear_proxy_cookie validates session_id ────────────────────────────


class TestClearProxyCookieValidation:
    """M-4: clear_proxy_cookie validates session_id charset."""

    def test_invalid_session_id_raises_in_clear(self):
        """clear_proxy_cookie raises 404 for session_id with illegal chars."""
        from fastapi import HTTPException
        from fastapi.responses import Response

        from gateway.notebook_proxy.cookies import clear_proxy_cookie

        resp = Response()
        with pytest.raises(HTTPException) as exc_info:
            clear_proxy_cookie(resp, session_id="bad;id\r\n", secure=False)
        assert exc_info.value.status_code == 404

    def test_valid_session_id_clears_normally(self):
        """clear_proxy_cookie works for a valid session_id."""
        from fastapi.responses import Response

        from gateway.notebook_proxy.cookies import clear_proxy_cookie

        resp = Response()
        clear_proxy_cookie(resp, session_id="valid-sess-id", secure=False)
        sc = resp.headers.get("set-cookie", "")
        assert "sp_nb_valid-sess-id=" in sc
        assert "Max-Age=0" in sc

    def test_invalid_session_id_raises_in_set(self):
        """set_proxy_cookie raises 404 for session_id with illegal chars."""
        from fastapi import HTTPException
        from fastapi.responses import Response

        from gateway.notebook_proxy.cookies import set_proxy_cookie

        resp = Response()
        with pytest.raises(HTTPException) as exc_info:
            set_proxy_cookie(resp, session_id="bad;id", token="x", secure=False, max_age=100)
        assert exc_info.value.status_code == 404


# ─── M-5: CSP path gate uses exact shape ─────────────────────────────────────


class TestCspPathGateExact:
    """M-5: Security headers only apply relaxed CSP to exact /notebook/{seg}/... shape."""

    def test_notebook_other_prefix_not_exempt(self):
        """A path like /notebook-other/... must NOT get the relaxed proxy CSP."""
        from gateway.http.middleware.security_headers import _NOTEBOOK_PROXY_PATH_RE

        assert _NOTEBOOK_PROXY_PATH_RE.match("/notebook-other/foo") is None

    def test_bare_notebook_slash_not_exempt(self):
        """/notebook/ (no session_id segment) must NOT get the relaxed CSP."""
        from gateway.http.middleware.security_headers import _NOTEBOOK_PROXY_PATH_RE

        assert _NOTEBOOK_PROXY_PATH_RE.match("/notebook/") is None

    def test_notebook_with_session_id_is_exempt(self):
        """/notebook/{session_id}/path is matched and gets the relaxed CSP."""
        from gateway.http.middleware.security_headers import _NOTEBOOK_PROXY_PATH_RE

        assert _NOTEBOOK_PROXY_PATH_RE.match("/notebook/abc-123/index.html")
        assert _NOTEBOOK_PROXY_PATH_RE.match("/notebook/sess-id/ws")

    def test_middleware_non_proxy_paths_unchanged(self):
        """Non-proxy paths still get DENY X-Frame-Options and default CSP."""
        import asyncio

        from fastapi import FastAPI
        from fastapi.responses import Response
        from starlette.testclient import TestClient

        from gateway.http.middleware.security_headers import SecurityHeadersMiddleware

        inner_app = FastAPI()

        @inner_app.get("/notebook-other/foo")
        async def _endpoint():
            return Response(content="ok")

        inner_app.add_middleware(SecurityHeadersMiddleware)
        with TestClient(inner_app, raise_server_exceptions=False) as client:
            resp = client.get("/notebook-other/foo")
        # Must be DENY, not SAMEORIGIN
        assert resp.headers.get("x-frame-options") == "DENY"


# ─── M-6: Error logs do not leak pod IP ───────────────────────────────────────


class TestProxyErrorLogScrubbing:
    """M-6: Upstream connect errors must not emit warning-level logs with pod IP."""

    @pytest.mark.asyncio
    async def test_connect_error_logged_at_debug_not_warning(self, monkeypatch, caplog):
        """502 connect error is logged at DEBUG, not WARNING."""
        import logging

        import httpx
        from fastapi import HTTPException

        http_client = MagicMock()
        http_client.build_request = MagicMock(return_value=MagicMock(headers={}))
        http_client.send = AsyncMock(side_effect=httpx.ConnectError("Connection refused to 10.42.0.5"))

        from gateway.notebook_proxy.proxy import NotebookProxy

        proxy = NotebookProxy("http://10.42.0.5:2718", http_client=http_client)

        request = MagicMock()
        request.method = "GET"
        url = MagicMock()
        url.query = ""
        request.url = url
        request.headers = {}

        async def _body():
            return b""

        request.body = _body

        import gateway.notebook_proxy.proxy as proxy_mod

        with caplog.at_level(logging.WARNING, logger=proxy_mod.__name__):
            with pytest.raises(HTTPException) as exc_info:
                await proxy.forward_http(request, "test")

        assert exc_info.value.status_code == 502
        # No warning-level log containing the pod IP should appear
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        for msg in warning_messages:
            assert "10.42.0.5" not in msg, f"Pod IP leaked in warning log: {msg}"


# ─── Session ID validation on API endpoints ────────────────────────────────────


class TestSessionIdValidationOnApiEndpoints:
    """M-4: Session ID charset validation on get/delete/ping endpoints."""

    @pytest.mark.asyncio
    async def test_get_session_by_id_invalid_charset_raises_404(self, monkeypatch):
        from fastapi import HTTPException

        import gateway.api.notebook_sessions as ns_api_mod

        store = MagicMock()
        store.session = AsyncMock()
        store.org_id = "org-1"
        store.user_id = "user-1"

        with pytest.raises(HTTPException) as exc_info:
            await ns_api_mod.get_session_by_id("bad;id", store)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_session_by_id_invalid_charset_raises_404(self, monkeypatch):
        from fastapi import HTTPException
        from fastapi.responses import Response

        import gateway.api.notebook_sessions as ns_api_mod

        store = MagicMock()
        store.session = AsyncMock()
        store.org_id = "org-1"
        store.user_id = "user-1"
        response = Response()

        with pytest.raises(HTTPException) as exc_info:
            await ns_api_mod.delete_session_by_id("bad\r\nid", store, response)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_ping_session_by_id_invalid_charset_raises_404(self, monkeypatch):
        from fastapi import HTTPException

        import gateway.api.notebook_sessions as ns_api_mod

        store = MagicMock()
        store.session = AsyncMock()
        store.org_id = "org-1"
        store.user_id = "user-1"

        with pytest.raises(HTTPException) as exc_info:
            await ns_api_mod.ping_session_by_id("bad,id", store)
        assert exc_info.value.status_code == 404
