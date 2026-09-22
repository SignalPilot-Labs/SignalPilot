"""Pull request lifecycle on agent-pushed branches: open, update, comment.

Hermetic: aiosqlite for Postgres, httpx.MockTransport for the GitHub REST
API. Push records are seeded through store.github_prs.record_branch_push,
exactly what the git server writes after an accepted chat push.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from gateway.db.models import (
    GatewayAgentPullRequest,
    GatewayBase,
    GatewayGitHubInstallation,
    GatewayGitHubRepoLink,
)
from gateway.git import agent_pr
from gateway.store import github_prs

ORG = "org-a"
PROJECT = "proj-1"
REPO = "acme/dbt"
TOKEN = "ghs_secretInstallationToken123"
WEB = "https://app.test"


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


class GitHubApiMock:
    """Enough of the GitHub REST API for PR create / patch / comment."""

    def __init__(self, *, pr_status: int = 201):
        self.pr_status = pr_status
        self.requests: list[dict] = []
        self.next_number = 17

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read() or b"null")
        path = request.url.path
        self.requests.append(
            {"method": request.method, "path": path, "json": body, "auth": request.headers.get("authorization")}
        )
        if request.method == "POST" and path == f"/repos/{REPO}/pulls":
            if self.pr_status != 201:
                return httpx.Response(
                    self.pr_status,
                    json={"message": "Validation Failed", "errors": [{"message": "No commits between"}]},
                )
            number = self.next_number
            self.next_number += 1
            return httpx.Response(201, json={"number": number, "html_url": f"https://github.com/{REPO}/pull/{number}"})
        if request.method == "PATCH" and path.startswith(f"/repos/{REPO}/pulls/"):
            number = int(path.rsplit("/", 1)[1])
            return httpx.Response(200, json={"number": number, "html_url": f"https://github.com/{REPO}/pull/{number}"})
        if request.method == "POST" and path.endswith("/comments"):
            number = int(path.split("/")[-2])
            return httpx.Response(
                201, json={"id": 9, "html_url": f"https://github.com/{REPO}/pull/{number}#issuecomment-9"}
            )
        return httpx.Response(404, json={"message": "unexpected"})


async def _seed_link(db):
    db.add(
        GatewayGitHubInstallation(
            id="inst-1", org_id=ORG, github_installation_id=1, github_account_login="acme",
            github_account_type="Organization", status="active", authorized_repository_ids=[42],
            created_at=1.0, updated_at=1.0,
        )
    )
    db.add(
        GatewayGitHubRepoLink(
            id="link-1", org_id=ORG, project_id=PROJECT, installation_id="inst-1", repo_full_name=REPO,
            repo_id=42, default_branch="main", status="active", created_at=1.0, updated_at=1.0,
        )
    )
    await db.commit()


async def _push(db, branch: str, conversation_id: str | None = "conv-1", *, repo: str = REPO, sha: str = "a" * 40):
    return await github_prs.record_branch_push(
        db, org_id=ORG, project_id=PROJECT, conversation_id=conversation_id, repo_full_name=repo,
        github_branch=branch, base_branch="main", sha=sha, actor="chat:run-1",
    )


@pytest.fixture
def pr_env(monkeypatch):
    """Token resolution, web url, and the GitHub REST transport."""
    from gateway.config import github as github_config
    from gateway.github_bot import client as bot_client
    from gateway.store import github as gh_store

    state: dict = {"api": GitHubApiMock()}

    async def fake_token(session, row):
        return TOKEN

    monkeypatch.setattr(gh_store, "get_valid_token", fake_token)
    monkeypatch.setattr(github_config, "get_github_settings", lambda: SimpleNamespace(sp_web_url=WEB))
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(state["api"])
        return real(*args, **kwargs)

    monkeypatch.setattr(bot_client.httpx, "AsyncClient", factory)
    return state


async def _rows(db):
    return (await db.execute(select(GatewayAgentPullRequest))).scalars().all()


def _open_kwargs(**overrides):
    base = {"org_id": ORG, "project_id": PROJECT, "conversation_id": "conv-1", "title": "Add revenue mart"}
    base.update(overrides)
    return base


# open_pull_request.


async def test_open_on_pushed_branch(db, pr_env):
    await _seed_link(db)
    await _push(db, "signalpilot/revenue")

    record = await agent_pr.open_pull_request(
        db, body="Changed: fct_revenue\nBuild: PASS", draft=True, **_open_kwargs()
    )
    assert record.status == "open"
    assert record.pr_number == 17
    assert record.pr_url == f"https://github.com/{REPO}/pull/17"
    assert record.github_branch == "signalpilot/revenue"
    assert record.base_branch == "main"
    assert record.title == "Add revenue mart"
    assert record.draft is True
    assert record.last_pushed_sha == "a" * 40
    assert record.error_message is None

    (call,) = pr_env["api"].requests
    assert call["method"] == "POST" and call["path"] == f"/repos/{REPO}/pulls"
    assert call["json"]["head"] == "signalpilot/revenue"
    assert call["json"]["base"] == "main"
    assert call["json"]["draft"] is True
    assert call["json"]["body"].startswith("Changed: fct_revenue\nBuild: PASS")
    assert call["json"]["body"].rstrip().endswith(f"{WEB}/chats/conv-1")
    assert call["auth"] == f"token {TOKEN}"
    rows = await _rows(db)
    assert [(r.status, r.pr_number, r.conversation_id) for r in rows] == [("open", 17, "conv-1")]


async def test_open_is_idempotent_for_an_open_pr(db, pr_env):
    await _seed_link(db)
    await _push(db, "signalpilot/revenue")
    first = await agent_pr.open_pull_request(db, **_open_kwargs())
    second = await agent_pr.open_pull_request(db, **_open_kwargs(title="another title"))
    assert (second.pr_number, second.pr_url, second.title) == (first.pr_number, first.pr_url, first.title)
    assert len(pr_env["api"].requests) == 1
    assert len(await _rows(db)) == 1


async def test_open_picks_the_latest_pushed_branch_of_the_conversation(db, pr_env):
    await _seed_link(db)
    await _push(db, "signalpilot/older", sha="1" * 40)
    await _push(db, "signalpilot/newer", sha="2" * 40)
    await _push(db, "signalpilot/other-chat", "conv-2", sha="3" * 40)
    record = await agent_pr.open_pull_request(db, **_open_kwargs())
    assert record.github_branch == "signalpilot/newer"


async def test_open_explicit_branch_and_base(db, pr_env):
    await _seed_link(db)
    await _push(db, "signalpilot/a", sha="1" * 40)
    await _push(db, "signalpilot/b", sha="2" * 40)
    record = await agent_pr.open_pull_request(
        db, github_branch="signalpilot/a", base_branch="release", **_open_kwargs()
    )
    assert record.github_branch == "signalpilot/a"
    assert record.base_branch == "release"
    assert pr_env["api"].requests[0]["json"]["base"] == "release"


async def test_open_without_push_record_errors(db, pr_env):
    await _seed_link(db)
    with pytest.raises(agent_pr.AgentPrError, match="git push origin HEAD:signalpilot/<name>"):
        await agent_pr.open_pull_request(db, **_open_kwargs())
    with pytest.raises(agent_pr.AgentPrError, match="no push record"):
        await agent_pr.open_pull_request(db, github_branch="signalpilot/nope", **_open_kwargs())
    assert pr_env["api"].requests == []


async def test_open_unlinked_project_errors(db, pr_env):
    await _push(db, "signalpilot/x", repo="")
    with pytest.raises(agent_pr.AgentPrError, match="not linked to GitHub"):
        await agent_pr.open_pull_request(db, **_open_kwargs())
    # Record has a repo name but the link row is gone: same plain message.
    await _push(db, "signalpilot/y", sha="b" * 40)
    with pytest.raises(agent_pr.AgentPrError, match="not linked to GitHub"):
        await agent_pr.open_pull_request(db, **_open_kwargs())
    assert pr_env["api"].requests == []


async def test_open_agent_cannot_use_another_chats_branch(db, pr_env):
    await _seed_link(db)
    await _push(db, "signalpilot/theirs", "conv-2")
    with pytest.raises(agent_pr.AgentPrError, match="another chat"):
        await agent_pr.open_pull_request(db, github_branch="signalpilot/theirs", **_open_kwargs())
    # A human REST caller may open it.
    record = await agent_pr.open_pull_request(
        db, github_branch="signalpilot/theirs", actor="user-1", **_open_kwargs(conversation_id=None)
    )
    assert record.status == "open"
    assert pr_env["api"].requests[0]["json"]["body"].rstrip().endswith(f"{WEB}/chats/conv-2")


async def test_open_github_error_keeps_status_pushed(db, pr_env):
    await _seed_link(db)
    await _push(db, "signalpilot/revenue")
    pr_env["api"] = GitHubApiMock(pr_status=422)
    with pytest.raises(agent_pr.AgentPrError, match="422") as info:
        await agent_pr.open_pull_request(db, **_open_kwargs())
    assert "No commits between" in str(info.value)
    assert TOKEN not in str(info.value)
    (row,) = await _rows(db)
    assert row.status == "pushed"
    assert row.pr_number is None
    assert "422" in row.error_message and TOKEN not in row.error_message


async def test_open_after_merge_errors(db, pr_env):
    await _seed_link(db)
    await _push(db, "signalpilot/revenue")
    await agent_pr.open_pull_request(db, **_open_kwargs())
    assert await github_prs.mark_pull_request_closed(db, repo_full_name=REPO, pr_number=17, merged=True) == 1
    with pytest.raises(agent_pr.AgentPrError, match="already merged"):
        await agent_pr.open_pull_request(db, **_open_kwargs())


# update_pull_request.


async def _two_open_prs(db):
    await _seed_link(db)
    await _push(db, "signalpilot/one", "conv-1", sha="1" * 40)
    await _push(db, "signalpilot/two", "conv-2", sha="2" * 40)
    mine = await agent_pr.open_pull_request(db, **_open_kwargs())
    theirs = await agent_pr.open_pull_request(db, **_open_kwargs(conversation_id="conv-2", title="theirs"))
    return mine, theirs


async def test_update_targets_only_this_conversations_pr(db, pr_env):
    mine, theirs = await _two_open_prs(db)
    record = await agent_pr.update_pull_request(
        db, org_id=ORG, project_id=PROJECT, conversation_id="conv-1", title="New title", body="Build: PASS again"
    )
    assert record.pr_number == mine.pr_number
    assert record.title == "New title"
    patch = pr_env["api"].requests[-1]
    assert patch["method"] == "PATCH" and patch["path"] == f"/repos/{REPO}/pulls/{mine.pr_number}"
    assert patch["json"]["title"] == "New title"
    assert patch["json"]["body"].startswith("Build: PASS again")
    assert patch["json"]["body"].rstrip().endswith(f"{WEB}/chats/conv-1")
    assert patch["json"]["body"].count(agent_pr.ATTRIBUTION_MARKER) == 1

    with pytest.raises(agent_pr.AgentPrError, match="another chat"):
        await agent_pr.update_pull_request(
            db, org_id=ORG, project_id=PROJECT, conversation_id="conv-1", pr_number=theirs.pr_number, title="x"
        )
    rows = {r.pr_number: r.title for r in await _rows(db)}
    assert rows[theirs.pr_number] == "theirs"


async def test_update_body_strips_an_existing_attribution_line(db, pr_env):
    await _seed_link(db)
    await _push(db, "signalpilot/one")
    await agent_pr.open_pull_request(db, **_open_kwargs())
    stale = agent_pr.build_body("old text", "conv-1")
    await agent_pr.update_pull_request(db, org_id=ORG, project_id=PROJECT, conversation_id="conv-1", body=stale)
    body = pr_env["api"].requests[-1]["json"]["body"]
    assert body.count(agent_pr.ATTRIBUTION_MARKER) == 1 and body.startswith("old text")


async def test_update_requires_an_open_pr_and_a_change(db, pr_env):
    await _seed_link(db)
    with pytest.raises(agent_pr.AgentPrError, match="no open pull request"):
        await agent_pr.update_pull_request(db, org_id=ORG, project_id=PROJECT, conversation_id="conv-1", title="x")
    await _push(db, "signalpilot/one")
    await agent_pr.open_pull_request(db, **_open_kwargs())
    with pytest.raises(agent_pr.AgentPrError, match="nothing to update"):
        await agent_pr.update_pull_request(db, org_id=ORG, project_id=PROJECT, conversation_id="conv-1")
    with pytest.raises(agent_pr.AgentPrError, match="not opened by SignalPilot"):
        await agent_pr.update_pull_request(
            db, org_id=ORG, project_id=PROJECT, conversation_id="conv-1", pr_number=999, title="x"
        )


async def test_ambiguous_target_errors(db, pr_env):
    await _seed_link(db)
    await _push(db, "signalpilot/one", sha="1" * 40)
    await _push(db, "signalpilot/two", sha="2" * 40)
    await agent_pr.open_pull_request(db, github_branch="signalpilot/one", **_open_kwargs())
    await agent_pr.open_pull_request(db, github_branch="signalpilot/two", **_open_kwargs())
    with pytest.raises(agent_pr.AgentPrError, match="several open pull requests .*pass pr_number"):
        await agent_pr.update_pull_request(db, org_id=ORG, project_id=PROJECT, conversation_id="conv-1", title="x")
    with pytest.raises(agent_pr.AgentPrError, match="several open"):
        await agent_pr.comment_on_pull_request(db, org_id=ORG, project_id=PROJECT, conversation_id="conv-1", body="hi")
    result = await agent_pr.comment_on_pull_request(
        db, org_id=ORG, project_id=PROJECT, conversation_id="conv-1", body="hi", pr_number=18
    )
    assert result["pr_number"] == 18


# comment_on_pull_request.


async def test_comment_returns_comment_url(db, pr_env):
    await _seed_link(db)
    await _push(db, "signalpilot/one")
    opened = await agent_pr.open_pull_request(db, **_open_kwargs())
    result = await agent_pr.comment_on_pull_request(
        db, org_id=ORG, project_id=PROJECT, conversation_id="conv-1", body="Build passed after the fix."
    )
    assert result == {
        "pr_url": opened.pr_url,
        "pr_number": opened.pr_number,
        "comment_url": f"https://github.com/{REPO}/pull/{opened.pr_number}#issuecomment-9",
    }
    call = pr_env["api"].requests[-1]
    assert call["method"] == "POST" and call["path"] == f"/repos/{REPO}/issues/{opened.pr_number}/comments"
    assert call["json"] == {"body": "Build passed after the fix."}
    with pytest.raises(agent_pr.AgentPrError, match="body is required"):
        await agent_pr.comment_on_pull_request(db, org_id=ORG, project_id=PROJECT, conversation_id="conv-1", body=" ")


async def test_comment_github_error_is_plain(db, pr_env):
    await _seed_link(db)
    await _push(db, "signalpilot/one")
    await agent_pr.open_pull_request(db, **_open_kwargs())

    class Failing(GitHubApiMock):
        def __call__(self, request):
            if request.url.path.endswith("/comments"):
                return httpx.Response(403, json={"message": "Resource not accessible by integration"})
            return super().__call__(request)

    pr_env["api"] = Failing()
    with pytest.raises(agent_pr.AgentPrError, match="GitHub returned 403: Resource not accessible"):
        await agent_pr.comment_on_pull_request(db, org_id=ORG, project_id=PROJECT, conversation_id="conv-1", body="x")
