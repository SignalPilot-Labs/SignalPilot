"""SP-12: GET /api/github/credentials/{project_id} returns a live installation
token with push rights, so it is gated on the write scope, not read."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from gateway.api import github as github_api
from gateway.api.deps import get_store
from gateway.security import scope_guard

_AUTH: dict = {"auth_method": "api_key", "user_id": "u", "scopes": []}


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()

    @app.middleware("http")
    async def _inject_auth(request: Request, call_next):
        request.state.auth = dict(_AUTH)
        return await call_next(request)

    app.include_router(github_api.router)
    app.dependency_overrides[scope_guard._resolve_user_id] = lambda: "u"
    app.dependency_overrides[get_store] = lambda: SimpleNamespace(org_id="org-a", session=object())

    from gateway.store import github as gh_store

    # Unlinked project -> "managed" response; no token handling exercised.
    monkeypatch.setattr(gh_store, "get_repo_link_for_project", AsyncMock(return_value=None))
    with TestClient(app) as c:
        yield c


def _scopes(*scopes: str) -> None:
    _AUTH["scopes"] = list(scopes)


def test_read_only_key_is_refused(client):
    _scopes("read")
    resp = client.get("/api/github/credentials/proj-1")
    assert resp.status_code == 403


def test_execute_only_key_is_refused(client):
    _scopes("execute")
    assert client.get("/api/github/credentials/proj-1").status_code == 403


def test_write_key_is_allowed(client):
    _scopes("read", "write")
    resp = client.get("/api/github/credentials/proj-1")
    assert resp.status_code == 200
    assert resp.json()["source"] == "managed"


def test_notebook_session_token_keeps_working(client):
    """Notebook/chat pod tokens carry read+write and must still fetch creds."""
    _AUTH.update({"auth_method": "notebook_session", "scopes": ["read", "write"]})
    try:
        assert client.get("/api/github/credentials/proj-1").status_code == 200
    finally:
        _AUTH.update({"auth_method": "api_key", "scopes": []})
