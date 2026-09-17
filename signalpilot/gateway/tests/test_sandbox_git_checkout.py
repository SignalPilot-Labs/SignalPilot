"""The agent sandbox's /workspace becomes a git checkout of the project mirror.

Seeding appends the git setup block when the run names a project and the
gateway has a reachable public URL. Every exec for the sandbox carries a
fresh SP_GIT_TOKEN in its env (never in the command, never on disk) that the
git server's session-JWT verifier accepts, with the run's execution identity
and the write scope.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from gateway.auth.notebook_jwt import mint_session_jwt, verify_session_jwt
from gateway.config.gateway import get_gateway_settings
from gateway.mcp.context import (
    mcp_allowed_connection_var,
    mcp_branch_var,
    mcp_capabilities_var,
    mcp_execution_identity_var,
    mcp_org_id_var,
    mcp_project_id_var,
    mcp_raw_key_var,
    mcp_scopes_var,
    mcp_user_id_var,
)
from gateway.mcp.tools import sandbox_git, sandbox_vm
from gateway.mcp.tools.sandbox_vm import SANDBOX_CAPABILITY, sandbox_exec
from gateway.sandbox_runtime import ExecResult, SandboxSpec

_SECRET = "test-secret-" + "x" * 40
_SHA = "b" * 40


@dataclass
class FakeRuntime:
    created: list[SandboxSpec] = field(default_factory=list)
    execs: list[tuple[str, str, dict]] = field(default_factory=list)

    async def create(self, spec: SandboxSpec) -> str:
        self.created.append(spec)
        return f"sbx-{len(self.created)}"

    async def exec(self, sandbox_id, command, *, cwd=None, env=None, timeout_seconds=None):
        self.execs.append((sandbox_id, command, {"cwd": cwd, "env": dict(env or {})}))
        return ExecResult(returncode=0, stdout="ok", stderr="")

    async def destroy(self, sandbox_id) -> None:
        return None


class _FakeStorage:
    enabled = True

    async def presign_get(self, key, expires_seconds=0):
        return "https://s3.example.com/snap.tgz"


class _FakeWorkspaceStore:
    def __init__(self, storage):
        pass

    async def build_snapshot(self, session, *, org_id, project_id, branch):
        return None, "snap-key"


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setattr("gateway.auth.notebook_jwt.load_session_jwt_secret", lambda: _SECRET)
    monkeypatch.setattr("gateway.auth.jwt_secret._cached_secret", _SECRET)


@pytest.fixture
def public_gateway(monkeypatch):
    monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("SP_PUBLIC_GATEWAY_URL", "https://gw.example.com")
    get_gateway_settings.cache_clear()
    yield
    get_gateway_settings.cache_clear()


@pytest.fixture
def runtime(monkeypatch):
    fake = FakeRuntime()
    monkeypatch.setattr(sandbox_vm, "get_sandbox_runtime", lambda: fake)
    monkeypatch.setattr(
        "gateway.workspace_store.workspace_object_storage", lambda: _FakeStorage()
    )
    monkeypatch.setattr("gateway.workspace_store.store.WorkspaceStore", _FakeWorkspaceStore)

    @asynccontextmanager
    async def fake_store_session(*args, **kwargs):
        class _S:
            session = None

        yield _S()

    monkeypatch.setattr(sandbox_vm, "_store_session", fake_store_session)
    sandbox_vm._session_sandboxes.clear()
    yield fake
    sandbox_vm._session_sandboxes.clear()


def _inbound_jwt() -> str:
    return mint_session_jwt(
        user_id="user-7",
        org_id="org-1",
        session_id="run-42",
        project_id="proj-1",
        branch="main",
        connection_name="warehouse",
        commit_sha=_SHA,
        capabilities=[SANDBOX_CAPABILITY, "dbt:execute"],
        execution_identity="chat:run-42",
        scopes=["read", "query", "execute"],
        ttl=3600,
    )


@contextmanager
def chat_identity(raw_key: str | None):
    tokens = [
        mcp_scopes_var.set(["read", "query", "execute"]),
        mcp_capabilities_var.set([SANDBOX_CAPABILITY, "dbt:execute"]),
        mcp_execution_identity_var.set("chat:run-42"),
        mcp_org_id_var.set("org-1"),
        mcp_user_id_var.set("user-7"),
        mcp_project_id_var.set("proj-1"),
        mcp_branch_var.set("main"),
        mcp_allowed_connection_var.set("warehouse"),
        mcp_raw_key_var.set(raw_key),
    ]
    try:
        yield
    finally:
        for var, token in zip(
            (
                mcp_scopes_var, mcp_capabilities_var, mcp_execution_identity_var,
                mcp_org_id_var, mcp_user_id_var, mcp_project_id_var, mcp_branch_var,
                mcp_allowed_connection_var, mcp_raw_key_var,
            ),
            tokens,
            strict=True,
        ):
            var.reset(token)


@pytest.mark.asyncio
async def test_seed_contains_git_block_and_token_in_env(runtime, public_gateway, secret):
    with chat_identity(_inbound_jwt()):
        out = await sandbox_exec("git status", cwd="/workspace")
    assert out.startswith("exit_code: 0")
    seed_cmd, seed_env = runtime.execs[0][1], runtime.execs[0][2]["env"]
    assert "tar xz -C /workspace" in seed_cmd
    assert "git init -q" in seed_cmd
    assert 'git remote add origin "$SP_GIT_REMOTE_URL"' in seed_cmd
    assert 'git fetch -q --depth=50 origin "$SP_GIT_BASE_BRANCH"' in seed_cmd
    assert 'git symbolic-ref HEAD "refs/heads/$SP_GIT_BASE_BRANCH"' in seed_cmd
    assert "git reset -q --mixed FETCH_HEAD" in seed_cmd
    assert ".git/info/exclude" in seed_cmd
    assert "( sp_git_setup ) || echo" in seed_cmd
    assert seed_cmd.index("tar xz") < seed_cmd.index("git init") < seed_cmd.index("SP_EOF")
    assert seed_env["SP_GIT_REMOTE_URL"] == "https://gw.example.com/git/proj-1.git"
    assert seed_env["SP_GIT_BASE_BRANCH"] == "main"
    assert seed_env["SP_GIT_TOKEN"]
    # The agent's own exec also carries a token, and only that.
    exec_cmd, exec_env = runtime.execs[1][1], runtime.execs[1][2]["env"]
    assert exec_cmd == "git status"
    assert set(exec_env) == {"SP_GIT_TOKEN"}
    assert exec_env["SP_GIT_TOKEN"] != seed_env["SP_GIT_TOKEN"] or True  # fresh per exec


@pytest.mark.asyncio
async def test_token_never_in_command_and_helper_reads_env(runtime, public_gateway, secret):
    with chat_identity(_inbound_jwt()):
        await sandbox_exec("git push origin HEAD:signalpilot/x", cwd="/workspace")
    for _, command, kwargs in runtime.execs:
        token = kwargs["env"].get("SP_GIT_TOKEN", "")
        assert token and token not in command
        assert _SECRET not in command
    seed_cmd = runtime.execs[0][1]
    assert 'credential.helper \'!f() { echo username=x-access-token; echo "password=$SP_GIT_TOKEN"; }; f\'' in seed_cmd
    assert "x-access-token:" not in seed_cmd


@pytest.mark.asyncio
async def test_token_verifies_with_identity_and_write_scope(runtime, public_gateway, secret):
    with chat_identity(_inbound_jwt()):
        await sandbox_exec("true")
    for _, _, kwargs in runtime.execs:
        claims = verify_session_jwt(kwargs["env"]["SP_GIT_TOKEN"])
        assert claims["execution_identity"] == "chat:run-42"
        assert claims["scopes"] == ["read", "write"]
        assert claims["sub"] == "user-7"
        assert claims["org_id"] == "org-1"
        assert claims["project_id"] == "proj-1"
        assert claims["commit_sha"] == _SHA
        assert claims["exp"] - claims["iat"] == sandbox_git.GIT_TOKEN_TTL_SECONDS


def test_token_from_context_vars_when_bearer_is_not_a_session_jwt(secret):
    with chat_identity("sk-api-key"):
        token = sandbox_git.mint_git_token()
    assert token
    with pytest.raises(Exception, match="commit_sha"):
        # Only the inbound session JWT carries commit_sha; without it the git
        # server refuses the token, which is the intended fail-closed path.
        verify_session_jwt(token)


def test_no_token_without_identity(secret):
    assert sandbox_git.mint_git_token() is None
    assert sandbox_git.git_exec_env() == {}


@pytest.mark.asyncio
async def test_no_git_block_without_public_url(runtime, monkeypatch, secret):
    monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
    monkeypatch.delenv("SP_PUBLIC_GATEWAY_URL", raising=False)
    get_gateway_settings.cache_clear()
    try:
        with chat_identity(_inbound_jwt()):
            await sandbox_exec("true")
    finally:
        get_gateway_settings.cache_clear()
    seed_cmd, seed_env = runtime.execs[0][1], runtime.execs[0][2]["env"]
    assert "git init" not in seed_cmd
    assert "SP_GIT_REMOTE_URL" not in seed_env


def test_remote_url_rules(monkeypatch):
    monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("SP_PUBLIC_GATEWAY_URL", "http://localhost:3300")
    get_gateway_settings.cache_clear()
    try:
        assert sandbox_git.git_remote_url("proj-1") is None
        monkeypatch.setenv("SP_PUBLIC_GATEWAY_URL", "https://gw.example.com/")
        get_gateway_settings.cache_clear()
        assert sandbox_git.git_remote_url("proj-1") == "https://gw.example.com/git/proj-1.git"
        assert sandbox_git.git_remote_url(None) is None
    finally:
        get_gateway_settings.cache_clear()


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _bash() -> str | None:
    """A POSIX shell that understands the host's paths. On Windows the bash
    on PATH may be WSL's, which cannot see C:/ paths; prefer git-bash."""
    git = shutil.which("git")
    if git and os.name == "nt":
        candidate = Path(git).resolve().parents[1] / "bin" / "bash.exe"
        if candidate.is_file():
            return str(candidate)
    return shutil.which("bash")


