"""Integration tests for notebook session endpoints and related auth dispatch.

Tests:
- Cross-org GET/DELETE return 404.
- Notebook-session JWT accepted on inbound requests.
- Clerk-shaped JWT not accepted by notebook-session verifier.
- Notebook-session JWT not accepted by Clerk verifier.
- sp_-prefixed local API key still authenticates end-to-end.
- Pod spec contains SP_SESSION_JWT and NOT SP_API_KEY in cloud mode.
- Session reuse when pod alive; recreate when pod dead.
- Direct store get_session_by_id cross-org returns None.
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
import pytest_asyncio
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from gateway.auth.notebook_jwt import (
    NOTEBOOK_SESSION_AUD,
    NOTEBOOK_SESSION_ISS,
    mint_session_jwt,
    verify_session_jwt,
)

_TEST_SECRET = "integration-test-secret-32-bytes!!"

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _patch_jwt_secret(monkeypatch):
    monkeypatch.setattr("gateway.auth.notebook_jwt.load_session_jwt_secret", lambda: _TEST_SECRET)
    monkeypatch.setattr("gateway.auth.jwt_secret._cached_secret", _TEST_SECRET)


def _make_nb_jwt(user_id: str, org_id: str, session_id: str, ttl: int = 3600, scopes: list | None = None) -> str:
    payload = {
        "iss": NOTEBOOK_SESSION_ISS,
        "aud": NOTEBOOK_SESSION_AUD,
        "sub": user_id,
        "org_id": org_id,
        "session_id": session_id,
        "project_id": "proj-1",
        "branch": "main",
        "scopes": scopes if scopes is not None else ["read", "write"],
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl,
    }
    return jwt.encode(payload, _TEST_SECRET, algorithm="HS256")


def _make_clerk_jwt(user_id: str = "clerk-user", org_id: str = "clerk-org") -> str:
    """Mint a fake Clerk-shaped JWT (RS256 shape but signed with HS256 for testing)."""
    payload = {
        "iss": "https://clerk.example.com",
        "sub": user_id,
        "org_id": org_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, "clerk-secret", algorithm="HS256")


# ─── Store-level test ─────────────────────────────────────────────────────────


class TestStoreGetSessionByIdCrossOrg:
    """Direct store-level: cross-org lookup returns None."""

    @pytest.mark.asyncio
    async def test_cross_org_returns_none(self):
        """get_session_by_id with wrong org_id returns None without revealing existence."""
        from gateway.store.notebook_sessions import get_session_by_id

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await get_session_by_id(mock_session, session_id="some-id", org_id="wrong-org")
        assert result is None

    @pytest.mark.asyncio
    async def test_same_org_returns_session(self):
        """get_session_by_id with correct org returns the session."""
        import time

        from gateway.db.models import GatewayNotebookSession
        from gateway.store.notebook_sessions import get_session_by_id

        row = GatewayNotebookSession(
            id="sess-abc",
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            pod_name="nb-test",
            pod_ip=None,
            access_token="token-abc",
            status="running",
            last_ping=time.time(),
            created_at=time.time(),
        )
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = row
        mock_session.execute.return_value = mock_result

        result = await get_session_by_id(mock_session, session_id="sess-abc", org_id="org-1")
        assert result is not None
        assert result.id == "sess-abc"
        assert result.org_id == "org-1"


# ─── JWT dispatch tests ───────────────────────────────────────────────────────


class TestNotebookJWTVerifierDispatch:
    """auth/user.py dispatch: iss-based routing."""

    @pytest.mark.asyncio
    async def test_notebook_session_jwt_accepted(self, monkeypatch):
        """A notebook-session JWT routes to verify_session_jwt and succeeds."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        monkeypatch.delenv("CLERK_PUBLISHABLE_KEY", raising=False)
        _patch_jwt_secret(monkeypatch)

        # Reimport to pick up monkeypatched mode
        import importlib

        import gateway.auth.user as user_mod
        import gateway.runtime.mode as mode_mod

        monkeypatch.setattr(mode_mod, "is_cloud_mode", lambda: True)
        monkeypatch.setattr(user_mod, "is_cloud_mode", lambda: True)

        token = _make_nb_jwt("user-a", "org-a", "sess-xyz")

        request = MagicMock()
        request.state = MagicMock()
        request.state.auth = None
        request.headers = {"authorization": f"Bearer {token}"}
        request.cookies = {}

        user_id = await user_mod.resolve_user_id(request)
        assert user_id == "user-a"
        assert request.state.auth["auth_method"] == "notebook_session"
        assert request.state.auth["org_id"] == "org-a"
        assert request.state.auth["session_id"] == "sess-xyz"

    @pytest.mark.asyncio
    async def test_clerk_shaped_jwt_not_routed_to_notebook_verifier(self, monkeypatch):
        """A Clerk-shaped JWT (different iss) is NOT sent to notebook-session verifier."""
        _patch_jwt_secret(monkeypatch)

        import gateway.auth.user as user_mod

        monkeypatch.setattr(user_mod, "is_cloud_mode", lambda: True)

        clerk_token = _make_clerk_jwt()
        # Notebook verifier should never be called
        verify_called = []

        def _fake_verify(token):
            verify_called.append(token)
            raise Exception("Should not be called")

        monkeypatch.setattr(user_mod, "verify_session_jwt", _fake_verify)

        request = MagicMock()
        request.state = MagicMock()
        request.state.auth = None
        request.headers = {"authorization": f"Bearer {clerk_token}"}
        request.cookies = {}

        # Should attempt Clerk path (which will fail since no JWKS client in test)
        with pytest.raises(HTTPException) as exc_info:
            await user_mod.resolve_user_id(request)
        assert exc_info.value.status_code in (401, 500)
        assert len(verify_called) == 0

    @pytest.mark.asyncio
    async def test_notebook_jwt_with_clerk_iss_rejected_by_nb_verifier(self, monkeypatch):
        """A token claiming Clerk iss (but signed with nb key) is routed to Clerk verifier, fails."""
        _patch_jwt_secret(monkeypatch)

        import gateway.auth.user as user_mod

        monkeypatch.setattr(user_mod, "is_cloud_mode", lambda: True)

        # Token has Clerk iss but is signed with our HS256 secret
        payload = {
            "iss": "https://clerk.example.com",
            "sub": "user-1",
            "org_id": "org-1",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, _TEST_SECRET, algorithm="HS256")

        request = MagicMock()
        request.state = MagicMock()
        request.state.auth = None
        request.headers = {"authorization": f"Bearer {token}"}
        request.cookies = {}

        # Routed to Clerk verifier (which will fail — wrong alg/no JWKS)
        with pytest.raises(HTTPException) as exc_info:
            await user_mod.resolve_user_id(request)
        assert exc_info.value.status_code in (401, 500)

    @pytest.mark.asyncio
    async def test_sp_prefix_short_circuits_no_jwt_decode(self, monkeypatch):
        """sp_-prefixed bearer token hits local API key path, never attempts JWT decode."""
        import gateway.auth.user as user_mod

        monkeypatch.setattr(user_mod, "is_cloud_mode", lambda: False)

        decode_called = []
        original_decode = jwt.decode

        def _spy_decode(*args, **kwargs):
            decode_called.append(True)
            return original_decode(*args, **kwargs)

        monkeypatch.setattr(jwt, "decode", _spy_decode)

        request = MagicMock()
        request.state = MagicMock()
        # auth state already set by APIKeyAuthMiddleware for local API key
        request.state.auth = {
            "auth_method": "api_key",
            "user_id": "local-user",
            "org_id": "local",
            "scopes": ["read", "write"],
        }
        request.headers = {"authorization": "Bearer sp_test_key_abc123"}
        request.cookies = {}

        # auth_state is already set so resolve_user_id short-circuits at step 1
        user_id = await user_mod.resolve_user_id(request)
        assert user_id == "local-user"
        assert len(decode_called) == 0


