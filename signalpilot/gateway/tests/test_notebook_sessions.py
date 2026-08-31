"""Integration tests for notebook session endpoints and related auth dispatch.

Runtime v2: compute is a sandbox behind the NotebookBackend seam. Tests cover:
- Cross-org GET/DELETE return 404.
- Notebook-session JWT accepted on inbound requests.
- Clerk-shaped JWT not accepted by notebook-session verifier.
- sp_-prefixed local API key still authenticates end-to-end.
- Launch credentials: the session JWT rides the boot process env, the notebook
  token rides write_file — neither lands in the sandbox creation spec.
- Session reuse when the runtime is alive; recreate when dead; resume when
  snapshotted.
- Org budget exhaustion returns 429.
- Direct store get_session_by_id cross-org returns None.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from gateway.auth.notebook_jwt import (
    NOTEBOOK_SESSION_AUD,
    NOTEBOOK_SESSION_ISS,
    mint_session_jwt,
    verify_session_jwt,
)

_TEST_SECRET = "integration-test-secret-32-bytes!!"

# Helper functions.


def _patch_jwt_secret(monkeypatch):
    monkeypatch.setattr("gateway.auth.notebook_jwt.load_session_jwt_secret", lambda: _TEST_SECRET)
    monkeypatch.setattr("gateway.auth.jwt_secret._cached_secret", _TEST_SECRET)


def _patch_encryption_key(monkeypatch):
    import gateway.store.crypto as crypto

    monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)
    monkeypatch.setenv("SP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("SP_ENCRYPTION_KEY_OLD", raising=False)
    monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)


@pytest.fixture(autouse=True)
def _default_org_secret_freshness(monkeypatch):
    monkeypatch.setattr(
        "gateway.notebooks.session_service.org_secrets_store.get_anthropic_key_updated_at",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "gateway.notebooks.session_service.org_secrets_store.resolve_anthropic_key",
        AsyncMock(return_value=None),
    )


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


@pytest.mark.asyncio
async def test_chat_force_oauth_omits_org_api_key_from_runtime_env(
    monkeypatch,
):
    from gateway.notebooks import session_service

    monkeypatch.setenv("SP_CHAT_FORCE_OAUTH_TOKEN", "true")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-test")
    resolve_org_key = AsyncMock(return_value="depleted-org-key")
    monkeypatch.setattr(
        session_service.org_secrets_store,
        "resolve_anthropic_key",
        resolve_org_key,
    )

    runtime_env = await session_service._runtime_env(
        MagicMock(),
        org_id="org-1",
        extra_env={"SP_CHAT_PROJECT_ID": "project-1"},
    )

    assert runtime_env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat-test"
    assert "ANTHROPIC_API_KEY" not in runtime_env
    resolve_org_key.assert_not_awaited()


class FakeBackend:
    """In-memory NotebookBackend covering the whole protocol."""

    name = "vercel"

    def __init__(self) -> None:
        self.launches: list = []
        self.terminated: list[str] = []
        self.resumed: list[tuple[str, object]] = []
        self.extends: list[tuple[str, int]] = []
        self.alive = True
        self.launch_error: Exception | None = None
        self.resume_url: str | None = "https://resumed.vercel.run"
        self.counter = 0

    async def launch(self, request):
        from gateway.notebooks.backends import NotebookLaunch

        if self.launch_error is not None:
            raise self.launch_error
        self.launches.append(request)
        self.counter += 1
        return NotebookLaunch(
            runtime_handle=f"sbx-{self.counter}",
            upstream_url=f"https://sbx-{self.counter}.vercel.run",
        )

    async def is_alive(self, runtime_handle: str) -> bool:
        return self.alive

    async def resume(self, runtime_handle: str, request) -> str:
        if self.resume_url is None:
            raise RuntimeError("resume failed")
        self.resumed.append((runtime_handle, request))
        return self.resume_url

    async def snapshot_and_stop(self, runtime_handle: str):
        return "snap-1"

    async def extend(self, runtime_handle: str, seconds: int) -> None:
        self.extends.append((runtime_handle, seconds))

    async def terminate(self, runtime_handle: str) -> None:
        self.terminated.append(runtime_handle)

    async def reap_orphans(self, keep):
        return 0


def _session_info(**overrides):
    from gateway.models.notebook_sessions import NotebookSessionInfo

    defaults = {
        "id": "sess-1",
        "org_id": "org-1",
        "user_id": "user-1",
        "project_id": "proj-1",
        "branch": "main",
        "backend": "vercel",
        "status": "running",
        "last_ping": time.time(),
        "created_at": time.time(),
    }
    defaults.update(overrides)
    return NotebookSessionInfo(**defaults)


def _internal(**overrides):
    from gateway.store.notebook_sessions import NotebookSessionInternal

    defaults = {
        "session_id": "sess-1",
        "org_id": "org-1",
        "user_id": "user-1",
        "status": "running",
        "backend": "vercel",
        "runtime_handle": "sbx-live",
        "upstream_url": "https://sbx-live.vercel.run",
        "snapshot_id": None,
        "access_token": "tok-1",
        "project_id": "proj-1",
        "branch": "main",
    }
    defaults.update(overrides)
    return NotebookSessionInternal(**defaults)


@pytest.fixture
def svc(monkeypatch):
    """session_service with the store and workspace seams mocked out."""
    from gateway.notebooks import session_service as service
    from gateway.store import notebook_sessions as ns_store

    mocks = SimpleNamespace(
        get_active_session=AsyncMock(return_value=None),
        get_session_internal=AsyncMock(return_value=_internal()),
        create_session=AsyncMock(return_value=_session_info(status="creating")),
        update_session_runtime=AsyncMock(),
        mark_stopped=AsyncMock(),
        delete_stopped=AsyncMock(),
        count_running_for_org=AsyncMock(return_value=0),
    )
    for name, mock in vars(mocks).items():
        monkeypatch.setattr(ns_store, name, mock)
    monkeypatch.setattr(service, "acquire_lease", AsyncMock(return_value=time.time() + 90))
    monkeypatch.setattr(service, "release_lease", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "_hydration_source", AsyncMock(return_value=(None, None)))
    return mocks


# Verify store behavior.


class TestStoreGetSessionByIdCrossOrg:
    """Direct store-level: cross-org lookup returns None."""

    @pytest.mark.asyncio
    async def test_cross_org_returns_none(self):
        from gateway.store.notebook_sessions import get_session_by_id

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await get_session_by_id(mock_session, session_id="some-id", org_id="wrong-org")
        assert result is None

    @pytest.mark.asyncio
    async def test_same_org_returns_session(self):
        from gateway.db.models import GatewayNotebookSession
        from gateway.store.notebook_sessions import get_session_by_id

        row = GatewayNotebookSession(
            id="sess-abc",
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            backend="vercel",
            runtime_handle="sbx-abc",
            upstream_url="https://sbx-abc.vercel.run",
            access_token_enc=None,
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
        assert result.backend == "vercel"
        # FE view never carries the upstream URL or credentials.
        assert not hasattr(result, "upstream_url")
        assert not hasattr(result, "access_token")


class TestStoreNotebookSessionTokenStorage:
    """Direct store-level notebook session token storage tests."""

    @pytest.mark.asyncio
    async def test_create_session_encrypts_access_token_without_plaintext(self, monkeypatch):
        _patch_encryption_key(monkeypatch)
        monkeypatch.setattr("secrets.token_urlsafe", lambda n: "generated-token")

        from gateway.store.crypto import _decrypt_with_migration
        from gateway.store.notebook_sessions import create_session

        rows = []
        mock_session = MagicMock()
        mock_session.add.side_effect = rows.append
        mock_session.commit = AsyncMock()

        info = await create_session(
            mock_session,
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            backend="vercel",
        )

        assert len(rows) == 1
        row = rows[0]
        # The model stores only the encrypted access token.
        assert not hasattr(type(row), "access_token")
        assert row.access_token_enc is not None
        assert b"generated-token" not in row.access_token_enc
        token, needs_migration = _decrypt_with_migration(row.access_token_enc)
        assert token == "generated-token"
        assert needs_migration is False
        assert not hasattr(info, "access_token")
        mock_session.commit.assert_awaited_once()


# Verify JWT dispatch.


class TestNotebookJWTVerifierDispatch:
    """auth/user.py dispatch: iss-based routing."""

    @pytest.mark.asyncio
    async def test_notebook_session_jwt_accepted(self, monkeypatch):
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        monkeypatch.delenv("CLERK_PUBLISHABLE_KEY", raising=False)
        _patch_jwt_secret(monkeypatch)

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
    async def test_notebook_session_jwt_retains_run_scope_in_local_mode(self, monkeypatch):
        _patch_jwt_secret(monkeypatch)

        import gateway.auth.user as user_mod

        monkeypatch.setattr(user_mod, "is_cloud_mode", lambda: False)
        token = mint_session_jwt(
            user_id="local",
            org_id="local",
            session_id="sess-local",
            project_id="project-a",
            branch="main",
            connection_name="warehouse",
            commit_sha="a" * 40,
            capabilities=["query:read"],
            execution_identity="chat:run-a",
            scopes=["read", "query", "execute"],
            ttl=60,
        )
        request = MagicMock()
        request.state = MagicMock()
        request.state.auth = None
        request.headers = {"authorization": f"Bearer {token}"}
        request.cookies = {}

        user_id = await user_mod.resolve_user_id(request)

        assert user_id == "local"
        assert request.state._jwt_claims["execution_identity"] == "chat:run-a"
        assert request.state._jwt_claims["project_id"] == "project-a"

        # A second dependency resolution must not collapse the verified claims
        # to only the synthetic local user and organization.
        assert await user_mod.resolve_user_id(request) == "local"
        assert request.state._jwt_claims["execution_identity"] == "chat:run-a"
        assert request.state._jwt_claims["commit_sha"] == "a" * 40

    @pytest.mark.asyncio
    async def test_clerk_shaped_jwt_not_routed_to_notebook_verifier(self, monkeypatch):
        _patch_jwt_secret(monkeypatch)

        import gateway.auth.user as user_mod

        monkeypatch.setattr(user_mod, "is_cloud_mode", lambda: True)

        clerk_token = _make_clerk_jwt()
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

        with pytest.raises(HTTPException) as exc_info:
            await user_mod.resolve_user_id(request)
        assert exc_info.value.status_code in (401, 500)
        assert len(verify_called) == 0

    @pytest.mark.asyncio
    async def test_notebook_jwt_with_clerk_iss_rejected_by_nb_verifier(self, monkeypatch):
        _patch_jwt_secret(monkeypatch)

        import gateway.auth.user as user_mod

        monkeypatch.setattr(user_mod, "is_cloud_mode", lambda: True)

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

        with pytest.raises(HTTPException) as exc_info:
            await user_mod.resolve_user_id(request)
        assert exc_info.value.status_code in (401, 500)

    @pytest.mark.asyncio
    async def test_sp_prefix_short_circuits_no_jwt_decode(self, monkeypatch):
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
        request.state.auth = {
            "auth_method": "api_key",
            "user_id": "local-user",
            "org_id": "local",
            "scopes": ["read", "write"],
        }
        request.headers = {"authorization": "Bearer sp_test_key_abc123"}
        request.cookies = {}

        user_id = await user_mod.resolve_user_id(request)
        assert user_id == "local-user"
        assert len(decode_called) == 0


# Verify HTTP integration.


def _make_mock_store(org_id: str = "org-1", user_id: str = "user-1") -> AsyncMock:
    store = AsyncMock()
    store.org_id = org_id
    store.user_id = user_id
    store.session = AsyncMock()
    return store


def _make_mock_response():
    resp = MagicMock()
    resp.headers = {}
    return resp


class TestCrossOrgScopingHTTP:
    """Cross-org GET/DELETE return 404."""

    def _client(self, org_id: str, user_id: str):
        from gateway.api.deps import get_store
        from gateway.auth import resolve_org_id, resolve_user_id
        from gateway.main import app

        async def _fake_user_id(request: Request) -> str:
            return user_id

        async def _fake_org_id(request: Request) -> str:
            return org_id

        async def _fake_store():
            return _make_mock_store(org_id=org_id, user_id=user_id)

        app.dependency_overrides[resolve_user_id] = _fake_user_id
        app.dependency_overrides[resolve_org_id] = _fake_org_id
        app.dependency_overrides[get_store] = _fake_store
        return app

    def _cleanup(self):
        from gateway.api.deps import get_store
        from gateway.auth import resolve_org_id, resolve_user_id
        from gateway.main import app

        app.dependency_overrides.pop(resolve_user_id, None)
        app.dependency_overrides.pop(resolve_org_id, None)
        app.dependency_overrides.pop(get_store, None)

    def _request(self, method: str, session_id: str):
        from gateway.main import app

        app_patches = (
            patch("gateway.main.init_db", new_callable=AsyncMock),
            patch("gateway.main.close_db", new_callable=AsyncMock),
            patch("gateway.main.get_session_factory", return_value=AsyncMock()),
            patch("gateway.main._mcp_session_manager", None),
            patch("gateway.connectors.health_monitor.health_monitor.load_from_db", new_callable=AsyncMock),
            patch("gateway.auth.jwt_secret.load_session_jwt_secret", return_value=_TEST_SECRET),
            patch("gateway.auth.notebook_jwt.load_session_jwt_secret", return_value=_TEST_SECRET),
            patch("gateway.store.notebook_sessions.get_session_by_id", AsyncMock(return_value=None)),
            # The middleware's eval-credential probe needs a DB; inert here.
            patch(
                "gateway.http.middleware.auth._eval_credentials_active",
                AsyncMock(return_value=False),
            ),
        )
        with (
            app_patches[0], app_patches[1], app_patches[2], app_patches[3],
            app_patches[4], app_patches[5], app_patches[6], app_patches[7],
            app_patches[8],
        ):
            client = TestClient(app, raise_server_exceptions=False)
            with client:
                return client.request(method, f"/api/notebook-sessions/{session_id}")

    def test_cross_org_get_returns_404(self, monkeypatch):
        self._client("org-b", "user-b")
        try:
            resp = self._request("GET", str(uuid.uuid4()))
            assert resp.status_code == 404
        finally:
            self._cleanup()

    def test_cross_org_delete_returns_404(self, monkeypatch):
        self._client("org-b", "user-b")
        try:
            resp = self._request("DELETE", str(uuid.uuid4()))
            assert resp.status_code == 404
        finally:
            self._cleanup()


class TestLaunchCredentials:
    """Launch credentials: JWT in the boot process env only, token via
    write_file, nothing secret in the sandbox creation spec."""

    @pytest.mark.asyncio
    async def test_session_jwt_rides_process_env_not_spec(self, monkeypatch):
        from gateway.config.notebooks import NotebookSettings
        from gateway.notebooks.backends import LaunchRequest, VercelNotebookBackend

        runtime = AsyncMock()
        runtime.create.return_value = "sbx-x"
        runtime.exec.return_value = SimpleNamespace(ok=True, stdout="", stderr="")
        runtime.routes.return_value = {2718: "https://sbx-x.vercel.run"}
        runtime.start_process.return_value = "proc-1"

        monkeypatch.setenv("SP_NOTEBOOK_VERCEL_IMAGE", "reg/sp-notebook:dev")
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        backend = VercelNotebookBackend(NotebookSettings(), runtime=runtime)
        launch = await backend.launch(
            LaunchRequest(
                org_id="org-1",
                user_id="user-1",
                session_id="sess-abc",
                project_id="proj-1",
                branch="main",
                session_jwt="jwt.value.here",
                notebook_token="nb-token",
            )
        )
        assert launch.upstream_url == "https://sbx-x.vercel.run"

        spec = runtime.create.await_args.args[0]
        assert spec.env == {}  # creation metadata is provider-readable: no secrets
        assert 2718 in spec.ports
        assert spec.tags["sp-purpose"] == "notebook"

        # The token rides the process env (never the creation spec); the boot
        # command stages it into the 0400 token file and unsets it before
        # exec'ing the server. No provider write_file on the critical path.
        runtime.write_file.assert_not_awaited()

        process_env = runtime.start_process.await_args.kwargs["env"]
        assert process_env["SP_SESSION_JWT"] == "jwt.value.here"
        assert process_env["SP_SESSION_ID"] == "sess-abc"
        assert process_env["SP_NOTEBOOK_TOKEN"] == "nb-token"
        assert "SP_API_KEY" not in process_env

    @pytest.mark.asyncio
    async def test_launch_failure_destroys_the_sandbox(self, monkeypatch):
        from gateway.config.notebooks import NotebookSettings
        from gateway.notebooks.backends import LaunchRequest, NotebookLaunchError, VercelNotebookBackend

        runtime = AsyncMock()
        runtime.create.return_value = "sbx-x"
        runtime.start_process.return_value = "proc-1"
        runtime.exec.return_value = SimpleNamespace(ok=False, stdout="", stderr="connection refused")

        monkeypatch.setenv("SP_NOTEBOOK_VERCEL_IMAGE", "reg/sp-notebook:dev")
        monkeypatch.setenv("SP_NOTEBOOK_START_TIMEOUT_SECONDS", "30")
        settings = NotebookSettings()
        object.__setattr__(settings, "start_timeout_seconds", 0)  # fail immediately
        backend = VercelNotebookBackend(settings, runtime=runtime)
        with pytest.raises(NotebookLaunchError):
            await backend.launch(
                LaunchRequest(
                    org_id="o", user_id="u", session_id="s", project_id=None,
                    branch="main", session_jwt="j", notebook_token="t",
                )
            )
        runtime.destroy.assert_awaited_once_with("sbx-x")


class TestProjectAuthorizationBeforeProvisioning:
    """Project-backed sessions resolve the project in the caller's org first."""

    @pytest.mark.asyncio
    async def test_missing_or_cross_org_project_returns_404_before_provisioning(
        self, monkeypatch
    ):
        from gateway.api import notebook_sessions as ns_api
        from gateway.models.notebook_sessions import NotebookSessionCreate

        store = _make_mock_store(org_id="org-b", user_id="user-b")
        store.get_workspace_project.return_value = None
        ensure_session = AsyncMock()
        monkeypatch.setattr(ns_api.session_service, "ensure_notebook_session", ensure_session)

        with pytest.raises(HTTPException) as exc_info:
            await ns_api.create_session(
                NotebookSessionCreate(project_id="project-from-org-a", branch="main"),
                store,
                _make_mock_response(),
            )

        assert exc_info.value.status_code == 404
        store.get_workspace_project.assert_awaited_once_with("project-from-org-a")
        ensure_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_same_org_project_is_resolved_before_recipient_session(
        self, monkeypatch
    ):
        from gateway.api import notebook_sessions as ns_api
        from gateway.models.notebook_sessions import NotebookSessionCreate

        store = _make_mock_store(org_id="org-1", user_id="recipient-user")
        store.get_workspace_project.return_value = MagicMock(id="project-1")
        recipient_session = _session_info(
            id="recipient-session", user_id="recipient-user", branch="feature/share"
        )
        ensure_session = AsyncMock(return_value=recipient_session)
        monkeypatch.setattr(ns_api.session_service, "ensure_notebook_session", ensure_session)

        result = await ns_api.create_session(
            NotebookSessionCreate(project_id="project-1", branch="feature/share"),
            store,
            _make_mock_response(),
        )

        assert result == recipient_session
        store.get_workspace_project.assert_awaited_once_with("project-1")
        ensure_session.assert_awaited_once_with(
            store.session,
            org_id="org-1",
            user_id="recipient-user",
            project_id="project-1",
            branch="feature/share",
        )


