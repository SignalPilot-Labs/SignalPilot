"""MCP tool wrappers and REST routes for the agent pull request lifecycle.

The store-level behaviour is covered in test_agent_pr.py; here the
agent_pr functions are faked and only the bindings, error passthrough,
response shapes, scopes, and audit events are checked.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from gateway.git import agent_pr
from gateway.store import github_prs

ORG = "org-a"
PROJECT = "proj-1"
REPO = "acme/dbt"
TOKEN = "ghs_secretInstallationToken123"


# MCP wrappers.


def _set_vars(mcp_context, *extra):
    variables = [
        (mcp_context.mcp_org_id_var, ORG),
        (mcp_context.mcp_user_id_var, "u"),
        (mcp_context.mcp_scopes_var, ["read", "query", "execute", "write"]),
        *extra,
    ]
    tokens = [var.set(value) for var, value in variables]

    def reset():
        for (var, _), tok in zip(variables, tokens, strict=True):
            var.reset(tok)

    return reset


def _chat_vars(mcp_context):
    return _set_vars(
        mcp_context,
        (mcp_context.mcp_execution_identity_var, "chat:run-9"),
        (mcp_context.mcp_project_id_var, PROJECT),
        (mcp_context.mcp_branch_var, "signalpilot-agent/chat-9"),
    )


def _fn(tool):
    return getattr(tool, "fn", tool)


@pytest.fixture
def mcp_env(monkeypatch):
    from gateway.mcp import context as mcp_context
    from gateway.mcp.tools import comment_on_pull_request as comment_mod
    from gateway.mcp.tools import open_pull_request as open_mod
    from gateway.mcp.tools import update_pull_request as update_mod

    async def fake_conv(session, run_id, org_id):
        assert run_id == "run-9" and org_id == ORG
        return "conv-9"

    @asynccontextmanager
    async def fake_store(user_id=None, org_id=None):
        yield SimpleNamespace(session=object())

    for mod in (open_mod, update_mod, comment_mod):
        monkeypatch.setattr(mod, "conversation_for_run", fake_conv)
        monkeypatch.setattr(mod, "_store_session", fake_store)
    return SimpleNamespace(context=mcp_context, open=open_mod, update=update_mod, comment=comment_mod)


async def test_mcp_tools_require_chat_identity(mcp_env):
    reset = _set_vars(mcp_env.context, (mcp_env.context.mcp_execution_identity_var, "user:u"))
    try:
        assert "chat execution identity" in (await _fn(mcp_env.open.open_pull_request)(title="x"))["error"]
        assert "chat execution identity" in (await _fn(mcp_env.update.update_pull_request)(title="x"))["error"]
        assert "chat execution identity" in (await _fn(mcp_env.comment.comment_on_pull_request)(body="x"))["error"]
    finally:
        reset()


async def test_mcp_open_passes_conversation_and_branch(mcp_env, monkeypatch):
    seen: dict = {}

    async def fake_open(session, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(pr_url="u", pr_number=5, github_branch="signalpilot/x", draft=True)

    monkeypatch.setattr("gateway.git.agent_pr.open_pull_request", fake_open)
    reset = _chat_vars(mcp_env.context)
    try:
        result = await _fn(mcp_env.open.open_pull_request)(
            title="Add mart", body="models: fct_x", draft=True, branch="signalpilot/x"
        )
    finally:
        reset()
    assert result == {"pr_url": "u", "pr_number": 5, "github_branch": "signalpilot/x", "draft": True}
    assert seen["conversation_id"] == "conv-9"
    assert seen["project_id"] == PROJECT
    assert seen["github_branch"] == "signalpilot/x"
    assert seen["draft"] is True and seen["actor"] == "agent"


async def test_mcp_tools_pass_errors_through(mcp_env, monkeypatch):
    from gateway.git.agent_pr import AgentPrError

    async def boom(session, **kwargs):
        raise AgentPrError("this chat has not pushed a branch yet. " + agent_pr.PUSH_FIRST)

    async def leak(session, **kwargs):
        raise RuntimeError(f"token {TOKEN} rejected")

    reset = _chat_vars(mcp_env.context)
    try:
        monkeypatch.setattr("gateway.git.agent_pr.open_pull_request", boom)
        result = await _fn(mcp_env.open.open_pull_request)(title="x")
        assert result["error"].endswith("git push origin HEAD:signalpilot/<name>")
        monkeypatch.setattr("gateway.git.agent_pr.update_pull_request", boom)
        assert "pushed a branch" in (await _fn(mcp_env.update.update_pull_request)(title="x"))["error"]
        monkeypatch.setattr("gateway.git.agent_pr.comment_on_pull_request", leak)
        result = await _fn(mcp_env.comment.comment_on_pull_request)(body="x")
        assert result["error"].startswith("pull request operation failed")
        assert TOKEN not in result["error"]
    finally:
        reset()


async def test_mcp_update_and_comment_shapes(mcp_env, monkeypatch):
    seen: dict = {}

    async def fake_update(session, **kwargs):
        seen["update"] = kwargs
        return SimpleNamespace(pr_url="u", pr_number=5)

    async def fake_comment(session, **kwargs):
        seen["comment"] = kwargs
        return {"pr_url": "u", "pr_number": 5, "comment_url": "c"}

    monkeypatch.setattr("gateway.git.agent_pr.update_pull_request", fake_update)
    monkeypatch.setattr("gateway.git.agent_pr.comment_on_pull_request", fake_comment)
    reset = _chat_vars(mcp_env.context)
    try:
        assert await _fn(mcp_env.update.update_pull_request)(title="", body="b", pr_number=0) == {
            "pr_url": "u", "pr_number": 5,
        }
        assert await _fn(mcp_env.comment.comment_on_pull_request)(body="hi", pr_number=5) == {
            "pr_url": "u", "pr_number": 5, "comment_url": "c",
        }
    finally:
        reset()
    assert seen["update"]["title"] is None and seen["update"]["body"] == "b" and seen["update"]["pr_number"] is None
    assert seen["comment"]["pr_number"] == 5 and seen["comment"]["conversation_id"] == "conv-9"


# REST.


def _record(**overrides):
    base = {
        "id": "pr-1", "org_id": ORG, "project_id": PROJECT, "conversation_id": "conv-1", "repo_full_name": REPO,
        "source_branch": "signalpilot/x", "github_branch": "signalpilot/x", "base_branch": "main", "pr_number": 3,
        "pr_url": f"https://github.com/{REPO}/pull/3", "title": "t", "status": "open", "error_message": None,
        "export_commit_sha": None, "last_pushed_sha": "a" * 40, "last_pushed_at": 2.0, "draft": False,
        "created_by": "chat:run-1", "created_at": 1.0, "updated_at": 2.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def rest_app(monkeypatch):
    from fastapi import FastAPI, Request

    from gateway.api import github as github_api
    from gateway.api.deps import get_store
    from gateway.security import scope_guard

    auth = {"auth_method": "api_key", "user_id": "u", "scopes": ["read", "write"]}
    app = FastAPI()

    @app.middleware("http")
    async def _inject(request: Request, call_next):
        request.state.auth = dict(auth)
        return await call_next(request)

    app.include_router(github_api.router)
    app.dependency_overrides[scope_guard._resolve_user_id] = lambda: "u"
    audits: list = []

    class _Store:
        org_id = ORG
        user_id = "u"
        session = object()

        async def get_workspace_project(self, project_id):
            return SimpleNamespace(id=project_id) if project_id == PROJECT else None

        async def append_audit(self, entry):
            audits.append(entry)

    app.dependency_overrides[get_store] = lambda: _Store()
    return SimpleNamespace(app=app, auth=auth, audits=audits)


def test_rest_create_and_list(rest_app, monkeypatch):
    from fastapi.testclient import TestClient

    seen: dict = {}

    async def fake_open(session, **kwargs):
        seen.update(kwargs)
        return _record()

    monkeypatch.setattr(agent_pr, "open_pull_request", fake_open)

    async def fake_list(session, *, org_id, project_id=None, limit=100):
        return [_record(), _record(id="pr-2", status="pushed", pr_number=None, pr_url=None)]

    monkeypatch.setattr(github_prs, "list_pull_requests", fake_list)
    with TestClient(rest_app.app) as c:
        resp = c.post(
            "/api/github/pull-requests",
            json={"project_id": PROJECT, "github_branch": "signalpilot/x", "title": "t", "draft": True},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["pr_number"] == 3
        assert seen["github_branch"] == "signalpilot/x" and seen["draft"] is True and seen["actor"] == "u"
        assert seen["conversation_id"] is None
        assert rest_app.audits[0].event_type == "github_pr_create"
        assert rest_app.audits[0].metadata["github_branch"] == "signalpilot/x"

        assert c.post("/api/github/pull-requests", json={"project_id": "zzz", "github_branch": "b", "title": "t"}).status_code == 404
        # Old body shape (source_branch) is rejected.
        assert c.post("/api/github/pull-requests", json={"project_id": PROJECT, "source_branch": "b", "title": "t"}).status_code == 422

        listed = c.get(f"/api/github/pull-requests?project_id={PROJECT}")
        assert listed.status_code == 200
        assert [(r["id"], r["status"], r["draft"]) for r in listed.json()] == [("pr-1", "open", False), ("pr-2", "pushed", False)]

        rest_app.auth["scopes"] = ["read"]
        assert c.post("/api/github/pull-requests", json={"project_id": PROJECT, "github_branch": "b", "title": "t"}).status_code == 403


def test_rest_create_maps_agent_pr_error_to_400(rest_app, monkeypatch):
    from fastapi.testclient import TestClient

    async def fake_open(session, **kwargs):
        raise agent_pr.AgentPrError("branch 'signalpilot/x' has no push record for this project")

    monkeypatch.setattr(agent_pr, "open_pull_request", fake_open)
    with TestClient(rest_app.app) as c:
        resp = c.post("/api/github/pull-requests", json={"project_id": PROJECT, "github_branch": "signalpilot/x", "title": "t"})
        assert resp.status_code == 400
        assert "no push record" in resp.json()["detail"]


def test_rest_update_and_comment(rest_app, monkeypatch):
    from fastapi.testclient import TestClient

    records = {"pr-1": _record(), "pr-2": _record(id="pr-2", status="pushed", pr_number=None, pr_url=None)}

    async def fake_get(session, *, org_id, record_id):
        assert org_id == ORG
        return records.get(record_id)

    seen: dict = {}

    async def fake_update(session, **kwargs):
        seen["update"] = kwargs
        return _record(title=kwargs.get("title") or "t")

    async def fake_comment(session, **kwargs):
        seen["comment"] = kwargs
        return {"pr_url": records["pr-1"].pr_url, "pr_number": 3, "comment_url": "https://github.com/x#c1"}

    monkeypatch.setattr(agent_pr, "get_record", fake_get)
    monkeypatch.setattr(agent_pr, "update_pull_request", fake_update)
    monkeypatch.setattr(agent_pr, "comment_on_pull_request", fake_comment)
    with TestClient(rest_app.app) as c:
        resp = c.patch("/api/github/pull-requests/pr-1", json={"title": "renamed"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["title"] == "renamed"
        assert seen["update"]["pr_number"] == 3 and seen["update"]["conversation_id"] == "conv-1"
        assert seen["update"]["actor"] == "u" and seen["update"]["body"] is None

        resp = c.post("/api/github/pull-requests/pr-1/comments", json={"body": "looks good"})
        assert resp.status_code == 201, resp.text
        assert resp.json() == {"pr_url": records["pr-1"].pr_url, "pr_number": 3, "comment_url": "https://github.com/x#c1"}
        assert seen["comment"]["body"] == "looks good" and seen["comment"]["pr_number"] == 3

        assert c.patch("/api/github/pull-requests/missing", json={"title": "x"}).status_code == 404
        assert c.patch("/api/github/pull-requests/pr-2", json={"title": "x"}).status_code == 400
        assert c.post("/api/github/pull-requests/pr-2/comments", json={"body": "x"}).status_code == 400
        assert {a.event_type for a in rest_app.audits} == {"github_pr_update", "github_pr_comment"}

        rest_app.auth["scopes"] = ["read"]
        assert c.patch("/api/github/pull-requests/pr-1", json={"title": "x"}).status_code == 403
        assert c.post("/api/github/pull-requests/pr-1/comments", json={"body": "x"}).status_code == 403