# ─── HTTP integration tests ───────────────────────────────────────────────────


def _make_mock_store(org_id: str = "org-1", user_id: str = "user-1") -> AsyncMock:
    store = AsyncMock()
    store.org_id = org_id
    store.user_id = user_id
    store.session = AsyncMock()
    return store


def _build_app_client(monkeypatch, org_id: str = "org-1", user_id: str = "user-1"):
    """Build a TestClient with mocked auth returning (org_id, user_id)."""
    from gateway.api.deps import get_store
    from gateway.auth import resolve_org_id, resolve_user_id
    from gateway.main import app

    async def _fake_user_id(request: Request) -> str:
        return user_id

    async def _fake_org_id(request: Request, _user_id) -> str:
        return org_id

    async def _fake_store() -> AsyncMock:
        return _make_mock_store(org_id=org_id, user_id=user_id)

    app.dependency_overrides[resolve_user_id] = _fake_user_id
    app.dependency_overrides[resolve_org_id] = _fake_org_id
    app.dependency_overrides[get_store] = _fake_store

    return app


_APP_PATCHES = [
    patch("gateway.main.init_db", new_callable=AsyncMock),
    patch("gateway.main.close_db", new_callable=AsyncMock),
    patch("gateway.main.get_session_factory", return_value=AsyncMock()),
    patch("gateway.main._mcp_session_manager", None),
    patch("gateway.connectors.health_monitor.health_monitor.load_from_db", new_callable=AsyncMock),
    patch("gateway.auth.jwt_secret.load_session_jwt_secret", return_value=_TEST_SECRET),
    patch("gateway.auth.notebook_jwt.load_session_jwt_secret", return_value=_TEST_SECRET),
]


def _enter_patches():
    """Enter all app patches and return the stack."""
    stack = []
    for p in _APP_PATCHES:
        stack.append(p.__enter__())
    return stack


def _exit_patches():
    for p in reversed(_APP_PATCHES):
        p.__exit__(None, None, None)


