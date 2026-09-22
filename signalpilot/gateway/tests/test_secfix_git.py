"""Security fixes 2026-09-15: git smart-HTTP scope, eval binding and body limits.

SP-04: reads require the read scope, eval-bound keys are refused, and a
       notebook-session token's scopes are capped to the REST allowlist.
SP-10: request bodies are capped for reads and writes, and gzip bodies are
       inflated incrementally so a bomb aborts at the ceiling.

The handler runs in a small FastAPI app with ``_authenticate`` and the repo
checks stubbed; ``git http-backend`` is replaced by a fake process so the
tests prove what reaches it.
"""

from __future__ import annotations

import gzip
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.git import http_server
from gateway.http.middleware.body_size import RequestBodySizeLimitMiddleware

PROJECT = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
UPLOAD = f"/git/{PROJECT}.git/git-upload-pack"
RECEIVE = f"/git/{PROJECT}.git/git-receive-pack"
_TEST_SECRET = "test-secret-for-git-secfix"


@pytest.fixture
def git_app(monkeypatch, tmp_path):
    """The git router with auth, repo lookup and the CGI process stubbed."""
    state = {"auth": {"user_id": "u1", "org_id": "org-1", "scopes": ["read", "write"], "auth_method": "api_key"}}
    seen: list[bytes] = []

    async def fake_authenticate(request):
        return dict(state["auth"])

    async def fake_authorize(auth, project_id):
        return None

    def fake_run(argv, *, input, capture_output, env, timeout):
        seen.append(input)
        return SimpleNamespace(
            returncode=0,
            stdout=b"Content-Type: application/x-git-upload-pack-result\r\n\r\nPACK",
            stderr=b"",
        )

    monkeypatch.setattr(http_server, "_authenticate", fake_authenticate)
    monkeypatch.setattr(http_server, "_authorize_project", fake_authorize)
    monkeypatch.setattr(http_server, "repo_exists", lambda project_id: True)
    monkeypatch.setattr(http_server, "REPOS_ROOT", tmp_path)
    monkeypatch.setattr(http_server, "repo_path", lambda project_id: tmp_path / f"{project_id}.git")
    monkeypatch.setattr(http_server.subprocess, "run", fake_run)
    monkeypatch.setattr(http_server, "_MAX_UPLOAD_PACK_BYTES", 4096)
    monkeypatch.setattr(http_server, "_MAX_PUSH_BYTES", 8192)

    app = FastAPI()
    app.include_router(http_server.router)
    return SimpleNamespace(client=TestClient(app, raise_server_exceptions=False), state=state, seen=seen)


# ── SP-04 ────────────────────────────────────────────────────────────────────


class TestGitScopes:
    def test_read_scope_clones(self, git_app):
        response = git_app.client.post(UPLOAD, content=b"0000")
        assert response.status_code == 200, response.text
        assert git_app.seen == [b"0000"]

    def test_query_only_key_cannot_read(self, git_app):
        git_app.state["auth"]["scopes"] = ["query"]
        response = git_app.client.post(UPLOAD, content=b"0000")
        assert response.status_code == 403
        assert response.json()["detail"] == "Read access required"
        assert git_app.seen == []

    def test_query_only_key_cannot_advertise_refs(self, git_app):
        git_app.state["auth"]["scopes"] = ["query"]
        response = git_app.client.get(f"/git/{PROJECT}.git/info/refs?service=git-upload-pack")
        assert response.status_code == 403

    def test_eval_bound_key_is_refused(self, git_app):
        git_app.state["auth"]["eval_run_id"] = "run-1"
        response = git_app.client.post(UPLOAD, content=b"0000")
        assert response.status_code == 403
        assert response.json()["detail"] == "Eval credentials cannot access git"
        assert git_app.client.post(RECEIVE, content=b"0000").status_code == 403

    def test_write_still_requires_write_scope(self, git_app):
        git_app.state["auth"]["scopes"] = ["read"]
        assert git_app.client.post(RECEIVE, content=b"0000").status_code == 403
        git_app.state["auth"]["scopes"] = ["read", "write"]
        assert git_app.client.post(RECEIVE, content=b"0000").status_code == 200


