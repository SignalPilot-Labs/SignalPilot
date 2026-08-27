"""Verify the notebook reverse proxy contract (Runtime v2).

Covers:
- Proxy HTTP/WS: header stripping (cookie/authorization/set-cookie/hop-by-hop)
- Security headers: CSP, X-Frame-Options, Cache-Control on proxy paths
- Session shape: tokenless notebook_url, no credential fields FE-side
- Session ownership: cross-user/cross-org 404 on API endpoints
- Upstream resolution: sandbox route URL + --base-url path, ws/wss scheme
  bridging, active-org authorization, fail-closed on missing credentials
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
from cryptography.fernet import Fernet

# Helper functions.


def _patch_encryption_key(monkeypatch):
    import gateway.store.crypto as crypto

    monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)
    monkeypatch.setenv("SP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("SP_ENCRYPTION_KEY_OLD", raising=False)
    monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)


def _make_session_row(
    session_id: str = "test-sess-123",
    org_id: str = "org-1",
    user_id: str = "user-1",
    status: str = "running",
    upstream_url: str = "https://sbx-abc.vercel.run",
    access_token_enc: bytes | None = None,
):
    """Build a GatewayNotebookSession test double.

    ``access_token_enc`` stores the encrypted access token.
    """
    from gateway.db.models import GatewayNotebookSession

    return GatewayNotebookSession(
        id=session_id,
        org_id=org_id,
        user_id=user_id,
        project_id="proj-1",
        branch="main",
        backend="vercel",
        runtime_handle="sbx-abc",
        upstream_url=upstream_url,
        access_token_enc=access_token_enc,
        status=status,
        last_ping=time.time(),
        created_at=time.time(),
    )


# Cookie helper functions.


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


# Verify HTTP header filtering.


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


# Verify NotebookSessionInternal storage.


class TestNotebookSessionInternal:
    """store/notebook_sessions.py: two read paths off the same row."""

    @pytest.mark.asyncio
    async def test_get_session_internal_returns_decrypted_token(self, monkeypatch):
        _patch_encryption_key(monkeypatch)

        from gateway.store.crypto import _encrypt
        from gateway.store.notebook_sessions import get_session_internal

        row = _make_session_row(access_token_enc=_encrypt("secret-token-abc"))
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = row
        mock_session.execute.return_value = mock_result

        result = await get_session_internal(
            mock_session, session_id="test-sess-123", org_id="org-1"
        )
        assert result is not None
        assert result.access_token == "secret-token-abc"
        assert result.upstream_url == "https://sbx-abc.vercel.run"
        assert result.runtime_handle == "sbx-abc"
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_session_internal_without_ciphertext_returns_no_token(self, monkeypatch):
        """Verify that missing ciphertext produces no access token.

        A null ``access_token_enc`` value produces ``access_token=None`` and no
        database write.
        """
        _patch_encryption_key(monkeypatch)

        from gateway.db.models import GatewayNotebookSession
        from gateway.store.notebook_sessions import get_session_internal

        # The model does not contain a plaintext access token column.
        assert not hasattr(GatewayNotebookSession, "access_token")

        row = _make_session_row(access_token_enc=None)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = row
        mock_session.execute.return_value = mock_result

        result = await get_session_internal(
            mock_session, session_id="test-sess-123", org_id="org-1"
        )

        assert result is not None
        assert result.access_token is None
        assert row.access_token_enc is None
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_to_info_hides_access_token(self, monkeypatch):
        """The FE-facing view exposes no token even when the row holds one."""
        _patch_encryption_key(monkeypatch)

        from gateway.store.crypto import _encrypt
        from gateway.store.notebook_sessions import get_session_by_id

        row = _make_session_row(access_token_enc=_encrypt("secret-token-abc"))
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = row
        mock_session.execute.return_value = mock_result

        result = await get_session_by_id(
            mock_session, session_id="test-sess-123", org_id="org-1"
        )
        assert result is not None
        assert not hasattr(result, "access_token")
        assert not hasattr(result, "upstream_url")

    @pytest.mark.asyncio
    async def test_to_info_notebook_url_is_proxy_path(self):
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
# The browser uses its Clerk JWT to authenticate the tokenless proxy path.
        assert result.notebook_url == "/notebook/test-sess-123/"

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


# Verify the orchestrator pod command.


class TestLaunchCredentialDelivery:
    """backends.py: the boot command and process env carry credentials safely."""

    def _launch_request(self, **overrides):
        from gateway.notebooks.backends import LaunchRequest

        kwargs = dict(
            org_id="org-1",
            user_id="user-1",
            session_id="sess-abc",
            project_id="proj-1",
            branch="main",
            session_jwt="jwt.value",
            notebook_token="pod-notebook-token",
        )
        kwargs.update(overrides)
        return LaunchRequest(**kwargs)

    def test_boot_command_never_disables_the_token(self):
        from gateway.notebooks.backends import _boot_command

        command = _boot_command(self._launch_request())
        assert "--no-token" not in command
        assert "--token-password-file" in command
        # The token itself must never appear in argv (process lists are readable).
        assert "pod-notebook-token" not in command

    def test_boot_command_includes_base_url(self):
        from gateway.notebooks.backends import _boot_command

        command = _boot_command(self._launch_request())
        assert '--base-url "/notebook/$SP_SESSION_ID"' in command

    def test_boot_command_hydrates_only_when_snapshot_given(self):
        from gateway.notebooks.backends import _boot_command

        assert "curl" not in _boot_command(self._launch_request())
        hydrated = _boot_command(self._launch_request(snapshot_url="https://s3/x.tgz"))
        assert 'curl -fsSL "$SP_SNAPSHOT_URL"' in hydrated

    @pytest.mark.asyncio
    async def test_creation_spec_env_is_empty(self, monkeypatch):
        """Creation metadata is provider-readable; secrets ride the process env."""
        from gateway.config.notebooks import NotebookSettings
        from gateway.notebooks.backends import VercelNotebookBackend

        runtime = AsyncMock()
        runtime.create.return_value = "sbx-1"
        runtime.exec.return_value = MagicMock(ok=True)
        runtime.routes.return_value = {2718: "https://sbx-1.vercel.run"}
        monkeypatch.setenv("SP_NOTEBOOK_VERCEL_IMAGE", "reg/nb:dev")
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        backend = VercelNotebookBackend(NotebookSettings(), runtime=runtime)
        await backend.launch(self._launch_request())
        spec = runtime.create.await_args.args[0]
        assert spec.env == {}
        process_env = runtime.start_process.await_args.kwargs["env"]
        assert process_env["SP_SESSION_JWT"] == "jwt.value"
        # The token rides the process env (never the creation spec); the boot
        # command stages it into the 0400 token file and unsets it before
        # exec'ing the server. No provider write_file on the critical path.
        assert process_env["SP_NOTEBOOK_TOKEN"] == "pod-notebook-token"
        runtime.write_file.assert_not_awaited()


class TestUpstreamResolution:
    """session_service.upstream_base_for: route URL + base-url path shape."""

    def test_vercel_upstream_appends_base_url_path(self):
        from gateway.notebooks.session_service import upstream_base_for
        from gateway.store.notebook_sessions import NotebookSessionInternal

        internal = NotebookSessionInternal(
            session_id="sess-1", org_id="o", user_id="u", status="running",
            backend="vercel", runtime_handle="sbx", snapshot_id=None,
            upstream_url="https://sbx.vercel.run/", access_token="t",
        )
        assert upstream_base_for(internal) == "https://sbx.vercel.run/notebook/sess-1"

    def test_direct_upstream_is_the_bare_container_url(self):
        from gateway.notebooks.session_service import upstream_base_for
        from gateway.store.notebook_sessions import NotebookSessionInternal

        internal = NotebookSessionInternal(
            session_id="sess-1", org_id="o", user_id="u", status="running",
            backend="direct", runtime_handle="local-notebook", snapshot_id=None,
            upstream_url="http://notebook:2718", access_token="t",
        )
        assert upstream_base_for(internal) == "http://notebook:2718"

    def test_missing_upstream_raises(self):
        from gateway.notebooks.session_service import (
            NotebookSessionError,
            upstream_base_for,
        )
        from gateway.store.notebook_sessions import NotebookSessionInternal

        internal = NotebookSessionInternal(
            session_id="sess-1", org_id="o", user_id="u", status="snapshotted",
            backend="vercel", runtime_handle="sbx", snapshot_id="snap",
            upstream_url=None, access_token="t",
        )
        with pytest.raises(NotebookSessionError):
            upstream_base_for(internal)


# Verify NotebookProxy HTTP behavior.


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
        outbound = _build_outbound_headers(request, None)
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
                "set-cookie": "nb_session=secret123; Path=/",
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
        result = _build_outbound_headers(request, None)
        assert "connection" not in result
        assert "upgrade" not in result
        assert "x-custom" in result

    def test_caller_authorization_is_replaced_by_the_pod_token(self):
        """The pod token is applied AFTER the strip, so it survives it."""
        from gateway.notebook_proxy.proxy import _build_outbound_headers

        request = self._make_request(
            headers={"authorization": "Bearer clerk-jwt-of-the-browser"}
        )
        result = _build_outbound_headers(request, "pod-notebook-token")
        assert result["authorization"] == "Bearer pod-notebook-token"
        assert "clerk-jwt" not in str(result)

    def test_ws_handshake_carries_the_pod_token(self):
        from gateway.notebook_proxy.proxy import _build_outbound_ws_headers

        ws = MagicMock()
        ws.headers = {
            "authorization": "Bearer clerk-jwt-of-the-browser",
            "sec-websocket-protocol": "signalpilot.auth, clerk-jwt-of-the-browser",
            "x-custom": "kept",
        }
        result = dict(_build_outbound_ws_headers(ws, "pod-notebook-token"))
        assert result["authorization"] == "Bearer pod-notebook-token"
        assert "sec-websocket-protocol" not in result
        assert result["x-custom"] == "kept"

    def test_pod_token_is_never_returned_to_the_client(self):
        """No response path can echo the credential back."""
        import httpx

        from gateway.notebook_proxy.proxy import _build_inbound_headers

        upstream = httpx.Headers(
            {
                "content-type": "text/html",
                "set-cookie": "session=pod-notebook-token; Path=/",
            }
        )
        result = _build_inbound_headers(upstream)
        assert "pod-notebook-token" not in str(result)

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


# Verify security header middleware.


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

    def test_proxy_path_omits_xframe_options(self):
        """Verify that proxy paths contain no X-Frame-Options header.

        The CSP frame-ancestors directive controls framing for notebook paths.
        X-Frame-Options cannot express the configured cross-origin allowlist.
        """
        resp = self._build_middleware_response("/notebook/abc/index.html")
        assert resp.headers.get("x-frame-options") is None

    def test_non_proxy_path_deny_xframe(self):
        resp = self._build_middleware_response("/api/something")
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_proxy_path_csp_frame_ancestors_only(self):
        resp = self._build_middleware_response("/notebook/abc/index.html")
        csp = resp.headers.get("content-security-policy", "")
        assert "frame-ancestors 'self'" in csp
        # Must NOT contain the full default-src policy
        assert "default-src" not in csp

    def test_proxy_csp_allows_configured_cross_origin_embedder(self, monkeypatch):
        """Why X-Frame-Options is omitted: the allowlist is cross-origin."""
        monkeypatch.setenv("SP_ALLOWED_ORIGINS", "https://app.signalpilot.ai")
        resp = self._build_middleware_response("/notebook/abc/index.html")
        assert "https://app.signalpilot.ai" in resp.headers.get("content-security-policy", "")

    def test_proxy_path_no_cache_control_forced(self):
        """Upstream Cache-Control passes through; no-store not forced."""
        resp = self._build_middleware_response("/notebook/abc/app.js")
        # Middleware should NOT override with no-store
        cache_control = resp.headers.get("cache-control", "")
        assert "no-store" not in cache_control

    def test_non_proxy_path_cache_control_no_store(self):
        resp = self._build_middleware_response("/api/test")
        assert resp.headers.get("cache-control") == "no-store"


# Verify the notebook URL structure.


def _arrange_proxy_session(
    monkeypatch,
    *,
    session_org_id: str | None = "org-1",
    session_user_id: str = "user-1",
    caller_user_id: str = "user-1",
    caller_org_id: str = "org-1",
    access_token: str = "tok",
):
    """Wire resolve_proxy_session's three collaborators and return the connection.

    Stubs the caller identity (resolve_user_id/resolve_org_id), the DB session
    factory, and the session row, so the test only varies who is calling and
    which org owns the session.
    """
    import contextlib

    import gateway.db.engine as engine_mod
    import gateway.notebook_proxy.auth as auth_mod
    import gateway.store.notebook_sessions as ns_mod
    from gateway.store.notebook_sessions import NotebookSessionInternal

    monkeypatch.delenv("SP_NOTEBOOK_DIRECT_URL", raising=False)

    internal = NotebookSessionInternal(
        session_id="sess-123",
        org_id=session_org_id,
        user_id=session_user_id,
        status="running",
        backend="vercel",
        runtime_handle="sbx-abc",
        upstream_url="https://sbx-abc.vercel.run",
        snapshot_id=None,
        access_token=access_token,
    )
    monkeypatch.setattr(ns_mod, "get_session_internal", AsyncMock(return_value=internal))

    @contextlib.asynccontextmanager
    async def _factory():
        yield AsyncMock()

    monkeypatch.setattr(engine_mod, "get_session_factory", lambda: _factory)

    async def _fake_user(conn):
        return caller_user_id

    async def _fake_org(conn, uid):
        return caller_org_id

    monkeypatch.setattr(auth_mod, "resolve_user_id", _fake_user)
    monkeypatch.setattr(auth_mod, "resolve_org_id", _fake_org)

    connection = MagicMock()
    connection.scope = {"type": "http"}
    connection.headers = {}
    connection.cookies = {}
    connection.state = MagicMock()
    connection.state.auth = None
    return connection


class TestProxyUsesRouteUrl:
    """Upstream is the sandbox's public route URL + the session base path."""

    @pytest.mark.asyncio
    async def test_upstream_base_is_route_url_with_session_path(self, monkeypatch):
        from gateway.notebook_proxy.auth import resolve_proxy_session

        connection = _arrange_proxy_session(monkeypatch)
        result = await resolve_proxy_session(connection, "sess-123")
        assert result.upstream_base == "https://sbx-abc.vercel.run/notebook/sess-123"


