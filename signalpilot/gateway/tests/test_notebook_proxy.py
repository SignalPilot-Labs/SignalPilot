"""Tests for the notebook reverse proxy — §3.14 of the R2 spec.

Covers:
- Proxy HTTP/WS: header stripping (cookie/authorization/set-cookie/hop-by-hop)
- Security headers: CSP, X-Frame-Options, Cache-Control on proxy paths
- Session shape: tokenless notebook_url, access_token None
- Session ownership: cross-user/cross-org 404 on API endpoints
- Orchestrator: pod CLI --no-token, no SP_ACCESS_TOKEN, fail-fast upstream mode
- Upstream mode: pod_ip_internal used (not NodePort)

Proxy auth itself (Clerk JWT / local) is covered end-to-end by the live
run_notebook test; the removed unit cases tested the retired cookie/_init model.
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


# ─── Helpers ─────────────────────────────────────────────────────────────────


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
    async def test_get_session_internal_returns_decrypted_token(self, monkeypatch):
        _patch_encryption_key(monkeypatch)

        from gateway.store.crypto import _encrypt
        from gateway.store.notebook_sessions import get_session_internal

        row = _make_session_row(access_token=None)
        row.access_token_enc = _encrypt("secret-token-abc")
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
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_session_internal_migrates_legacy_plaintext_token(self, monkeypatch):
        _patch_encryption_key(monkeypatch)

        from gateway.store.crypto import _decrypt_with_migration
        from gateway.store.notebook_sessions import get_session_internal

        row = _make_session_row(access_token="legacy-token")
        assert row.access_token_enc is None
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = row
        mock_session.execute.return_value = mock_result

        result = await get_session_internal(
            mock_session, session_id="test-sess-123", org_id="org-1"
        )

        assert result is not None
        assert result.access_token == "legacy-token"
        assert row.access_token is None
        assert row.access_token_enc is not None
        assert b"legacy-token" not in row.access_token_enc
        token, needs_migration = _decrypt_with_migration(row.access_token_enc)
        assert token == "legacy-token"
        assert needs_migration is False
        mock_session.commit.assert_awaited_once()

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
        # Tokenless proxy path — the browser authenticates with its Clerk JWT.
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
        # R4: command is now ["sh", "-c", "...sentinel shim..."]
        command = manifest["spec"]["containers"][0]["command"]
        assert command[0] == "sh"
        assert command[1] == "-c"
        cmd_str = command[2]
        assert "--no-token" in cmd_str
        assert "--token-password" not in cmd_str

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
        # R4: command is now ["sh", "-c", "...sentinel shim..."]
        command = manifest["spec"]["containers"][0]["command"]
        assert command[0] == "sh"
        assert command[1] == "-c"
        cmd_str = command[2]
        assert "--no-token" in cmd_str
        assert "--token-password" not in cmd_str

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
        # R4: command is ["sh", "-c", "...sentinel shim...exec sp edit ...--base-url /notebook/{sid}..."]
        command = manifest["spec"]["containers"][0]["command"]
        assert command[0] == "sh"
        assert command[1] == "-c"
        cmd_str = command[2]
        assert "--base-url" in cmd_str
        assert "/notebook/sess-abc" in cmd_str

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


# ─── H-1/R3: NodePort fully retired — KubernetesOrchestrator only accepts pod_ip ─


class TestNodePortServiceGating:
    """R3: NodePort is fully retired from KubernetesOrchestrator.

    The constructor now refuses any SP_NOTEBOOK_UPSTREAM_MODE other than pod_ip.
    Services are never created. ResourceQuota services=0 enforces this at the
    K8s API layer too.
    """

    @pytest.mark.asyncio
    async def test_pod_ip_mode_does_not_create_nodeport_service(self, monkeypatch):
        """In pod_ip mode, create_pod must NOT call create_namespaced_service."""
        import sys

        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        sys.modules.pop("gateway.orchestrator.kubernetes", None)

        import importlib

        from unittest.mock import patch

        mod = importlib.import_module("gateway.orchestrator.kubernetes")
        orch = mod.KubernetesOrchestrator()

        core_api = AsyncMock()
        core_api.create_namespaced_pod = AsyncMock()
        core_api.create_namespaced_service = AsyncMock()
        orch._core_api = core_api
        orch._networking_api = MagicMock()
        orch._rbac_api = MagicMock()
        orch._client = MagicMock()
        orch._namespace_prefix = "sp-nb"
        orch._gateway_namespace = "signalpilot"
        orch._gateway_pod_selector = {"app": "signalpilot-gateway"}
        orch._gateway_port = 3300
        orch._egress_cidr = None
        orch._gateway_service_account = "signalpilot-gateway"

        with patch("gateway.orchestrator.kubernetes.ensure_org_namespace", AsyncMock()):
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

    def test_nodeport_mode_constructor_raises_runtime_error(self, monkeypatch):
        """R3: KubernetesOrchestrator constructor raises if SP_NOTEBOOK_UPSTREAM_MODE=nodeport.

        NodePort was retired in R3. The constructor now refuses it immediately
        rather than failing at create_pod — no dead branches remain in the class.
        """
        import sys

        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "nodeport")
        sys.modules.pop("gateway.orchestrator.kubernetes", None)

        import importlib

        mod = importlib.import_module("gateway.orchestrator.kubernetes")

        with pytest.raises(RuntimeError, match="pod_ip"):
            mod.KubernetesOrchestrator()

    def test_nodeport_mode_in_cloud_constructor_raises(self, monkeypatch):
        """R3: nodeport mode is rejected at constructor time, regardless of deployment mode."""
        import sys

        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "nodeport")
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        sys.modules.pop("gateway.orchestrator.kubernetes", None)

        import importlib

        mod = importlib.import_module("gateway.orchestrator.kubernetes")

        with pytest.raises(RuntimeError, match="pod_ip"):
            mod.KubernetesOrchestrator()


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