class TestSessionLifecycleService:
    """ensure_notebook_session: reuse, recreate, resume, launch wiring."""

    @pytest.mark.asyncio
    async def test_session_reuse_when_runtime_alive(self, svc, monkeypatch):
        _patch_jwt_secret(monkeypatch)
        from gateway.notebooks import session_service as service

        backend = FakeBackend()
        svc.get_active_session.return_value = _session_info()

        result = await service.ensure_notebook_session(
            AsyncMock(),
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            backend=backend,
        )
        assert result.id == "sess-1"
        assert backend.launches == []  # reused, not relaunched

    @pytest.mark.asyncio
    async def test_session_recreated_when_runtime_dead(self, svc, monkeypatch):
        _patch_jwt_secret(monkeypatch)
        from gateway.notebooks import session_service as service

        backend = FakeBackend()
        backend.alive = False
        svc.get_active_session.return_value = _session_info(id="dead-sess")
        svc.create_session.return_value = _session_info(id="new-sess", status="creating")

        result = await service.ensure_notebook_session(
            AsyncMock(),
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            backend=backend,
        )
        assert result.id == "new-sess"
        assert backend.terminated == ["sbx-live"]  # dead runtime torn down
        assert len(backend.launches) == 1
        svc.mark_stopped.assert_awaited()

    @pytest.mark.asyncio
    async def test_snapshotted_session_resumes_in_place(self, svc, monkeypatch):
        _patch_jwt_secret(monkeypatch)
        from gateway.notebooks import session_service as service

        backend = FakeBackend()
        svc.get_active_session.return_value = _session_info(status="snapshotted")
        svc.get_session_internal.return_value = _internal(
            status="snapshotted", snapshot_id="snap-9", upstream_url=None
        )
        svc.get_session_by_id = AsyncMock(return_value=_session_info(status="running"))
        monkeypatch.setattr(
            "gateway.store.notebook_sessions.get_session_by_id", svc.get_session_by_id
        )

        result = await service.ensure_notebook_session(
            AsyncMock(),
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            backend=backend,
        )
        assert result.status == "running"
        assert len(backend.resumed) == 1
        resumed_handle, resume_request = backend.resumed[0]
        assert resumed_handle == "sbx-live"
        assert resume_request.session_id == "sess-1"
        assert resume_request.notebook_token == "tok-1"
        assert resume_request.snapshot_url is None
        assert backend.launches == []
        update_kwargs = svc.update_session_runtime.await_args.kwargs
        assert update_kwargs["upstream_url"] == "https://resumed.vercel.run"

    @pytest.mark.asyncio
    async def test_hung_resume_falls_back_to_fresh_launch(self, svc, monkeypatch):
        _patch_jwt_secret(monkeypatch)
        from gateway.notebooks import session_service as service

        backend = FakeBackend()
        svc.get_active_session.return_value = _session_info(status="snapshotted")
        svc.get_session_internal.return_value = _internal(
            status="snapshotted", snapshot_id="snap-9", upstream_url=None
        )
        svc.create_session.return_value = _session_info(id="fresh-sess", status="creating")

        async def hung_resume(_runtime_handle, _request):
            await asyncio.Event().wait()

        monkeypatch.setattr(backend, "resume", hung_resume)
        monkeypatch.setattr(service, "_NOTEBOOK_RESUME_TIMEOUT_SECONDS", 0.01)

        result = await service.ensure_notebook_session(
            AsyncMock(),
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            backend=backend,
        )

        assert result.id == "fresh-sess"
        assert backend.terminated == ["sbx-live"]
        assert len(backend.launches) == 1

    @pytest.mark.asyncio
    async def test_project_or_branch_switch_replaces_the_session(self, svc, monkeypatch):
        _patch_jwt_secret(monkeypatch)
        from gateway.notebooks import session_service as service

        backend = FakeBackend()
        svc.get_active_session.return_value = _session_info(branch="other-branch")
        svc.create_session.return_value = _session_info(id="new-sess", status="creating")

        result = await service.ensure_notebook_session(
            AsyncMock(),
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            backend=backend,
        )
        assert result.id == "new-sess"
        assert backend.terminated == ["sbx-live"]

    @pytest.mark.asyncio
    async def test_launch_receives_valid_session_jwt(self, svc, monkeypatch):
        _patch_jwt_secret(monkeypatch)
        from gateway.notebooks import session_service as service

        backend = FakeBackend()
        await service.ensure_notebook_session(
            AsyncMock(),
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            backend=backend,
        )
        (request,) = backend.launches
        claims = verify_session_jwt(request.session_jwt)
        assert claims["sub"] == "user-1"
        assert claims["org_id"] == "org-1"
        assert request.notebook_token  # minted by the store

    @pytest.mark.asyncio
    async def test_writer_session_takes_the_branch_lease(self, svc, monkeypatch):
        _patch_jwt_secret(monkeypatch)
        from gateway.notebooks import session_service as service

        backend = FakeBackend()
        await service.ensure_notebook_session(
            AsyncMock(),
            org_id="org-1",
            user_id="user-1",
            project_id="proj-1",
            branch="main",
            backend=backend,
        )
        service.acquire_lease.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_read_only_session_never_takes_a_lease(self, svc, monkeypatch):
        _patch_jwt_secret(monkeypatch)
        from gateway.notebooks import session_service as service

        backend = FakeBackend()
        await service.ensure_notebook_session(
            AsyncMock(),
            org_id="org-1",
            user_id="chat:run-1",
            project_id="proj-1",
            branch="main",
            read_only=True,
            backend=backend,
        )
        service.acquire_lease.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_launch_failure_marks_error_and_releases_lease(self, svc, monkeypatch):
        _patch_jwt_secret(monkeypatch)
        from gateway.notebooks import session_service as service

        backend = FakeBackend()
        backend.launch_error = RuntimeError("provider down")

        with pytest.raises(service.NotebookSessionError):
            await service.ensure_notebook_session(
                AsyncMock(),
                org_id="org-1",
                user_id="user-1",
                project_id="proj-1",
                branch="main",
                backend=backend,
            )
        statuses = [c.kwargs.get("status") for c in svc.update_session_runtime.await_args_list]
        assert "error" in statuses
        service.release_lease.assert_awaited()

    @pytest.mark.asyncio
    async def test_launch_timeout_marks_session_error(self, svc, monkeypatch):
        _patch_jwt_secret(monkeypatch)
        from gateway.notebooks import session_service as service

        backend = FakeBackend()

        async def hung_launch(_request):
            await asyncio.Event().wait()

        monkeypatch.setattr(backend, "launch", hung_launch)
        monkeypatch.setattr(service, "_NOTEBOOK_LAUNCH_TIMEOUT_SECONDS", 0.01)

        with pytest.raises(service.NotebookSessionError, match="TimeoutError"):
            await service.ensure_notebook_session(
                AsyncMock(),
                org_id="org-1",
                user_id="user-1",
                project_id="proj-1",
                branch="main",
                backend=backend,
            )

        statuses = [c.kwargs.get("status") for c in svc.update_session_runtime.await_args_list]
        assert "error" in statuses
        service.release_lease.assert_awaited()