# Verify active organization authorization.


class TestProxyActiveOrgAuthorization:
    """auth.py: the caller's ACTIVE org must own the session, not just the user.

    resolve_proxy_session is the sanctioned RequireScope bypass, so it has to do
    the whole authorization itself. user_id alone survives an org switch and
    survives losing membership of the owning org.
    """

    @pytest.mark.asyncio
    async def test_same_user_active_in_other_org_is_refused(self, monkeypatch):
        """Session created in org A; the same user, now active in org B, is out."""
        from fastapi import HTTPException

        from gateway.notebook_proxy.auth import resolve_proxy_session

        connection = _arrange_proxy_session(
            monkeypatch, session_org_id="org-a", caller_org_id="org-b"
        )
        with pytest.raises(HTTPException) as exc_info:
            await resolve_proxy_session(connection, "sess-123")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_same_user_active_in_owning_org_is_allowed(self, monkeypatch):
        """Control for the test above: back in org A the same session resolves."""
        from gateway.notebook_proxy.auth import resolve_proxy_session

        connection = _arrange_proxy_session(
            monkeypatch, session_org_id="org-a", caller_org_id="org-a"
        )
        result = await resolve_proxy_session(connection, "sess-123")
        assert result.org_id == "org-a"

    @pytest.mark.asyncio
    async def test_user_removed_from_owning_org_is_refused(self, monkeypatch):
        """Verify denial when the JWT does not name organization A as active."""
        from fastapi import HTTPException

        from gateway.notebook_proxy.auth import resolve_proxy_session

        connection = _arrange_proxy_session(
            monkeypatch,
            session_org_id="org-a",
            caller_org_id="org-personal",
        )
        with pytest.raises(HTTPException) as exc_info:
            await resolve_proxy_session(connection, "sess-123")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cross_user_same_org_still_refused(self, monkeypatch):
        """The org check does not weaken the ownership check."""
        from fastapi import HTTPException

        from gateway.notebook_proxy.auth import resolve_proxy_session

        connection = _arrange_proxy_session(
            monkeypatch, session_user_id="user-1", caller_user_id="user-2"
        )
        with pytest.raises(HTTPException) as exc_info:
            await resolve_proxy_session(connection, "sess-123")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_session_without_org_is_refused_in_a_real_org(self, monkeypatch):
        """Verify that a cloud organization cannot access an unscoped session."""
        from fastapi import HTTPException

        from gateway.notebook_proxy.auth import resolve_proxy_session

        connection = _arrange_proxy_session(
            monkeypatch, session_org_id=None, caller_org_id="org-a"
        )
        with pytest.raises(HTTPException) as exc_info:
            await resolve_proxy_session(connection, "sess-123")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_local_mode_org_still_resolves(self, monkeypatch):
        """Local mode: both sides are "local", so the check is a no-op there."""
        from gateway.notebook_proxy.auth import resolve_proxy_session

        connection = _arrange_proxy_session(
            monkeypatch, session_org_id="local", caller_org_id="local"
        )
        result = await resolve_proxy_session(connection, "sess-123")
        assert result.org_id == "local"

    @pytest.mark.asyncio
    async def test_missing_upstream_token_is_503(self, monkeypatch):
        """Verify that a missing pod credential denies access."""
        from fastapi import HTTPException

        from gateway.notebook_proxy.auth import resolve_proxy_session

        connection = _arrange_proxy_session(monkeypatch, access_token=None)
        with pytest.raises(HTTPException) as exc_info:
            await resolve_proxy_session(connection, "sess-123")
        assert exc_info.value.status_code == 503




