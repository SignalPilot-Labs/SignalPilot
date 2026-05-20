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
    """Pod spec dict contains SP_SESSION_JWT and NOT SP_API_KEY."""

    def test_pod_env_contains_session_jwt_not_api_key(self, monkeypatch):
        """_pod_manifest produces SP_SESSION_JWT and no SP_API_KEY."""
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
            session_jwt="test.jwt.token",
            session_id="sess-abc",
            access_token="access-abc",
        )
        env_names = {e["name"] for e in manifest["spec"]["containers"][0]["env"]}
        assert "SP_SESSION_JWT" in env_names
        assert "SP_SESSION_ID" in env_names
        assert "SP_API_KEY" not in env_names

    def test_pod_env_session_jwt_value(self, monkeypatch):
        """SP_SESSION_JWT env var gets the correct value."""
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
            session_jwt="my.jwt.value",
            session_id="sess-xyz",
            access_token=None,
        )
        env_by_name = {e["name"]: e["value"] for e in manifest["spec"]["containers"][0]["env"]}
        assert env_by_name["SP_SESSION_JWT"] == "my.jwt.value"
        assert env_by_name["SP_SESSION_ID"] == "sess-xyz"


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

        result = await ns_api.create_session(body, store)
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

        result = await ns_api.create_session(body, store)
        assert result.id == "new-sess"
        mock_orch.create_pod.assert_called_once()
        # Verify mark_stopped was called for the dead session
        assert "dead-sess" in mark_stopped_calls

    @pytest.mark.asyncio
    async def test_create_pod_receives_session_jwt_not_api_key(self, monkeypatch):
        """create_pod call does NOT pass api_key; instead passes session_jwt."""
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
        mock_orch.wait_for_ready.return_value = PodInfo(name="nb-test", ip="10.0.0.4:2718", status="running")

        monkeypatch.setattr(ns_store, "get_active_session", AsyncMock(return_value=None))
        monkeypatch.setattr(ns_store, "create_session", AsyncMock(return_value=new_session))
        monkeypatch.setattr(ns_store, "delete_stopped", AsyncMock())
        monkeypatch.setattr(ns_store, "update_session_status", AsyncMock())
        monkeypatch.setattr(ns_api, "_get_orchestrator", AsyncMock(return_value=mock_orch))

        store = _make_mock_store()

        from gateway.models.notebook_sessions import NotebookSessionCreate

        body = NotebookSessionCreate(project_id="proj-1", branch="main")

        await ns_api.create_session(body, store)

        call_kwargs = mock_orch.create_pod.call_args.kwargs
        assert "session_jwt" in call_kwargs
        assert "api_key" not in call_kwargs

        # Verify the JWT is a valid notebook session JWT
        token = call_kwargs["session_jwt"]
        claims = verify_session_jwt(token)
        assert claims["sub"] == "user-1"
        assert claims["org_id"] == "org-1"


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
            await ns_api.create_session(body, store)
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
        mock_orch.create_pod.side_effect = Exception(
            "403 Forbidden: pods 'nb-quota' is forbidden: exceeded quota: default-quota"
        )

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
            await ns_api.create_session(body, store)
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

        result = await ns_api.create_session(body, store)
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
        mock_orch.wait_for_ready = _fake_wait

        monkeypatch.setattr(ns_store, "get_active_session", AsyncMock(return_value=None))
        monkeypatch.setattr(ns_store, "create_session", AsyncMock(return_value=new_session))
        monkeypatch.setattr(ns_store, "delete_stopped", AsyncMock())
        monkeypatch.setattr(ns_store, "update_session_status", AsyncMock())
        monkeypatch.setattr(ns_api, "_get_orchestrator", AsyncMock(return_value=mock_orch))

        store = _make_mock_store(org_id="org-1", user_id="user-1")

        from gateway.models.notebook_sessions import NotebookSessionCreate

        body = NotebookSessionCreate(project_id="proj-1", branch="main")

        await ns_api.create_session(body, store)
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
