"""Chat agent git publish: ref policy on the gateway git server + push records.

A real ``git`` client pushes over HTTP to the git router served by uvicorn in
a thread. Auth is stubbed at ``_authenticate`` (the Basic password selects the
identity); everything else is real: the org check against a sqlite database,
``git http-backend``, the bare mirror, the push record table and the mirror
to a local repo standing in for GitHub.

Proven here:
- a chat identity may create and update refs/heads/signalpilot/** only,
- pushes to main, deletes and force pushes are refused with a reason the
  git client prints as ``! [remote rejected]``,
- an accepted push is recorded (status pushed, sha) and mirrored to GitHub
  under the same name, fast-forward only,
- a branch that exists on GitHub without a record of ours is left alone,
- API-key identities keep the open policy,
- a project without a GitHub link records but does not publish.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import (
    GatewayAgentPullRequest,
    GatewayBase,
    GatewayChatRun,
    GatewayGitHubRepoLink,
    GatewayWorkspaceProject,
)
from gateway.git import http_server, ref_policy
from gateway.git import repos as repos_mod
from gateway.git import sync as sync_mod
from gateway.store import github_prs

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available")

ORG = "org-chat"
USER = "user-1"
RUN_ID = "run-1"
CONVERSATION = "conv-1"
_GIT_ID = ["-c", "user.email=t@test", "-c", "user.name=test"]

CHAT_TOKEN = "chat-token"
KEY_TOKEN = "api-key-token"
IDENTITIES = {
    CHAT_TOKEN: {
        "user_id": USER, "org_id": ORG, "scopes": ["read", "write", "query", "execute"],
        "auth_method": "notebook_session", "execution_identity": f"chat:{RUN_ID}",
    },
    KEY_TOKEN: {"user_id": USER, "org_id": ORG, "scopes": ["read", "write"], "auth_method": "api_key"},
}


def _git(*args: str, cwd: str | Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *_GIT_ID, *args], cwd=str(cwd) if cwd else None, check=check, capture_output=True, text=True,
    )


def _commit(work: Path, name: str, text: str, message: str = "work") -> str:
    (work / name).write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", message, cwd=work)
    return _git("rev-parse", "HEAD", cwd=work).stdout.strip()


def _make_github(tmp_path: Path) -> Path:
    """A local repo standing in for the GitHub repository."""
    src = tmp_path / "github"
    src.mkdir()
    _git("init", "-q", "--initial-branch", "main", str(src))
    _commit(src, "a.txt", "a", "init")
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=src)
    return src


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Harness ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'gateway.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest.fixture
def server(monkeypatch, tmp_path, db):
    """The git router on a real port; returns (base_url, state)."""
    monkeypatch.setattr(repos_mod, "REPOS_ROOT", tmp_path / "repos")
    (tmp_path / "repos").mkdir()
    monkeypatch.setattr(http_server, "REPOS_ROOT", tmp_path / "repos")
    monkeypatch.setattr("gateway.db.engine.get_session_factory", lambda: db)

    async def fake_authenticate(request):
        import base64

        header = request.headers.get("authorization", "")
        if not header.startswith("Basic "):
            raise http_server.HTTPException(
                status_code=401, detail="Authentication required",
                headers={"WWW-Authenticate": 'Basic realm="SignalPilot Git"'},
            )
        _, token = base64.b64decode(header[6:]).decode().split(":", 1)
        auth = IDENTITIES.get(token)
        if auth is None:
            raise http_server.HTTPException(status_code=403, detail="Invalid credentials")
        return dict(auth)

    monkeypatch.setattr(http_server, "_authenticate", fake_authenticate)

    github = _make_github(tmp_path)
    remote_calls: list[str] = []

    async def fake_remote_url(session, org_id, link):
        remote_calls.append(link.repo_full_name)
        return str(github)

    monkeypatch.setattr(http_server, "github_remote_url", fake_remote_url)

    publish_calls: list[dict] = []
    real_publish = sync_mod.publish_agent_branch

    def spy_publish(project_id, remote_url, branch, *, known_branch):
        publish_calls.append({"project_id": project_id, "remote_url": remote_url, "branch": branch,
                              "known_branch": known_branch})
        return real_publish(project_id, remote_url, branch, known_branch=known_branch)

    monkeypatch.setattr(sync_mod, "publish_agent_branch", spy_publish)

    app = FastAPI()
    app.include_router(http_server.router)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio")
    uv = uvicorn.Server(config)
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not uv.started and time.time() < deadline:
        time.sleep(0.05)
    assert uv.started, "uvicorn did not start"
    yield SimpleNamespace(
        url=f"http://127.0.0.1:{port}", github=github, remote_calls=remote_calls, publish_calls=publish_calls,
    )
    uv.should_exit = True
    thread.join(timeout=10)


async def _seed(db, *, project_id: str, link: bool) -> None:
    now = time.time()
    async with db() as session:
        session.add(GatewayWorkspaceProject(
            id=project_id, org_id=ORG, name="p", display_name="P", source="github" if link else "managed",
            status="active", created_at=now, updated_at=now,
        ))
        session.add(GatewayChatRun(
            id=RUN_ID, org_id=ORG, user_id=USER, conversation_id=CONVERSATION, project_id=project_id,
            user_message_id="m1", status="running",
        ))
        if link:
            session.add(GatewayGitHubRepoLink(
                id=str(uuid.uuid4()), org_id=ORG, project_id=project_id, installation_id="inst-1",
                repo_full_name="acme/dbt", repo_id=1, default_branch="main", status="active",
                created_at=now, updated_at=now,
            ))
        await session.commit()


@pytest.fixture
def project(server, db, tmp_path):
    """A linked project: bare mirror cloned from the fake GitHub, plus a checkout."""
    project_id = str(uuid.uuid4())
    asyncio.run(_seed(db, project_id=project_id, link=True))
    repos_mod.init_bare_repo(project_id)
    repos_mod.clone_from_remote(project_id, str(server.github))
    work = tmp_path / "work"
    _git("clone", "-q", _clone_url(server, CHAT_TOKEN, project_id), str(work))
    return SimpleNamespace(id=project_id, work=work)


def _clone_url(server, token: str, project_id: str) -> str:
    return server.url.replace("http://", f"http://sp:{token}@") + f"/git/{project_id}.git"


def _push(work: Path, *refspecs: str, token: str = CHAT_TOKEN, server=None, project_id=None):
    url = _clone_url(server, token, project_id) if server else "origin"
    return _git("push", url, *refspecs, cwd=work, check=False)


async def _rows(db, project_id: str) -> list[GatewayAgentPullRequest]:
    async with db() as session:
        result = await session.execute(
            select(GatewayAgentPullRequest).where(GatewayAgentPullRequest.project_id == project_id)
        )
        return list(result.scalars().all())


# ── Accepted pushes ──────────────────────────────────────────────────────────


class TestChatPushAccepted:
    def test_push_to_signalpilot_branch_is_recorded_and_published(self, server, db, project):
        sha = _commit(project.work, "model.sql", "select 1")
        result = _push(project.work, "HEAD:refs/heads/signalpilot/rana-fix")
        assert result.returncode == 0, result.stderr
        assert "new branch" in result.stderr

        # Mirror has the ref, GitHub has the same ref, one push record.
        assert repos_mod.branch_head_sha(project.id, "signalpilot/rana-fix") == sha
        assert _git("rev-parse", "refs/heads/signalpilot/rana-fix", cwd=server.github).stdout.strip() == sha
        assert server.publish_calls == [
            {"project_id": project.id, "remote_url": str(server.github), "branch": "signalpilot/rana-fix",
             "known_branch": False}
        ]
        rows = asyncio.run(_rows(db, project.id))
        assert len(rows) == 1
        row = rows[0]
        assert row.status == "pushed"
        assert row.last_pushed_sha == sha
        assert row.last_pushed_at is not None
        assert row.github_branch == "signalpilot/rana-fix"
        assert row.title == "signalpilot/rana-fix"
        assert row.conversation_id == CONVERSATION
        assert row.repo_full_name == "acme/dbt"
        assert row.base_branch == "main"
        assert row.created_by == USER
        assert row.error_message is None
        assert row.draft is False

    def test_second_push_updates_the_same_record(self, server, db, project):
        _commit(project.work, "model.sql", "select 1")
        assert _push(project.work, "HEAD:refs/heads/signalpilot/x").returncode == 0
        sha2 = _commit(project.work, "model.sql", "select 2")
        result = _push(project.work, "HEAD:refs/heads/signalpilot/x")
        assert result.returncode == 0, result.stderr

        rows = asyncio.run(_rows(db, project.id))
        assert len(rows) == 1
        assert rows[0].last_pushed_sha == sha2
        assert server.publish_calls[-1]["known_branch"] is True
        assert _git("rev-parse", "refs/heads/signalpilot/x", cwd=server.github).stdout.strip() == sha2

    def test_new_branch_already_on_github_is_rejected_before_receive(self, server, db, project):
        # A human (or an earlier chat with no record) created signalpilot/human on GitHub.
        _git("branch", "signalpilot/human", cwd=server.github)
        human_sha = _git("rev-parse", "signalpilot/human", cwd=server.github).stdout.strip()
        _commit(project.work, "model.sql", "select 1")
        result = _push(project.work, "HEAD:refs/heads/signalpilot/human")
        assert result.returncode != 0
        assert "[remote rejected]" in result.stderr
        assert ref_policy.reason_exists_on_github("signalpilot/human") in result.stderr
        assert _git("rev-parse", "signalpilot/human", cwd=server.github).stdout.strip() == human_sha
        assert repos_mod.branch_head_sha(project.id, "signalpilot/human") is None
        assert asyncio.run(_rows(db, project.id)) == []
        assert server.publish_calls == []

    def test_publish_guard_leaves_foreign_github_branch_alone(self, server, db, project):
        # Defence in depth: publish_agent_branch refuses a GitHub branch we have no record for.
        _git("branch", "signalpilot/human", cwd=server.github)
        repos_mod.ensure_branch_from(project.id, "signalpilot/human", "main")
        outcome = sync_mod.publish_agent_branch(
            project.id, str(server.github), "signalpilot/human", known_branch=False
        )
        assert outcome.get("exists") is True and "already exists on GitHub" in outcome["error"]

    def test_branch_of_another_conversation_is_rejected(self, server, db, project):
        async def seed_other():
            async with db() as session:
                await github_prs.record_branch_push(
                    session, org_id=ORG, project_id=project.id, conversation_id="conv-other",
                    repo_full_name="acme/dbt", github_branch="signalpilot/theirs", base_branch="main",
                    sha="f" * 40, actor="someone",
                )

        asyncio.run(seed_other())
        _commit(project.work, "model.sql", "select 1")
        result = _push(project.work, "HEAD:refs/heads/signalpilot/theirs")
        assert result.returncode != 0
        assert "[remote rejected]" in result.stderr
        assert ref_policy.reason_other_chat("signalpilot/theirs") in result.stderr
        assert repos_mod.branch_head_sha(project.id, "signalpilot/theirs") is None
        rows = asyncio.run(_rows(db, project.id))
        assert [r.last_pushed_sha for r in rows] == ["f" * 40]
        assert server.publish_calls == []

    def test_same_conversation_updates_its_own_branch(self, server, db, project):
        _commit(project.work, "model.sql", "select 1")
        assert _push(project.work, "HEAD:refs/heads/signalpilot/x").returncode == 0
        rows = asyncio.run(_rows(db, project.id))
        assert rows[0].conversation_id == CONVERSATION
        sha2 = _commit(project.work, "model.sql", "select 2")
        result = _push(project.work, "HEAD:refs/heads/signalpilot/x")
        assert result.returncode == 0, result.stderr
        assert _git("rev-parse", "refs/heads/signalpilot/x", cwd=server.github).stdout.strip() == sha2
        assert server.remote_calls.count("acme/dbt") >= 1

    def test_project_without_github_link_records_but_does_not_publish(self, server, db, tmp_path):
        project_id = str(uuid.uuid4())
        asyncio.run(_seed(db, project_id=project_id, link=False))
        repos_mod.init_bare_repo(project_id)
        work = tmp_path / "work-unlinked"
        _git("clone", "-q", _clone_url(server, CHAT_TOKEN, project_id), str(work))
        sha = _commit(work, "model.sql", "select 1")
        result = _push(work, "HEAD:refs/heads/signalpilot/local-only")
        assert result.returncode == 0, result.stderr

        assert server.publish_calls == []
        assert server.remote_calls == []
        rows = asyncio.run(_rows(db, project_id))
        assert len(rows) == 1
        assert rows[0].status == "pushed"
        assert rows[0].last_pushed_sha == sha
        assert rows[0].repo_full_name == ""


# ── Refused pushes ───────────────────────────────────────────────────────────


class TestChatPushRefused:
    def test_push_to_main_is_rejected_with_reason(self, server, db, project):
        before = repos_mod.branch_head_sha(project.id, "main")
        _commit(project.work, "model.sql", "select 1")
        result = _push(project.work, "HEAD:refs/heads/main")
        assert result.returncode != 0
        assert "[remote rejected]" in result.stderr
        assert ref_policy.REASON_OUTSIDE_NAMESPACE in result.stderr
        assert repos_mod.branch_head_sha(project.id, "main") == before
        assert asyncio.run(_rows(db, project.id)) == []
        assert server.publish_calls == []

    def test_mixed_push_is_rejected_as_a_whole(self, server, db, project):
        _commit(project.work, "model.sql", "select 1")
        result = _push(project.work, "HEAD:refs/heads/signalpilot/ok", "HEAD:refs/heads/feature/x")
        assert result.returncode != 0
        assert result.stderr.count("[remote rejected]") == 2
        assert repos_mod.branch_head_sha(project.id, "signalpilot/ok") is None
        assert asyncio.run(_rows(db, project.id)) == []

    def test_tag_is_rejected(self, server, project):
        _commit(project.work, "model.sql", "select 1")
        _git("tag", "v1", cwd=project.work)
        result = _push(project.work, "refs/tags/v1:refs/tags/v1")
        assert result.returncode != 0
        assert ref_policy.REASON_OUTSIDE_NAMESPACE in result.stderr

    def test_delete_is_rejected(self, server, db, project):
        _commit(project.work, "model.sql", "select 1")
        assert _push(project.work, "HEAD:refs/heads/signalpilot/x").returncode == 0
        result = _push(project.work, ":refs/heads/signalpilot/x")
        assert result.returncode != 0
        assert "[remote rejected]" in result.stderr
        assert ref_policy.REASON_DELETE in result.stderr
        assert repos_mod.branch_head_sha(project.id, "signalpilot/x") is not None

    def test_force_push_is_rejected_by_git(self, server, db, project):
        sha1 = _commit(project.work, "model.sql", "select 1")
        assert _push(project.work, "HEAD:refs/heads/signalpilot/x").returncode == 0
        _git("reset", "-q", "--hard", "HEAD~1", cwd=project.work)
        _commit(project.work, "other.sql", "select 9")
        result = _push(project.work, "+HEAD:refs/heads/signalpilot/x")
        assert result.returncode != 0
        assert "[remote rejected]" in result.stderr
        assert "non-fast-forward" in result.stderr
        assert repos_mod.branch_head_sha(project.id, "signalpilot/x") == sha1
        rows = asyncio.run(_rows(db, project.id))
        assert [r.last_pushed_sha for r in rows] == [sha1]


# ── Other identities are unchanged ───────────────────────────────────────────


class TestOtherIdentities:
    def test_api_key_pushes_anywhere_without_records(self, server, db, project, monkeypatch):
        mirrored: list[str] = []

        async def fake_mirror(project_id, org_id, branch):
            mirrored.append(branch)

        monkeypatch.setattr(sync_mod, "mirror_push_to_github", fake_mirror)
        _commit(project.work, "model.sql", "select 1")
        result = _push(
            project.work, "HEAD:refs/heads/signalpilot-agent/chat-1", "HEAD:refs/heads/feature/y",
            token=KEY_TOKEN, server=server, project_id=project.id,
        )
        assert result.returncode == 0, result.stderr
        assert repos_mod.branch_head_sha(project.id, "feature/y") is not None
        assert asyncio.run(_rows(db, project.id)) == []
        assert server.publish_calls == []
        deadline = time.time() + 5
        while len(mirrored) < 2 and time.time() < deadline:
            time.sleep(0.05)
        # (The receive-pack info/refs GET also mirrors "main" today; unchanged.)
        assert {"feature/y", "signalpilot-agent/chat-1"} <= set(mirrored)

    def test_plain_notebook_session_is_not_a_chat_identity(self):
        assert http_server.chat_run_id({"auth_method": "notebook_session"}) is None
        assert http_server.chat_run_id({"auth_method": "notebook_session", "execution_identity": "chat:"}) is None
        assert http_server.chat_run_id({"auth_method": "api_key", "execution_identity": "chat:r"}) is None
        assert http_server.chat_run_id(IDENTITIES[CHAT_TOKEN]) == RUN_ID


# ── Unit: parser and report ──────────────────────────────────────────────────


class TestRefPolicyUnit:
    def test_parser_reads_commands_and_capabilities(self):
        old = "0" * 40
        new = "a" * 40
        body = (
            ref_policy.pkt_line(f"{old} {new} refs/heads/signalpilot/x\0report-status side-band-64k\n".encode())
            + ref_policy.pkt_line(f"{new} {old} refs/heads/main\n".encode())
            + b"0000PACKdata"
        )
        commands, caps = ref_policy.parse_receive_pack_commands(body)
        assert caps == ["report-status", "side-band-64k"]
        assert [c.refname for c in commands] == ["refs/heads/signalpilot/x", "refs/heads/main"]
        assert commands[1].is_delete and not commands[0].is_delete
        assert ref_policy.pushed_branches(body) == ["signalpilot/x", "main"]
        assert ref_policy.check_chat_push(commands) == {"refs/heads/main": ref_policy.REASON_OUTSIDE_NAMESPACE}

    def test_report_without_sideband(self):
        cmd = ref_policy.RefUpdate("0" * 40, "a" * 40, "refs/heads/main")
        report = ref_policy.build_rejection_report([cmd], {"refs/heads/main": "nope"}, ["report-status"])
        assert report == b"000eunpack ok\n" + ref_policy.pkt_line(b"ng refs/heads/main nope\n") + b"0000"

    def test_report_with_sideband_wraps_in_band_1_and_adds_band_2(self):
        cmd = ref_policy.RefUpdate("0" * 40, "a" * 40, "refs/heads/main")
        report = ref_policy.build_rejection_report([cmd], {"refs/heads/main": "nope"}, ["side-band-64k"])
        assert report.startswith(ref_policy.pkt_line(b"\x02error: nope\n"))
        assert b"\x01000eunpack ok\n" in report
        assert report.endswith(b"0000" + b"0000")


# ── Store ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_branch_push_records(db):
    async with db() as session:
        kwargs = {"org_id": ORG, "project_id": "p1", "repo_full_name": "acme/dbt", "base_branch": "main", "actor": USER}
        first = await github_prs.record_branch_push(
            session, conversation_id=None, github_branch="signalpilot/a", sha="1" * 40, **kwargs
        )
        assert first.status == "pushed" and first.title == "signalpilot/a" and first.last_pushed_sha == "1" * 40
        assert await github_prs.latest_branch_for_conversation(
            session, org_id=ORG, project_id="p1", conversation_id=CONVERSATION
        ) is None

        # Re-push fills the conversation, keeps the row, moves the sha.
        again = await github_prs.record_branch_push(
            session, conversation_id=CONVERSATION, github_branch="signalpilot/a", sha="2" * 40,
            error_message="mirror failed", **kwargs,
        )
        assert again.id == first.id and again.conversation_id == CONVERSATION
        assert again.last_pushed_sha == "2" * 40 and again.error_message == "mirror failed"

        # A PR row keeps its status and PR fields on the next push.
        row = (await session.execute(select(GatewayAgentPullRequest))).scalar_one()
        row.status, row.pr_number, row.pr_url, row.title = "open", 7, "https://gh/pr/7", "Real title"
        await session.commit()
        third = await github_prs.record_branch_push(
            session, conversation_id="other", github_branch="signalpilot/a", sha="3" * 40, **kwargs
        )
        assert (third.status, third.pr_number, third.pr_url, third.title) == ("open", 7, "https://gh/pr/7", "Real title")
        assert third.conversation_id == CONVERSATION and third.error_message is None

        later = await github_prs.record_branch_push(
            session, conversation_id=CONVERSATION, github_branch="signalpilot/b", sha="4" * 40, **kwargs
        )
        latest = await github_prs.latest_branch_for_conversation(
            session, org_id=ORG, project_id="p1", conversation_id=CONVERSATION
        )
        assert latest is not None and latest.id == later.id
        got = await github_prs.get_branch_record(session, org_id=ORG, project_id="p1", github_branch="signalpilot/a")
        assert got is not None and got.id == first.id
        assert await github_prs.get_branch_record(session, org_id="o2", project_id="p1", github_branch="signalpilot/a") is None
        open_prs = await github_prs.list_open_prs_for_conversation(
            session, org_id=ORG, project_id="p1", conversation_id=CONVERSATION
        )
        assert [p.id for p in open_prs] == [first.id]