# Verify session ownership in API endpoints.


class TestSessionOwnershipCheck:
    """Verify that organization peers cannot access another user's session."""

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
        Response()

        with pytest.raises(HTTPException) as exc_info:
            await ns_api_mod.delete_session_by_id("sess-owned", store)
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


# Verify HTTPConnection support in resolve_proxy_session.


class TestWsQueryValidation:
    """Verify WebSocket query validation before forwarding."""

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




class TestCspPathGateExact:
    """Verify relaxed CSP only for the exact notebook path structure."""

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


# Verify that error logs exclude pod IP addresses.


class TestProxyErrorLogScrubbing:
    """Verify that upstream connection warnings exclude pod IP addresses."""

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


# Verify session identifier validation in API endpoints.


class TestSessionIdValidationOnApiEndpoints:
    """Verify session identifiers on get, delete, and ping endpoints."""

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
            await ns_api_mod.delete_session_by_id("bad\r\nid", store)
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





class TestLegacyCollectionPingRemoved:
    """Verify that the collection ping route rejects POST requests.

    The per-session route requires a session identifier and returns status 404
    when the caller does not own the session.
    """

    def _routes(self) -> set[tuple[str, frozenset]]:
        from gateway.api import notebook_sessions as ns_api_mod

        return {
            (route.path, frozenset(route.methods))
            for route in ns_api_mod.router.routes
        }

    def test_per_session_ping_is_registered(self) -> None:
        assert (
            "/api/notebook-sessions/{session_id}/ping",
            frozenset({"POST"}),
        ) in self._routes()

    def test_legacy_collection_ping_is_not_registered(self) -> None:
        paths = {path for path, _ in self._routes()}
        assert "/api/notebook-sessions/ping" not in paths

    def test_legacy_collection_ping_is_rejected(self) -> None:
        """Verify that POST to the collection path returns status 405.

        The request does not extend a session lifetime.
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from gateway.api import notebook_sessions as ns_api_mod

        app = FastAPI()
        app.include_router(ns_api_mod.router)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/api/notebook-sessions/ping")

        assert resp.status_code == 405
        assert not resp.is_success