def _build_test_client(org_id: str = "org-1", user_id: str = "user-1") -> TestClient:
    """Build a TestClient with mocked auth."""
    from gateway.api.deps import get_store
    from gateway.auth import resolve_org_id, resolve_user_id
    from gateway.main import app

    async def _fake_user_id(request: Request) -> str:
        return user_id

    async def _fake_org_id(request: Request, _user_id) -> str:
        return org_id

    async def _fake_store():
        return _make_mock_store(org_id=org_id, user_id=user_id)

    app.dependency_overrides[resolve_user_id] = _fake_user_id
    app.dependency_overrides[resolve_org_id] = _fake_org_id
    app.dependency_overrides[get_store] = _fake_store
    return TestClient(app, raise_server_exceptions=False)


class TestCrossOrgScopingHTTP:
    """Cross-org GET/DELETE return 404."""

    def test_cross_org_get_returns_404(self, monkeypatch):
        """GET /api/notebook-sessions/{id} from a different org returns 404."""
        from gateway.api.deps import get_store
        from gateway.auth import resolve_org_id, resolve_user_id
        from gateway.main import app

        session_id = str(uuid.uuid4())
        org_b = "org-b"

        async def _fake_get_session_by_id(session, *, session_id, org_id):
            return None  # Cross-org: always returns None

        async def _fake_user_id(request: Request) -> str:
            return "user-b"

        async def _fake_org_id(request: Request, _user_id) -> str:
            return org_b

        async def _fake_store_b():
            return _make_mock_store(org_id=org_b, user_id="user-b")

        app.dependency_overrides[resolve_user_id] = _fake_user_id
        app.dependency_overrides[resolve_org_id] = _fake_org_id
        app.dependency_overrides[get_store] = _fake_store_b

        try:
            with (
                patch("gateway.main.init_db", new_callable=AsyncMock),
                patch("gateway.main.close_db", new_callable=AsyncMock),
                patch("gateway.main.get_session_factory", return_value=AsyncMock()),
                patch("gateway.main._mcp_session_manager", None),
                patch("gateway.connectors.health_monitor.health_monitor.load_from_db", new_callable=AsyncMock),
                patch("gateway.auth.jwt_secret.load_session_jwt_secret", return_value=_TEST_SECRET),
                patch("gateway.auth.notebook_jwt.load_session_jwt_secret", return_value=_TEST_SECRET),
                patch(
                    "gateway.store.notebook_sessions.get_session_by_id",
                    side_effect=_fake_get_session_by_id,
                ),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                with client:
                    resp = client.get(f"/api/notebook-sessions/{session_id}")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(resolve_user_id, None)
            app.dependency_overrides.pop(resolve_org_id, None)
            app.dependency_overrides.pop(get_store, None)

    def test_cross_org_delete_returns_404(self, monkeypatch):
        """DELETE /api/notebook-sessions/{id} from a different org returns 404."""
        from gateway.api.deps import get_store
        from gateway.auth import resolve_org_id, resolve_user_id
        from gateway.main import app

        session_id = str(uuid.uuid4())
        org_b = "org-b"

        async def _fake_get_session_by_id(session, *, session_id, org_id):
            return None  # Cross-org: always None

        async def _fake_user_id(request: Request) -> str:
            return "user-b"

        async def _fake_org_id(request: Request, _user_id) -> str:
            return org_b

        async def _fake_store_b():
            return _make_mock_store(org_id=org_b, user_id="user-b")

        app.dependency_overrides[resolve_user_id] = _fake_user_id
        app.dependency_overrides[resolve_org_id] = _fake_org_id
        app.dependency_overrides[get_store] = _fake_store_b

        try:
            with (
                patch("gateway.main.init_db", new_callable=AsyncMock),
                patch("gateway.main.close_db", new_callable=AsyncMock),
                patch("gateway.main.get_session_factory", return_value=AsyncMock()),
                patch("gateway.main._mcp_session_manager", None),
                patch("gateway.connectors.health_monitor.health_monitor.load_from_db", new_callable=AsyncMock),
                patch("gateway.auth.jwt_secret.load_session_jwt_secret", return_value=_TEST_SECRET),
                patch("gateway.auth.notebook_jwt.load_session_jwt_secret", return_value=_TEST_SECRET),
                patch(
                    "gateway.store.notebook_sessions.get_session_by_id",
                    side_effect=_fake_get_session_by_id,
                ),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                with client:
                    resp = client.delete(f"/api/notebook-sessions/{session_id}")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(resolve_user_id, None)
            app.dependency_overrides.pop(resolve_org_id, None)
            app.dependency_overrides.pop(get_store, None)


class TestPodSpecEnv:
    """Pod spec dict does NOT contain SP_SESSION_JWT — JWT is staged via Secret+emptyDir."""

    def _make_manifest(self, **kwargs):
        from gateway.orchestrator.kubernetes import _pod_manifest

        defaults = dict(
            pod_name="nb-test",
            namespace="default",
            image="signalpilot-notebook:latest",
            user_id="user-1",
            org_id="org-1",
            project_id="proj-1",
            branch="main",
            gateway_url="http://localhost:3300",
            session_jwt_secret_name="sp-jwt-nb-test",
            session_id="sess-abc",
            access_token="access-abc",
        )
        defaults.update(kwargs)
        return _pod_manifest(**defaults)

    def test_pod_env_does_not_contain_session_jwt(self, monkeypatch):
        """_pod_manifest does NOT inject SP_SESSION_JWT as an env var (R4 F-6)."""
        manifest = self._make_manifest()
        env_names = {e["name"] for e in manifest["spec"]["containers"][0]["env"]}
        assert "SP_SESSION_JWT" not in env_names
        assert "SP_SESSION_ID" in env_names
        assert "SP_API_KEY" not in env_names

    def test_pod_env_session_id_value(self, monkeypatch):
        """SP_SESSION_ID env var gets the correct value."""
        manifest = self._make_manifest(session_id="sess-xyz")
        env_by_name = {e["name"]: e.get("value") for e in manifest["spec"]["containers"][0]["env"]}
        assert env_by_name["SP_SESSION_ID"] == "sess-xyz"

    def test_init_container_present(self):
        """jwt-stager initContainer is present and stages the JWT file."""
        manifest = self._make_manifest()
        init_containers = manifest["spec"]["initContainers"]
        assert len(init_containers) == 1
        init = init_containers[0]
        assert init["name"] == "jwt-stager"
        # InitContainer runs as uid 10001 (non-root); kubelet fsGroup chown handles ownership (R7 F-14).
        assert init["securityContext"]["runAsUser"] == 10001
        # Constant sh -c — no user-input interpolation.
        assert init["command"][0] == "sh"
        cmd_str = init["command"][2]
        assert "$" not in cmd_str, "initContainer command must not contain variable interpolation"
        assert "`" not in cmd_str, "initContainer command must not contain backticks"
        # Source mount must be read-only.
        src_mounts = [m for m in init["volumeMounts"] if m["name"] == "session-jwt-src"]
        assert len(src_mounts) == 1
        assert src_mounts[0].get("readOnly") is True
        # Destination mount (emptyDir) is writable — no readOnly key.
        dst_mounts = [m for m in init["volumeMounts"] if m["name"] == "session-jwt"]
        assert len(dst_mounts) == 1
        assert "readOnly" not in dst_mounts[0] or not dst_mounts[0]["readOnly"]

    def test_main_container_mounts_session_jwt_emptydir(self):
        """Main container mounts session-jwt emptyDir (writable), NOT session-jwt-src."""
        manifest = self._make_manifest()
        mounts = manifest["spec"]["containers"][0]["volumeMounts"]
        mount_names = {m["name"] for m in mounts}
        assert "session-jwt" in mount_names
        assert "session-jwt-src" not in mount_names, "Main container must NOT mount the Secret volume"
        # The session-jwt mount must be writable (no readOnly: True).
        jwt_mounts = [m for m in mounts if m["name"] == "session-jwt"]
        assert len(jwt_mounts) == 1
        assert not jwt_mounts[0].get("readOnly"), "session-jwt mount must be writable for unlink"

    def test_session_jwt_volume_is_emptydir_memory(self):
        """session-jwt volume is an in-memory emptyDir with sizeLimit."""
        manifest = self._make_manifest()
        volumes = {v["name"]: v for v in manifest["spec"]["volumes"]}
        jwt_vol = volumes["session-jwt"]
        assert "emptyDir" in jwt_vol
        assert jwt_vol["emptyDir"].get("medium") == "Memory"
        assert "sizeLimit" in jwt_vol["emptyDir"]

    def test_secret_volume_references_correct_secret(self):
        """session-jwt-src volume references the per-session Secret."""
        manifest = self._make_manifest(session_jwt_secret_name="sp-jwt-nb-abc")
        volumes = {v["name"]: v for v in manifest["spec"]["volumes"]}
        src_vol = volumes["session-jwt-src"]
        assert src_vol["secret"]["secretName"] == "sp-jwt-nb-abc"

    def test_main_container_command_no_sh(self):
        """Main container command is argv-only — no 'sh' element (F-4 invariant)."""
        manifest = self._make_manifest()
        command = manifest["spec"]["containers"][0]["command"]
        assert "sh" not in command

    def test_automount_service_account_token_false(self):
        """automountServiceAccountToken is False."""
        manifest = self._make_manifest()
        assert manifest["spec"]["automountServiceAccountToken"] is False


class TestSessionReuse:
    """Session reuse: alive pod → reuse; dead pod → recreate."""

    @pytest.mark.asyncio
    async def test_session_reuse_when_pod_alive(self, monkeypatch):
        """Second create_session call returns existing session when pod is alive."""
        _patch_jwt_secret(monkeypatch)

        import time

        from gateway.api import notebook_sessions as ns_api
        from gateway.models.notebook_sessions import NotebookSessionInfo
        from gateway.store import notebook_sessions as ns_store

        existing_session = NotebookSessionInfo(
            id="existing-sess",
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            pod_name="nb-abc",
            pod_ip="10.0.0.1:2718",
            access_token="tok-abc",
            status="running",
            last_ping=time.time(),
            created_at=time.time(),
        )
        existing_session.notebook_url = "http://10.0.0.1:2718?access_token=tok-abc"

        mock_orch = AsyncMock()
        mock_orch.is_pod_alive.return_value = True

        monkeypatch.setattr(ns_store, "get_active_session", AsyncMock(return_value=existing_session))
        monkeypatch.setattr(ns_api, "_get_orchestrator", AsyncMock(return_value=mock_orch))

        store = _make_mock_store()

        from gateway.models.notebook_sessions import NotebookSessionCreate

        body = NotebookSessionCreate(project_id="proj-1", branch="main")

        result = await ns_api.create_session(body, store, _make_mock_response())
        assert result.id == "existing-sess"
        mock_orch.create_pod.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_recreated_when_pod_dead(self, monkeypatch):
        """create_session recreates pod when is_pod_alive returns False."""
        _patch_jwt_secret(monkeypatch)

        import time

        from gateway.api import notebook_sessions as ns_api
        from gateway.models.notebook_sessions import NotebookSessionInfo
        from gateway.orchestrator import PodInfo
        from gateway.store import notebook_sessions as ns_store

        existing_session = NotebookSessionInfo(
            id="dead-sess",
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            pod_name="nb-dead",
            pod_ip="10.0.0.2:2718",
            access_token="tok-dead",
            status="running",
            last_ping=time.time(),
            created_at=time.time(),
        )

        new_session = NotebookSessionInfo(
            id="new-sess",
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            pod_name="nb-new",
            pod_ip=None,
            access_token="tok-new",
            status="creating",
            last_ping=time.time(),
            created_at=time.time(),
        )

        mock_orch = AsyncMock()
        mock_orch.is_pod_alive.return_value = False
        mock_orch.create_pod.return_value = PodInfo(name="nb-new", ip=None, status="pending")
        mock_orch.wait_for_running = AsyncMock(
            return_value=PodInfo(name="nb-new", ip=None, status="running")
        )
        mock_orch.wait_for_ready.return_value = PodInfo(name="nb-new", ip="10.0.0.3:2718", status="running")

        mark_stopped_calls = []

        async def _mock_mark_stopped(session, *, session_id):
            mark_stopped_calls.append(session_id)

        async def _mock_delete_stopped(session, *, org_id, user_id):
            pass

        async def _mock_update_status(session, *, session_id, status, pod_ip=None, pod_ip_internal=None):
            pass

        monkeypatch.setattr(ns_store, "get_active_session", AsyncMock(return_value=existing_session))
        monkeypatch.setattr(ns_store, "create_session", AsyncMock(return_value=new_session))
        monkeypatch.setattr(ns_store, "mark_stopped", _mock_mark_stopped)
        monkeypatch.setattr(ns_store, "delete_stopped", _mock_delete_stopped)
        monkeypatch.setattr(ns_store, "update_session_status", _mock_update_status)
        monkeypatch.setattr(ns_api, "_get_orchestrator", AsyncMock(return_value=mock_orch))

        store = _make_mock_store()

        from gateway.models.notebook_sessions import NotebookSessionCreate

        body = NotebookSessionCreate(project_id="proj-1", branch="main")

        result = await ns_api.create_session(body, store, _make_mock_response())
        assert result.id == "new-sess"
        mock_orch.create_pod.assert_called_once()
        # Verify mark_stopped was called for the dead session
        assert "dead-sess" in mark_stopped_calls

    @pytest.mark.asyncio
    async def test_create_pod_receives_secret_name_not_jwt(self, monkeypatch):
        """create_pod call receives session_jwt_secret_name (not raw session_jwt) — R4 F-6."""
        _patch_jwt_secret(monkeypatch)

        import time

        from gateway.api import notebook_sessions as ns_api
        from gateway.models.notebook_sessions import NotebookSessionInfo
        from gateway.orchestrator import PodInfo
        from gateway.store import notebook_sessions as ns_store

        new_session = NotebookSessionInfo(
            id="sess-new",
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            pod_name="nb-test",
            pod_ip=None,
            access_token="tok-new",
            status="creating",
            last_ping=time.time(),
            created_at=time.time(),
        )

        mock_orch = AsyncMock()
        mock_orch.create_pod.return_value = PodInfo(name="nb-test", ip=None, status="pending")
        mock_orch.wait_for_running = AsyncMock(
            return_value=PodInfo(name="nb-test", ip=None, status="running")
        )
        mock_orch.wait_for_ready.return_value = PodInfo(name="nb-test", ip="10.0.0.4:2718", status="running")
        # Mock core_v1 methods needed for Secret creation.
        mock_orch._core_api = AsyncMock()
        mock_orch._core_api.create_namespaced_secret = AsyncMock()
        mock_orch._core_api.read_namespaced_pod = AsyncMock(
            return_value=MagicMock(metadata=MagicMock(name="nb-test", uid="uid-abc"))
        )
        mock_orch._core_api.patch_namespaced_secret = AsyncMock()
        mock_orch._ensure_client = AsyncMock()
        mock_orch._resolve_namespace = MagicMock(return_value="sp-nb-org-1")

        monkeypatch.setattr(ns_store, "get_active_session", AsyncMock(return_value=None))
        monkeypatch.setattr(ns_store, "create_session", AsyncMock(return_value=new_session))
        monkeypatch.setattr(ns_store, "delete_stopped", AsyncMock())
        monkeypatch.setattr(ns_store, "update_session_status", AsyncMock())
        monkeypatch.setattr(ns_api, "_get_orchestrator", AsyncMock(return_value=mock_orch))

        store = _make_mock_store()

        from gateway.models.notebook_sessions import NotebookSessionCreate

        body = NotebookSessionCreate(project_id="proj-1", branch="main")

        await ns_api.create_session(body, store, _make_mock_response())

        call_kwargs = mock_orch.create_pod.call_args.kwargs
        # R4 F-6: JWT is staged via Secret, not passed directly to create_pod.
        assert "session_jwt" not in call_kwargs
        assert "session_jwt_secret_name" in call_kwargs
        assert call_kwargs["session_jwt_secret_name"].startswith("sp-jwt-")
        assert "api_key" not in call_kwargs
        # Verify the Secret was created with encoded JWT.
        mock_orch._core_api.create_namespaced_secret.assert_called_once()


class TestR3OrgIdEnforcement:
    """R3: org_id threading and quota enforcement."""

    @pytest.mark.asyncio
    async def test_create_session_empty_org_id_returns_400(self, monkeypatch):
        """create_session with empty org_id returns 400."""
        _patch_jwt_secret(monkeypatch)

        from gateway.api import notebook_sessions as ns_api
        from gateway.store import notebook_sessions as ns_store

        monkeypatch.setattr(ns_store, "get_active_session", AsyncMock(return_value=None))

        store = _make_mock_store(org_id="", user_id="user-1")

        from fastapi import HTTPException

        from gateway.models.notebook_sessions import NotebookSessionCreate

        body = NotebookSessionCreate(project_id="proj-1", branch="main")

        with pytest.raises(HTTPException) as exc_info:
            await ns_api.create_session(body, store, _make_mock_response())
        assert exc_info.value.status_code == 400
        assert "org_id" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_create_session_quota_exhausted_returns_429(self, monkeypatch):
        """create_pod raises K8s 403 with quota message → API returns 429."""
        _patch_jwt_secret(monkeypatch)

        import time

        from gateway.api import notebook_sessions as ns_api
        from gateway.models.notebook_sessions import NotebookSessionInfo
        from gateway.store import notebook_sessions as ns_store

        new_session = NotebookSessionInfo(
            id="sess-quota",
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            pod_name="nb-quota",
            pod_ip=None,
            access_token="tok-quota",
            status="creating",
            last_ping=time.time(),
            created_at=time.time(),
        )

        mock_orch = AsyncMock()
        # R5: _is_quota_exceeded_error uses exc.status + exc.body, not str(exc).
        _E = type("ApiException", (Exception,), {})
        _quota_exc = _E("Forbidden")
        _quota_exc.status = 403  # type: ignore[attr-defined]
        _quota_exc.body = "pods 'nb-quota' is forbidden: exceeded quota: default-quota"  # type: ignore[attr-defined]
        mock_orch.create_pod.side_effect = _quota_exc

        monkeypatch.setattr(ns_store, "get_active_session", AsyncMock(return_value=None))
        monkeypatch.setattr(ns_store, "create_session", AsyncMock(return_value=new_session))
        monkeypatch.setattr(ns_store, "delete_stopped", AsyncMock())
        monkeypatch.setattr(ns_store, "update_session_status", AsyncMock())
        monkeypatch.setattr(ns_api, "_get_orchestrator", AsyncMock(return_value=mock_orch))

        store = _make_mock_store()

        from fastapi import HTTPException

        from gateway.models.notebook_sessions import NotebookSessionCreate

        body = NotebookSessionCreate(project_id="proj-1", branch="main")

        with pytest.raises(HTTPException) as exc_info:
            await ns_api.create_session(body, store, _make_mock_response())
        assert exc_info.value.status_code == 429
        assert "quota" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_is_pod_alive_called_with_org_id(self, monkeypatch):
        """is_pod_alive is called with org_id keyword argument on session reuse check."""
        _patch_jwt_secret(monkeypatch)

        import time

        from gateway.api import notebook_sessions as ns_api
        from gateway.models.notebook_sessions import NotebookSessionInfo
        from gateway.store import notebook_sessions as ns_store

        existing_session = NotebookSessionInfo(
            id="sess-alive",
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            pod_name="nb-alive",
            pod_ip="10.0.0.1:2718",
            access_token="tok-alive",
            status="running",
            last_ping=time.time(),
            created_at=time.time(),
        )
        existing_session.notebook_url = "/notebook/sess-alive/_init"

        is_alive_calls = []

        async def _fake_is_pod_alive(pod_name, *, org_id):
            is_alive_calls.append({"pod_name": pod_name, "org_id": org_id})
            return True

        mock_orch = AsyncMock()
        mock_orch.is_pod_alive = _fake_is_pod_alive

        monkeypatch.setattr(ns_store, "get_active_session", AsyncMock(return_value=existing_session))
        monkeypatch.setattr(ns_api, "_get_orchestrator", AsyncMock(return_value=mock_orch))

        store = _make_mock_store(org_id="org-1", user_id="user-1")

        from gateway.models.notebook_sessions import NotebookSessionCreate

        body = NotebookSessionCreate(project_id="proj-1", branch="main")

        result = await ns_api.create_session(body, store, _make_mock_response())
        assert result.id == "sess-alive"
        assert len(is_alive_calls) == 1
        assert is_alive_calls[0]["org_id"] == "org-1"
        assert is_alive_calls[0]["pod_name"] == "nb-alive"

    @pytest.mark.asyncio
    async def test_wait_for_ready_called_with_org_id(self, monkeypatch):
        """wait_for_ready is called with org_id keyword argument."""
        _patch_jwt_secret(monkeypatch)

        import time

        from gateway.api import notebook_sessions as ns_api
        from gateway.models.notebook_sessions import NotebookSessionInfo
        from gateway.orchestrator import PodInfo
        from gateway.store import notebook_sessions as ns_store

        new_session = NotebookSessionInfo(
            id="sess-new",
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            pod_name="nb-test",
            pod_ip=None,
            access_token="tok-new",
            status="creating",
            last_ping=time.time(),
            created_at=time.time(),
        )

        wait_calls = []

        async def _fake_wait(pod_name, *, org_id, timeout=60):
            wait_calls.append({"pod_name": pod_name, "org_id": org_id})
            return PodInfo(name=pod_name, ip="10.0.0.5", status="running", internal_ip="10.0.0.5")

        mock_orch = AsyncMock()
        mock_orch.create_pod.return_value = PodInfo(name="nb-test", ip=None, status="pending")
        mock_orch.wait_for_running = AsyncMock(
            return_value=PodInfo(name="nb-test", ip=None, status="running")
        )
        mock_orch.wait_for_ready = _fake_wait

        monkeypatch.setattr(ns_store, "get_active_session", AsyncMock(return_value=None))
        monkeypatch.setattr(ns_store, "create_session", AsyncMock(return_value=new_session))
        monkeypatch.setattr(ns_store, "delete_stopped", AsyncMock())
        monkeypatch.setattr(ns_store, "update_session_status", AsyncMock())
        monkeypatch.setattr(ns_api, "_get_orchestrator", AsyncMock(return_value=mock_orch))

        store = _make_mock_store(org_id="org-1", user_id="user-1")

        from gateway.models.notebook_sessions import NotebookSessionCreate

        body = NotebookSessionCreate(project_id="proj-1", branch="main")

        await ns_api.create_session(body, store, _make_mock_response())
        assert len(wait_calls) == 1
        assert wait_calls[0]["org_id"] == "org-1"


class TestLocalAPIKeyAuth:
    """sp_-prefixed local API key still authenticates end-to-end."""

    @pytest.mark.asyncio
    async def test_sp_prefix_key_with_auth_state_resolves_correctly(self, monkeypatch):
        """When auth state is already set (by APIKeyAuthMiddleware), sp_ bearer resolves fine."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

        import gateway.auth.user as user_mod

        monkeypatch.setattr(user_mod, "is_cloud_mode", lambda: False)

        request = MagicMock()
        request.state = MagicMock()
        request.state.auth = {
            "auth_method": "api_key",
            "user_id": "local",
            "org_id": "local",
            "scopes": ["read", "write"],
        }
        request.headers = {"authorization": "Bearer sp_local_abc123"}
        request.cookies = {}

        user_id = await user_mod.resolve_user_id(request)
        assert user_id == "local"

    @pytest.mark.asyncio
    async def test_sp_prefix_key_without_auth_state_raises_401(self, monkeypatch):
        """sp_ key with no auth state (unrecognized key) returns 401."""
        import gateway.auth.user as user_mod

        monkeypatch.setattr(user_mod, "is_cloud_mode", lambda: False)

        request = MagicMock()
        request.state = MagicMock()
        request.state.auth = None
        request.headers = {"authorization": "Bearer sp_unknown_key_xyz"}
        request.cookies = {}

        with pytest.raises(HTTPException) as exc_info:
            await user_mod.resolve_user_id(request)
        assert exc_info.value.status_code == 401



# --- Option B entrypoint contract tests ---


def _make_mock_response():
    resp = MagicMock()
    resp.headers = {}
    return resp


class TestOptionBEntrypoint:
    @pytest.mark.asyncio
    async def test_create_session_sequence_no_populate(self, monkeypatch):
        """create_session: create_pod -> wait_for_running -> wait_for_ready. No populate call."""
        _patch_jwt_secret(monkeypatch)

        import time

        from gateway.api import notebook_sessions as ns_api
        from gateway.models.notebook_sessions import NotebookSessionInfo
        from gateway.orchestrator import PodInfo
        from gateway.store import notebook_sessions as ns_store

        call_order: list[str] = []

        new_session = NotebookSessionInfo(
            id="sess-optb",
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            pod_name="nb-optb",
            pod_ip=None,
            access_token="tok-optb",
            status="creating",
            last_ping=time.time(),
            created_at=time.time(),
        )

        mock_orch = AsyncMock()

        async def _create_pod(*a, **kw):
            call_order.append("create_pod")
            return PodInfo(name="nb-optb", ip=None, status="pending")

        async def _wait_running(*a, **kw):
            call_order.append("wait_for_running")
            return PodInfo(name="nb-optb", ip=None, status="running")

        async def _wait_ready(*a, **kw):
            call_order.append("wait_for_ready")
            return PodInfo(name="nb-optb", ip="10.0.0.9", status="running", internal_ip="10.0.0.9")

        mock_orch.create_pod = _create_pod
        mock_orch.wait_for_running = _wait_running
        mock_orch.wait_for_ready = _wait_ready

        monkeypatch.setattr(ns_store, "get_active_session", AsyncMock(return_value=None))
        monkeypatch.setattr(ns_store, "create_session", AsyncMock(return_value=new_session))
        monkeypatch.setattr(ns_store, "delete_stopped", AsyncMock())
        monkeypatch.setattr(ns_store, "update_session_status", AsyncMock())
        monkeypatch.setattr(ns_api, "_get_orchestrator", AsyncMock(return_value=mock_orch))

        store = _make_mock_store()
        response = _make_mock_response()

        from gateway.models.notebook_sessions import NotebookSessionCreate

        body = NotebookSessionCreate(project_id="proj-1", branch="main")

        result = await ns_api.create_session(body, store, response)
        assert result.id == "sess-optb"
        assert "create_pod" in call_order
        assert "wait_for_running" in call_order
        assert "wait_for_ready" in call_order
        assert call_order.index("wait_for_running") < call_order.index("wait_for_ready")

    def test_pod_cmd_uses_entrypoint_shim(self):
        """Pod CMD uses the entrypoint shim (regression guard — no sh -c in main container)."""
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
            session_jwt_secret_name="sp-jwt-nb-test",
            session_id="sess-abc",
            access_token=None,
        )
        command = manifest["spec"]["containers"][0]["command"]
        # R4 F-6: main container is argv-only — no sh -c.
        assert "sh" not in command
        assert "signalpilot._server.entrypoint" in " ".join(command)

    @pytest.mark.asyncio
    async def test_delete_session_deletes_pod_and_marks_stopped(self, monkeypatch):
        """delete_session: deletes pod and marks session stopped."""
        _patch_jwt_secret(monkeypatch)

        import time

        from gateway.api import notebook_sessions as ns_api
        from gateway.models.notebook_sessions import NotebookSessionInfo
        from gateway.store import notebook_sessions as ns_store

        existing_session = NotebookSessionInfo(
            id="sess-del",
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            pod_name="nb-del",
            pod_ip="10.0.0.1",
            access_token="tok-del",
            status="running",
            last_ping=time.time(),
            created_at=time.time(),
        )

        mock_orch = AsyncMock()
        delete_pod_calls = []

        async def _mock_delete_pod(pod_name, *, org_id):
            delete_pod_calls.append(pod_name)
            return True

        mock_orch.delete_pod = _mock_delete_pod
        mark_stopped_calls = []

        monkeypatch.setattr(ns_store, "get_active_session", AsyncMock(return_value=existing_session))
        monkeypatch.setattr(
            ns_store, "mark_stopped",
            AsyncMock(side_effect=lambda *a, **kw: mark_stopped_calls.append(True))
        )
        monkeypatch.setattr(ns_api, "_get_orchestrator", AsyncMock(return_value=mock_orch))

        store = _make_mock_store()
        response = _make_mock_response()

        await ns_api.delete_session(store, response)

        assert delete_pod_calls == ["nb-del"]
        assert mark_stopped_calls


class TestIsQuotaExceededErrorClassification:
    """R5: _is_quota_exceeded_error must use exc.status, not str(exc)."""

    def test_returns_true_for_403_with_exceeded_quota_body(self):
        from gateway.api.notebook_sessions import _is_quota_exceeded_error

        exc = type("E", (Exception,), {})()
        exc.status = 403  # type: ignore[attr-defined]
        exc.body = "pods exceeded quota for pods in namespace sp-nb-abc"  # type: ignore[attr-defined]
        assert _is_quota_exceeded_error(exc) is True

    def test_returns_false_for_403_without_quota_body(self):
        from gateway.api.notebook_sessions import _is_quota_exceeded_error

        exc = type("E", (Exception,), {})()
        exc.status = 403  # type: ignore[attr-defined]
        exc.body = "forbidden"  # type: ignore[attr-defined]
        assert _is_quota_exceeded_error(exc) is False

    def test_returns_false_for_non_403_status(self):
        from gateway.api.notebook_sessions import _is_quota_exceeded_error

        exc = type("E", (Exception,), {})()
        exc.status = 429  # type: ignore[attr-defined]
        exc.body = "exceeded quota"  # type: ignore[attr-defined]
        assert _is_quota_exceeded_error(exc) is False

    def test_returns_false_for_plain_exception_with_403_in_message(self):
        """Proves we no longer grep — '403' in the message text must not count."""
        from gateway.api.notebook_sessions import _is_quota_exceeded_error

        assert _is_quota_exceeded_error(Exception("403 exceeded quota forbidden")) is False