class TestOrgEnforcement:
    """Organization propagation and budget enforcement."""

    @pytest.mark.asyncio
    async def test_create_session_empty_org_id_returns_400(self, monkeypatch):
        _patch_jwt_secret(monkeypatch)

        from gateway.api import notebook_sessions as ns_api
        from gateway.models.notebook_sessions import NotebookSessionCreate

        store = _make_mock_store(org_id="", user_id="user-1")

        with pytest.raises(HTTPException) as exc_info:
            await ns_api.create_session(
                NotebookSessionCreate(project_id="proj-1", branch="main"),
                store,
                _make_mock_response(),
            )
        assert exc_info.value.status_code == 400
        assert "org_id" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_org_budget_exhausted_raises_quota_error(self, svc, monkeypatch):
        _patch_jwt_secret(monkeypatch)
        from gateway.notebooks import session_service as service

        backend = FakeBackend()
        svc.count_running_for_org.return_value = 10_000

        with pytest.raises(service.NotebookQuotaExceededError):
            await service.ensure_notebook_session(
                AsyncMock(),
                org_id="org-1",
                user_id="user-1",
                project_id="proj-1",
                branch="main",
                backend=backend,
            )
        assert backend.launches == []

    @pytest.mark.asyncio
    async def test_quota_error_maps_to_429(self, monkeypatch):
        from gateway.api import notebook_sessions as ns_api
        from gateway.models.notebook_sessions import NotebookSessionCreate
        from gateway.notebooks.session_service import NotebookQuotaExceededError

        store = _make_mock_store()
        store.get_workspace_project.return_value = MagicMock(id="proj-1")
        monkeypatch.setattr(
            ns_api.session_service,
            "ensure_notebook_session",
            AsyncMock(side_effect=NotebookQuotaExceededError("full")),
        )
        with pytest.raises(HTTPException) as exc_info:
            await ns_api.create_session(
                NotebookSessionCreate(project_id="proj-1", branch="main"),
                store,
                _make_mock_response(),
            )
        assert exc_info.value.status_code == 429


