"""Security fixes 2026-09-15: redirects, CSP precedence, dev key, hygiene, docs.

SP-22: backslash open redirect in the OAuth return-URL validators.
SP-24: the security-headers middleware keeps a route-set CSP.
SP-28: the public docker-compose dev Fernet key is refused in cloud mode.
SP-32: read_notebook uses an org-scoped store; download filenames are encoded.
SP-33: API docs are not public in cloud mode.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

# ── SP-22 ────────────────────────────────────────────────────────────────────


class TestBackslashRedirects:
    @pytest.fixture(autouse=True)
    def web(self, monkeypatch):
        monkeypatch.setenv("SP_WEB_URL", "https://app.example.test")

    @pytest.mark.parametrize("bad", ["/\\evil.com", "/\\\\evil.com", "/ok\\..", "https://app.example.test/\\evil"])
    def test_connector_signin_falls_back(self, bad):
        from gateway.api.mcp.oauth import safe_return_url

        url = safe_return_url(bad, connector_id="c1", signin="ok")
        assert url.startswith("https://app.example.test/settings/connectors?")
        assert "evil" not in url

    def test_connector_signin_keeps_plain_paths(self):
        from gateway.api.mcp.oauth import safe_return_url

        url = safe_return_url("/chats/abc?x=1", connector_id="c1", signin="ok")
        assert url == "https://app.example.test/chats/abc?x=1&connector=c1&signin=ok"

    def test_connector_signin_rejects_scheme_relative(self):
        from gateway.api.mcp.oauth import safe_return_url

        assert "evil" not in safe_return_url("//evil.com/x", connector_id="c1", signin="ok")

    @pytest.mark.parametrize("module", ["gateway.api.notion", "gateway.api.slack"])
    def test_integration_validators_reject_backslash(self, module):
        import importlib

        is_safe = importlib.import_module(module)._is_safe_redirect_target
        assert is_safe("/integrations") is True
        assert is_safe("/integrations?x=1") is True
        assert is_safe("/\\evil.com") is False
        assert is_safe("/x\\y") is False
        assert is_safe("//evil.com") is False
        assert is_safe("\\evil.com") is False


# ── SP-24 ────────────────────────────────────────────────────────────────────


class TestRouteCspIsKept:
    @pytest.fixture
    def client(self):
        from gateway.http.middleware.security_headers import SecurityHeadersMiddleware

        app = FastAPI()

        @app.get("/own")
        async def own():
            return Response("<html/>", headers={"Content-Security-Policy": "default-src 'none'; connect-src 'none'"})

        @app.get("/plain")
        async def plain():
            return Response("ok")

        @app.get("/notebook/sid/x")
        async def proxy():
            return Response("ok", headers={"Content-Security-Policy": "upstream"})

        app.add_middleware(SecurityHeadersMiddleware)
        return TestClient(app)

    def test_route_policy_survives(self, client):
        assert client.get("/own").headers["content-security-policy"] == "default-src 'none'; connect-src 'none'"

    def test_default_policy_when_absent(self, client):
        csp = client.get("/plain").headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_proxy_paths_unchanged(self, client):
        assert client.get("/notebook/sid/x").headers["content-security-policy"].startswith("frame-ancestors 'self'")


# ── SP-28 ────────────────────────────────────────────────────────────────────

DEV_KEY = "5d1aa5ETRcln8vkPWrzDkdfSEuqAua5xcZCWMLMDXmc="


class TestDevKeyRefusedInCloud:
    def test_compose_literal_matches(self):
        from pathlib import Path

        from gateway.store.crypto import _WELL_KNOWN_DEV_KEY

        compose = Path(__file__).resolve().parents[3] / "docker-compose.yml"
        if not compose.exists():
            pytest.skip("docker-compose.yml not in this checkout")
        assert f"SP_ENCRYPTION_KEY: {_WELL_KNOWN_DEV_KEY}" in compose.read_text(encoding="utf-8")

    def test_cloud_mode_refuses_dev_key(self, monkeypatch):
        from gateway.store.crypto import _get_encryption_key

        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_ENCRYPTION_KEY", DEV_KEY)
        with pytest.raises(RuntimeError, match="docker-compose dev key"):
            _get_encryption_key()

    def test_cloud_mode_accepts_private_key(self, monkeypatch):
        from gateway.store.crypto import _get_encryption_key

        key = Fernet.generate_key().decode()
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_ENCRYPTION_KEY", key)
        assert _get_encryption_key() == key.encode()

    def test_local_mode_still_accepts_dev_key(self, monkeypatch):
        from gateway.store.crypto import _get_encryption_key

        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        monkeypatch.setenv("SP_ENCRYPTION_KEY", DEV_KEY)
        assert _get_encryption_key() == DEV_KEY.encode()


# ── SP-32 ────────────────────────────────────────────────────────────────────


class TestReadNotebookOrgScoped:
    def test_store_is_scoped_to_the_caller_org(self, monkeypatch):
        from gateway.mcp.context import mcp_org_id_var, mcp_scopes_var, mcp_user_id_var
        from gateway.mcp.tools.notebook import read_notebook

        captured: dict = {}

        class FakeStore:
            def __init__(self, session, org_id=None, user_id=None, allow_unscoped=False, **_):
                captured.update(org_id=org_id, user_id=user_id, allow_unscoped=allow_unscoped)

            async def list_workspace_projects(self, **kwargs):
                return [], 0

        @asynccontextmanager
        async def session():
            yield object()

        monkeypatch.setattr("gateway.store.Store", FakeStore)
        monkeypatch.setattr("gateway.db.engine.get_session_factory", lambda: session)
        monkeypatch.setattr("gateway.api.workspace_files.get_workspace_store", lambda: object())
        org_token = mcp_org_id_var.set("org-42")
        user_token = mcp_user_id_var.set("user-7")
        scopes_token = mcp_scopes_var.set(["read"])
        try:
            result = asyncio.run(read_notebook("analysis.py"))
        finally:
            mcp_org_id_var.reset(org_token)
            mcp_user_id_var.reset(user_token)
            mcp_scopes_var.reset(scopes_token)
        assert result.startswith("Error: signalpilot-agent/analysis.py not found")
        assert captured == {"org_id": "org-42", "user_id": "user-7", "allow_unscoped": False}


class TestDownloadFilenamesAreEncoded:
    def test_eval_artifact_filename(self, monkeypatch):
        from gateway.api import eval_runs

        class FakeObjects:
            def artifact_key(self, org_id, run_id, task_id, filename):
                return f"{org_id}/{run_id}/{task_id}/{filename}"

            async def get_bytes(self, key):
                return b"data"

        monkeypatch.setattr(eval_runs, "_object_store_or_422", lambda: FakeObjects())
        store = SimpleNamespace(org_id="org-1")
        hostile = 'evil"; filename="x.html\r\nX-Injected: 1'
        response = asyncio.run(
            eval_runs.download_eval_artifact(store, "run-20260915-120000-abcdef", "task-1", hostile)
        )
        disposition = response.headers["content-disposition"]
        assert disposition == (
            'attachment; filename="evil__ filename=_x.html__X-Injected: 1"; '
            "filename*=UTF-8''evil%22%3B%20filename%3D%22x.html%0D%0AX-Injected%3A%201"
        )
        assert "\r" not in disposition and "\n" not in disposition
        assert disposition.count('"') == 2  # only the quoted-string delimiters survive


# ── SP-33 ────────────────────────────────────────────────────────────────────