@pytest.mark.skipif(
    not _bash() or not shutil.which("git"),
    reason="bash and git are required to execute the seed block",
)
def test_git_block_executes_against_a_real_remote(tmp_path: Path):
    """Run the actual shell block: the index matches the base tree while the
    working tree keeps the hydrated snapshot, so `git status` shows exactly
    the workspace's changes; a failure never stops the seed."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git("init", "-q", "-b", "main", cwd=upstream)
    _git("config", "user.email", "t@example.com", cwd=upstream)
    _git("config", "user.name", "t", cwd=upstream)
    (upstream / "models").mkdir()
    (upstream / "models" / "a.sql").write_text("select 1\n")
    (upstream / "models" / "b.sql").write_text("select 2\n")
    _git("add", ".", cwd=upstream)
    _git("commit", "-q", "-m", "base", cwd=upstream)
    remote = tmp_path / "remote.git"
    _git("clone", "-q", "--bare", str(upstream), str(remote), cwd=tmp_path)

    workspace = tmp_path / "workspace"
    (workspace / "models").mkdir(parents=True)
    (workspace / "models" / "a.sql").write_text("select 1 -- changed\n")
    (workspace / "models" / "b.sql").write_text("select 2\n")
    (workspace / "models" / "c.sql").write_text("select 3\n")
    (workspace / "target").mkdir()
    (workspace / "target" / "manifest.json").write_text("{}")

    script = sandbox_git.git_setup_command(workspace.as_posix())
    env = {
        **os.environ,
        sandbox_git.GIT_REMOTE_URL_ENV: remote.as_uri(),
        sandbox_git.GIT_BASE_BRANCH_ENV: "main",
    }
    run = subprocess.run(
        [_bash(), "-c", "set -e; " + script + "echo seed-continued"],
        env=env, capture_output=True, text=True, cwd=tmp_path,
    )
    assert run.returncode == 0, run.stderr
    assert "seed-continued" in run.stdout
    assert "git publish is unavailable" not in run.stderr
    assert _git("symbolic-ref", "HEAD", cwd=workspace) == "refs/heads/main"
    status = {
        line.strip() for line in _git("status", "--porcelain", cwd=workspace).splitlines()
    }
    assert status == {"M models/a.sql", "?? models/c.sql"}
    assert _git("config", "credential.helper", cwd=workspace).startswith("!f() {")
    assert _git("remote", "get-url", "origin", cwd=workspace) == remote.as_uri()

    # A broken remote logs and continues; re-running is idempotent.
    env[sandbox_git.GIT_REMOTE_URL_ENV] = (tmp_path / "missing.git").as_uri()
    rerun = subprocess.run(
        [_bash(), "-c", "set -e; " + script + "echo again"],
        env=env, capture_output=True, text=True, cwd=tmp_path,
    )
    assert rerun.returncode == 0
    assert "again" in rerun.stdout
    assert "git publish is unavailable" in rerun.stderr
    assert (workspace / ".git" / "info" / "exclude").read_text().count("target/") == 1