class TestLocalAPIKeyAuth:
    """sp_-prefixed local API key still authenticates end-to-end."""

    @pytest.mark.asyncio
    async def test_sp_prefix_key_with_auth_state_resolves_correctly(self, monkeypatch):
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


class TestTerminateSession:
    """delete paths release compute, the lease, and mark the row stopped."""

    @pytest.mark.asyncio
    async def test_terminate_releases_runtime_lease_and_marks_stopped(self, svc, monkeypatch):
        from gateway.notebooks import session_service as service

        backend = FakeBackend()
        await service.terminate_session(
            AsyncMock(), session_info=_session_info(), backend=backend
        )
        assert backend.terminated == ["sbx-live"]
        service.release_lease.assert_awaited_once()
        svc.mark_stopped.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_endpoint_terminates(self, monkeypatch):
        from gateway.api import notebook_sessions as ns_api
        from gateway.store import notebook_sessions as ns_store

        session = _session_info()
        monkeypatch.setattr(ns_store, "get_active_session", AsyncMock(return_value=session))
        terminate = AsyncMock()
        monkeypatch.setattr(ns_api.session_service, "terminate_session", terminate)

        await ns_api.delete_session(_make_mock_store(), _make_mock_response())
        terminate.assert_awaited_once()
        assert terminate.await_args.kwargs["session_info"] == session