class TestAuthenticateNotebookToken:
    @pytest.fixture
    def no_stored_keys(self, monkeypatch):
        monkeypatch.setattr("gateway.auth.notebook_jwt.load_session_jwt_secret", lambda: _TEST_SECRET)
        monkeypatch.setattr("gateway.auth.jwt_secret._cached_secret", _TEST_SECRET)
        monkeypatch.setattr("gateway.store.get_local_api_key", lambda: None)

        @asynccontextmanager
        async def session():
            yield object()

        monkeypatch.setattr("gateway.db.engine.get_session_factory", lambda: session)

        async def no_match(self, token):
            return None

        monkeypatch.setattr("gateway.store.Store.validate_stored_api_key", no_match)

    @pytest.mark.asyncio
    async def test_session_scopes_are_capped_to_rest_allowlist(self, no_stored_keys):
        import base64

        from gateway.auth.notebook_jwt import mint_session_jwt

        token = mint_session_jwt(
            user_id="u1",
            org_id="org-1",
            session_id="s1",
            project_id="p1",
            branch="main",
            connection_name="warehouse",
            commit_sha="a" * 40,
            capabilities=["query:read"],
            ttl=600,
            execution_identity="chat:run-1",
            scopes=["read", "query", "execute", "write", "admin"],
        )
        header = "Basic " + base64.b64encode(f"git:{token}".encode()).decode()
        request = SimpleNamespace(headers={"authorization": header})
        auth = await http_server._authenticate(request)
        assert auth["auth_method"] == "notebook_session"
        assert auth["org_id"] == "org-1"
        assert sorted(auth["scopes"]) == ["execute", "query", "read", "write"]
        assert "admin" not in auth["scopes"]


# ── SP-10 ────────────────────────────────────────────────────────────────────


class TestGitBodyLimits:
    def test_read_body_over_cap_is_rejected(self, git_app):
        response = git_app.client.post(UPLOAD, content=b"x" * 4097)
        assert response.status_code == 413
        assert git_app.seen == []

    def test_read_body_at_cap_is_served(self, git_app):
        assert git_app.client.post(UPLOAD, content=b"x" * 4096).status_code == 200

    def test_push_keeps_its_own_larger_cap(self, git_app):
        assert git_app.client.post(RECEIVE, content=b"x" * 5000).status_code == 200
        response = git_app.client.post(RECEIVE, content=b"x" * 8193)
        assert response.status_code == 413
        assert response.json()["detail"] == "Push too large"

    def test_gzip_body_is_inflated_for_backend(self, git_app):
        body = gzip.compress(b"0032want " + b"a" * 40 + b"\n0000")
        response = git_app.client.post(UPLOAD, content=body, headers={"Content-Encoding": "gzip"})
        assert response.status_code == 200, response.text
        assert git_app.seen[0].startswith(b"0032want ")

    def test_gzip_bomb_aborts_at_ceiling(self, git_app):
        bomb = gzip.compress(b"\0" * (3 * 1024 * 1024))
        assert len(bomb) < 4096  # small on the wire, 3 MiB inflated (cap is 4 KiB)
        response = git_app.client.post(UPLOAD, content=bomb, headers={"Content-Encoding": "gzip"})
        assert response.status_code == 413
        assert git_app.seen == []

    def test_deflate_bomb_aborts_on_push_too(self, git_app):
        import zlib

        bomb = zlib.compress(b"\0" * (50 * 1024 * 1024))
        response = git_app.client.post(RECEIVE, content=bomb, headers={"Content-Encoding": "deflate"})
        assert response.status_code == 413
        assert response.json()["detail"] == "Push too large"

    def test_truncated_gzip_is_malformed(self, git_app):
        body = gzip.compress(b"0000" * 100)[:-8]
        response = git_app.client.post(UPLOAD, content=body, headers={"Content-Encoding": "gzip"})
        assert response.status_code == 400


class TestBodySizeMiddlewareGitPaths:
    """The middleware caps git bytes on the wire instead of exempting /git/."""

    @pytest.fixture
    def app(self, monkeypatch):
        monkeypatch.setattr(http_server, "_MAX_UPLOAD_PACK_BYTES", 1024)
        monkeypatch.setattr(http_server, "_MAX_PUSH_BYTES", 4096)
        app = FastAPI()

        @app.post("/git/{project_id}.git/{remainder:path}")
        async def sink(project_id: str, remainder: str):
            return {"ok": True}

        app.add_middleware(RequestBodySizeLimitMiddleware, max_body_bytes=16)
        return TestClient(app, raise_server_exceptions=False)

    def test_upload_pack_uses_read_limit(self, app):
        assert app.post(UPLOAD, content=b"x" * 1024).status_code == 200
        assert app.post(UPLOAD, content=b"x" * 1025).status_code == 413

    def test_receive_pack_uses_push_limit(self, app):
        assert app.post(RECEIVE, content=b"x" * 4096).status_code == 200
        assert app.post(RECEIVE, content=b"x" * 4097).status_code == 413

    def test_push_detected_from_query_string(self, app):
        path = f"/git/{PROJECT}.git/info/refs?service=git-receive-pack"
        assert app.post(path, content=b"x" * 2048).status_code == 200
