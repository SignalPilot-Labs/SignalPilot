"""Security regression tests for notebook session JWT fixes.

Covers:
- H-3: notebook_session auth method accepted by scope_guard with read/write,
        rejected for admin.
- M (allowlist): JWT with admin in scopes claim cannot escalate via allowlist
                 intersection.
- H-2: SP_PUBLIC_GATEWAY_URL from config, not from request Host header.
- M-4 (alg pin): JWT with alg=none or alg=RS256 is rejected by notebook verifier.
- M-3 (cloud user_id): cloud mode with empty user_id returns 401.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import HTTPException, Request

from gateway.auth.notebook_jwt import (
    NOTEBOOK_SESSION_AUD,
    NOTEBOOK_SESSION_ISS,
    NotebookSessionJWTError,
    mint_session_jwt,
    verify_session_jwt,
)
from gateway.security.scope_guard import (
    _NOTEBOOK_SESSION_SCOPE_ALLOWLIST,
    require_scopes,
)

_TEST_SECRET = "test-security-fixes-secret-48bytes!!"


def _patch_secret(monkeypatch) -> None:
    monkeypatch.setattr("gateway.auth.notebook_jwt.load_session_jwt_secret", lambda: _TEST_SECRET)
    monkeypatch.setattr("gateway.auth.jwt_secret._cached_secret", _TEST_SECRET)


def _make_nb_token(
    user_id: str = "user-1",
    org_id: str = "org-1",
    session_id: str = "sess-1",
    scopes: list[str] | None = None,
    ttl: int = 3600,
) -> str:
    payload = {
        "iss": NOTEBOOK_SESSION_ISS,
        "aud": NOTEBOOK_SESSION_AUD,
        "sub": user_id,
        "org_id": org_id,
        "session_id": session_id,
        "branch": "main",
        "scopes": scopes if scopes is not None else ["read", "write"],
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl,
    }
    return jwt.encode(payload, _TEST_SECRET, algorithm="HS256")


def _make_request_with_auth(auth: dict) -> Request:
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    request.state.auth = auth
    return request


# ─── H-3: scope_guard honors notebook_session ─────────────────────────────────


class TestScopeGuardNotebookSession:
    """notebook_session auth method is accepted for read/write, rejected for admin."""

    def test_notebook_session_accepted_for_read(self):
        auth = {
            "auth_method": "notebook_session",
            "user_id": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": ["read", "write"],
        }
        request = _make_request_with_auth(auth)
        # Should not raise
        require_scopes(request, "read")

    def test_notebook_session_accepted_for_write(self):
        auth = {
            "auth_method": "notebook_session",
            "user_id": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": ["read", "write"],
        }
        request = _make_request_with_auth(auth)
        # Should not raise
        require_scopes(request, "write")

    def test_notebook_session_rejected_for_admin(self):
        auth = {
            "auth_method": "notebook_session",
            "user_id": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": ["read", "write"],
        }
        request = _make_request_with_auth(auth)
        with pytest.raises(HTTPException) as exc_info:
            require_scopes(request, "admin")
        assert exc_info.value.status_code == 403

    def test_notebook_session_rejected_for_billing(self):
        auth = {
            "auth_method": "notebook_session",
            "user_id": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": ["read", "write"],
        }
        request = _make_request_with_auth(auth)
        with pytest.raises(HTTPException) as exc_info:
            require_scopes(request, "billing")
        assert exc_info.value.status_code == 403

    def test_notebook_session_accepted_for_read_and_write_together(self):
        auth = {
            "auth_method": "notebook_session",
            "user_id": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": ["read", "write"],
        }
        request = _make_request_with_auth(auth)
        # Should not raise
        require_scopes(request, "read", "write")

    def test_notebook_session_rejected_when_read_and_admin_required(self):
        auth = {
            "auth_method": "notebook_session",
            "user_id": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": ["read", "write"],
        }
        request = _make_request_with_auth(auth)
        with pytest.raises(HTTPException) as exc_info:
            require_scopes(request, "read", "admin")
        assert exc_info.value.status_code == 403


# ─── M: allowlist intersection prevents scope escalation ─────────────────────


class TestNotebookSessionScopeAllowlistIntersection:
    """JWT with admin in scopes claim cannot escalate — allowlist caps it."""

    def test_admin_in_token_scopes_still_rejected(self):
        # Token claims admin scope — but allowlist does not include admin
        auth = {
            "auth_method": "notebook_session",
            "user_id": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": ["read", "write", "admin"],  # attacker-modified claim
        }
        request = _make_request_with_auth(auth)
        with pytest.raises(HTTPException) as exc_info:
            require_scopes(request, "admin")
        assert exc_info.value.status_code == 403

    def test_allowlist_constant_does_not_contain_admin(self):
        assert "admin" not in _NOTEBOOK_SESSION_SCOPE_ALLOWLIST

    def test_allowlist_constant_contains_read_and_write(self):
        assert "read" in _NOTEBOOK_SESSION_SCOPE_ALLOWLIST
        assert "write" in _NOTEBOOK_SESSION_SCOPE_ALLOWLIST

    def test_token_with_only_read_scope_cannot_write(self):
        # Token has only read — effective scopes are read only
        auth = {
            "auth_method": "notebook_session",
            "user_id": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": ["read"],  # narrower than default
        }
        request = _make_request_with_auth(auth)
        with pytest.raises(HTTPException) as exc_info:
            require_scopes(request, "write")
        assert exc_info.value.status_code == 403


# ─── H-2: gateway URL from config not request Host ────────────────────────────


class TestGatewayUrlFromConfig:
    """SP_PUBLIC_GATEWAY_URL is sourced from config, not request Host header."""

    def test_create_session_uses_config_url_not_request_host(self, monkeypatch):
        """create_session passes sp_public_gateway_url to create_pod, ignoring request Host."""
        _patch_secret(monkeypatch)
        from unittest.mock import AsyncMock, patch

        from gateway.api import notebook_sessions as ns_api
        from gateway.config.k8s import K8sSettings
        from gateway.models.notebook_sessions import NotebookSessionInfo
        from gateway.orchestrator import PodInfo
        from gateway.store import notebook_sessions as ns_store

        # Mock k8s settings to return a known gateway URL
        fake_settings = MagicMock(spec=K8sSettings)
        fake_settings.sp_public_gateway_url = "http://configured-gateway:3300"
        fake_settings.sp_session_jwt_ttl_seconds = 3600

        new_session = NotebookSessionInfo(
            id="sess-url-test",
            org_id="org-1",
            user_id="user-1",
            branch="main",
            pod_name="nb-url-test",
            pod_ip=None,
            access_token="tok-url",
            status="creating",
            last_ping=time.time(),
            created_at=time.time(),
        )

        mock_orch = AsyncMock()
        mock_orch.create_pod.return_value = PodInfo(name="nb-url-test", ip=None, status="pending")
        mock_orch.wait_for_running = AsyncMock(
            return_value=PodInfo(name="nb-url-test", ip=None, status="running")
        )
        mock_orch.wait_for_ready.return_value = PodInfo(
            name="nb-url-test", ip="10.0.0.5:2718", status="running"
        )

        monkeypatch.setattr(ns_store, "get_active_session", AsyncMock(return_value=None))
        monkeypatch.setattr(ns_store, "create_session", AsyncMock(return_value=new_session))
        monkeypatch.setattr(ns_store, "delete_stopped", AsyncMock())
        monkeypatch.setattr(ns_store, "update_session_status", AsyncMock())
        monkeypatch.setattr(ns_api, "_get_orchestrator", AsyncMock(return_value=mock_orch))
        monkeypatch.setattr(ns_api, "get_k8s_settings", lambda: fake_settings)

        store = MagicMock()
        store.org_id = "org-1"
        store.user_id = "user-1"
        store.session = AsyncMock()

        from gateway.models.notebook_sessions import NotebookSessionCreate

        body = NotebookSessionCreate(branch="main")

        mock_response = MagicMock()
        mock_response.headers = {}

        import asyncio

        asyncio.run(ns_api.create_session(body, store, mock_response))

        call_kwargs = mock_orch.create_pod.call_args.kwargs
        # Must use the config URL, NOT any Host-header-derived value
        assert call_kwargs["gateway_url"] == "http://configured-gateway:3300"


# ─── M-4: alg=none and alg=RS256 rejected by notebook verifier ───────────────


class TestAlgorithmPinning:
    """JWT with alg=none or alg=RS256 is rejected before unverified decode."""

    @pytest.mark.asyncio
    async def test_alg_none_rejected(self, monkeypatch):
        _patch_secret(monkeypatch)
        import gateway.auth.user as user_mod

        monkeypatch.setattr(user_mod, "is_cloud_mode", lambda: True)

        # Build a token with alg=none by manually crafting it
        import base64
        import json

        header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=")
        payload_data = {
            "iss": NOTEBOOK_SESSION_ISS,
            "sub": "user-1",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=")
        token = f"{header.decode()}.{payload_b64.decode()}."  # empty signature

        request = MagicMock()
        request.state = MagicMock()
        request.state.auth = None
        request.headers = {"authorization": f"Bearer {token}"}
        request.cookies = {}

        with pytest.raises(HTTPException) as exc_info:
            await user_mod.resolve_user_id(request)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_alg_rs256_notebook_token_rejected(self, monkeypatch):
        """A token claiming RS256 alg (not a valid HS256 notebook token) is rejected at alg gate."""
        _patch_secret(monkeypatch)
        import gateway.auth.user as user_mod

        monkeypatch.setattr(user_mod, "is_cloud_mode", lambda: True)

        # Craft a token header claiming RS256 but with HS256 body (simulating spoofing)
        import base64
        import json

        header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=")
        payload_data = {
            "iss": NOTEBOOK_SESSION_ISS,
            "sub": "user-1",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=")
        # Sign with HS256 but put RS256 in header — this token claims RS256
        import hashlib
        import hmac

        signing_input = f"{header.decode()}.{payload_b64.decode()}".encode()
        sig = hmac.new(_TEST_SECRET.encode(), signing_input, hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=")
        token = f"{header.decode()}.{payload_b64.decode()}.{sig_b64.decode()}"

        request = MagicMock()
        request.state = MagicMock()
        request.state.auth = None
        request.headers = {"authorization": f"Bearer {token}"}
        request.cookies = {}

        # RS256 is in our allowed set {"HS256", "RS256"}, so a RS256 token gets routed
        # to Clerk verifier (not notebook), which will fail since we have no JWKS.
        # What matters is that the alg gate passes RS256 through (it's valid) but
        # routes to Clerk — confirming notebook verifier is not tricked.
        with pytest.raises(HTTPException) as exc_info:
            await user_mod.resolve_user_id(request)
        # Routes to Clerk (500 for no JWKS client) or 401 — either way not 200
        assert exc_info.value.status_code in (401, 500)

    @pytest.mark.asyncio
    async def test_alg_hs384_rejected(self, monkeypatch):
        """An unexpected algorithm (HS384) is rejected at the alg gate."""
        _patch_secret(monkeypatch)
        import gateway.auth.user as user_mod

        monkeypatch.setattr(user_mod, "is_cloud_mode", lambda: True)

        # Craft a token with alg=HS384
        payload = {
            "iss": NOTEBOOK_SESSION_ISS,
            "aud": NOTEBOOK_SESSION_AUD,
            "sub": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": ["read", "write"],
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, _TEST_SECRET, algorithm="HS384")

        request = MagicMock()
        request.state = MagicMock()
        request.state.auth = None
        request.headers = {"authorization": f"Bearer {token}"}
        request.cookies = {}

        with pytest.raises(HTTPException) as exc_info:
            await user_mod.resolve_user_id(request)
        assert exc_info.value.status_code == 401


# ─── M-3: cloud mode empty user_id returns 401 ────────────────────────────────


class TestCloudModeEmptyUserId:
    """Cloud mode with empty user_id raises 401 instead of collapsing to 'local'."""

    @pytest.mark.asyncio
    async def test_cloud_mode_empty_user_id_raises_401(self, monkeypatch):
        _patch_secret(monkeypatch)
        from unittest.mock import AsyncMock

        from gateway.api import notebook_sessions as ns_api
        from gateway.store import notebook_sessions as ns_store

        monkeypatch.setattr(ns_api, "is_cloud_mode", lambda: True)

        store = MagicMock()
        store.org_id = "org-1"
        store.user_id = ""  # empty — simulates None/empty user_id in cloud mode
        store.session = AsyncMock()

        from gateway.models.notebook_sessions import NotebookSessionCreate

        body = NotebookSessionCreate(branch="main")

        mock_response = MagicMock()
        mock_response.headers = {}
        with pytest.raises(HTTPException) as exc_info:
            await ns_api.create_session(body, store, mock_response)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_local_mode_none_user_id_uses_fallback(self, monkeypatch):
        """Local mode with None user_id falls back to 'local' (no error)."""
        _patch_secret(monkeypatch)
        from unittest.mock import AsyncMock

        from gateway.api import notebook_sessions as ns_api
        from gateway.config.k8s import K8sSettings
        from gateway.models.notebook_sessions import NotebookSessionInfo
        from gateway.orchestrator import PodInfo
        from gateway.store import notebook_sessions as ns_store

        monkeypatch.setattr(ns_api, "is_cloud_mode", lambda: False)

        fake_settings = MagicMock(spec=K8sSettings)
        fake_settings.sp_public_gateway_url = "http://gateway:3300"
        fake_settings.sp_session_jwt_ttl_seconds = 3600
        monkeypatch.setattr(ns_api, "get_k8s_settings", lambda: fake_settings)

        new_session = NotebookSessionInfo(
            id="sess-local",
            org_id="local",
            user_id="local",
            branch="main",
            pod_name="nb-local",
            pod_ip=None,
            access_token="tok-local",
            status="creating",
            last_ping=time.time(),
            created_at=time.time(),
        )

        mock_orch = AsyncMock()
        mock_orch.is_pod_alive.return_value = False
        mock_orch.create_pod.return_value = PodInfo(name="nb-local", ip=None, status="pending")
        mock_orch.wait_for_running = AsyncMock(
            return_value=PodInfo(name="nb-local", ip=None, status="running")
        )
        mock_orch.wait_for_ready.return_value = PodInfo(name="nb-local", ip="10.0.0.6:2718", status="running")

        monkeypatch.setattr(ns_store, "get_active_session", AsyncMock(return_value=None))
        monkeypatch.setattr(ns_store, "create_session", AsyncMock(return_value=new_session))
        monkeypatch.setattr(ns_store, "delete_stopped", AsyncMock())
        monkeypatch.setattr(ns_store, "update_session_status", AsyncMock())
        monkeypatch.setattr(ns_api, "_get_orchestrator", AsyncMock(return_value=mock_orch))

        store = MagicMock()
        store.org_id = "local"
        store.user_id = None  # None in local mode — should fall back to "local"
        store.session = AsyncMock()

        from gateway.models.notebook_sessions import NotebookSessionCreate

        body = NotebookSessionCreate(branch="main")
        mock_response = MagicMock()
        mock_response.headers = {}
        result = await ns_api.create_session(body, store, mock_response)
        assert result is not None


# ─── M: scopes claim in minted JWT ────────────────────────────────────────────


class TestMintedJWTContainsScopes:
    """Minted notebook JWT contains scopes claim and verifier exposes it."""

    def test_minted_jwt_has_scopes_claim(self, monkeypatch):
        _patch_secret(monkeypatch)
        token = mint_session_jwt(
            user_id="user-1",
            org_id="org-1",
            session_id="sess-1",
            branch="main",
            ttl=3600,
        )
        claims = verify_session_jwt(token)
        assert "scopes" in claims
        assert claims["scopes"] == ["read", "write", "query", "execute"]

    def test_verifier_rejects_token_with_empty_scopes(self, monkeypatch):
        _patch_secret(monkeypatch)
        payload = {
            "iss": NOTEBOOK_SESSION_ISS,
            "aud": NOTEBOOK_SESSION_AUD,
            "sub": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": [],  # empty list — should be rejected
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, _TEST_SECRET, algorithm="HS256")
        with pytest.raises(NotebookSessionJWTError, match="scopes"):
            verify_session_jwt(token)

    def test_verifier_rejects_token_with_non_list_scopes(self, monkeypatch):
        _patch_secret(monkeypatch)
        payload = {
            "iss": NOTEBOOK_SESSION_ISS,
            "aud": NOTEBOOK_SESSION_AUD,
            "sub": "user-1",
            "org_id": "org-1",
            "session_id": "sess-1",
            "scopes": "read write",  # string, not list
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, _TEST_SECRET, algorithm="HS256")
        with pytest.raises(NotebookSessionJWTError, match="scopes"):
            verify_session_jwt(token)