class TestStandaloneChatWarmSession:
    """A warm notebook is conversation-scoped, never frozen to its first run."""

    @pytest.mark.asyncio
    async def test_session_launch_contains_only_conversation_stable_scope(
        self, monkeypatch
    ):
        from gateway.notebooks import session_service as service

        selected = SimpleNamespace(id="session-a")
        ensure = AsyncMock(return_value=selected)
        runtime = SimpleNamespace(session_id="session-a")
        monkeypatch.setattr(service, "ensure_notebook_session", ensure)
        monkeypatch.setattr(
            service, "runtime_for_session", AsyncMock(return_value=runtime)
        )

        result = await service.ensure_standalone_chat_notebook_session(
            AsyncMock(),
            org_id="org-a",
            user_id="user-a",
            conversation_id="conversation-a",
            project_id="project-a",
            branch="main",
            connection_name="production",
            commit_sha="a" * 40,
        )

        assert result is runtime
        kwargs = ensure.await_args.kwargs
        assert kwargs["user_id"] == "chat:conv-conversation-a"
        assert kwargs["extra_env"] == {
            "SP_CHAT_PROJECT_ID": "project-a",
            "SP_CHAT_BRANCH": "main",
            "SP_CHAT_CONNECTION_NAME": "production",
            "SP_CHAT_COMMIT_SHA": "a" * 40,
            "SP_PROJECT_COMMIT_SHA": "a" * 40,
        }
        assert "SP_CHAT_RUN_ID" not in kwargs["extra_env"]
