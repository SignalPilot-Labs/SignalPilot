"""SP-11: the GitHub App installation token must never be persisted in a
bare repo's config. The remote URL stays credential-free and the credential
travels per invocation through GIT_CONFIG_* env (an http.extraheader)."""

from __future__ import annotations

import base64
import shutil
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available")

TOKEN = "ghs_secretInstallationToken123"
AUTHED = f"https://x-access-token:{TOKEN}@github.com/acme/dbt.git"
PLAIN = "https://github.com/acme/dbt.git"


@pytest.fixture
def repos(monkeypatch, tmp_path):
    from gateway.git import repos as repos_mod

    monkeypatch.setattr(repos_mod, "REPOS_ROOT", tmp_path / "repos")
    (tmp_path / "repos").mkdir()
    return repos_mod


@pytest.fixture
def sync(repos):
    from gateway.git import sync as sync_mod

    return sync_mod


def _git(*args: str, cwd: str | Path) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=False, capture_output=True, text=True).stdout


def _config_dump(path: Path) -> str:
    return _git("config", "--list", cwd=path)


def _make_remote(tmp_path: Path) -> str:
    src = tmp_path / "remote"
    src.mkdir()
    ident = ["-c", "user.email=t@test", "-c", "user.name=test"]
    subprocess.run(["git", *ident, "init", "--initial-branch", "main", str(src)], check=True, capture_output=True)
    (src / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", *ident, "add", "-A"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", *ident, "commit", "-m", "init"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "config", "receive.denyCurrentBranch", "ignore"], cwd=src, check=True)
    return str(src)


# ── Pure helper ──────────────────────────────────────────────────────────────


def test_split_remote_credentials_moves_token_into_env(repos):
    plain, env = repos.split_remote_credentials(AUTHED)
    assert plain == PLAIN
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    b64 = env["GIT_CONFIG_VALUE_0"].removeprefix("AUTHORIZATION: basic ")
    assert base64.b64decode(b64).decode() == f"x-access-token:{TOKEN}"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


@pytest.mark.parametrize("url", [PLAIN, "/tmp/some/local/repo", "C:\\repos\\x.git", "git@github.com:acme/dbt.git"])
def test_split_remote_credentials_passes_plain_urls_through(repos, url):
    assert repos.split_remote_credentials(url) == (url, {})


# ── Persisted config never carries the token ────────────────────────────────


def test_configure_github_remote_stores_plain_url_and_scrubs_legacy_token(repos, sync):
    project_id = str(uuid.uuid4())
    path = repos.init_bare_repo(project_id)
    # A mirror written before the fix: token embedded in the remote URL.
    _git("remote", "add", "github", AUTHED, cwd=path)
    assert TOKEN in _config_dump(path)

    env = sync.configure_github_remote(project_id, AUTHED)

    assert _git("config", "--get", "remote.github.url", cwd=path).strip() == PLAIN
    assert TOKEN not in _config_dump(path)
    assert env["GIT_CONFIG_KEY_0"].endswith(".extraheader")


def test_configure_github_remote_adds_plain_url_when_remote_missing(repos, sync):
    project_id = str(uuid.uuid4())
    path = repos.init_bare_repo(project_id)
    sync.configure_github_remote(project_id, AUTHED)
    assert _git("config", "--get", "remote.github.url", cwd=path).strip() == PLAIN
    assert TOKEN not in _config_dump(path)


def test_push_fetch_pull_never_put_token_in_argv_or_config(repos, sync, monkeypatch):
    """Every git invocation on the sync/push/fetch/pull paths gets the
    credential via env only; argv and the on-disk config stay clean."""
    project_id = str(uuid.uuid4())
    path = repos.init_bare_repo(project_id)
    calls: list[tuple[tuple[str, ...], dict | None]] = []
    real = repos._run_git

    def spy(*args, cwd=None, timeout=30, input=None, env=None):
        calls.append((args, env))
        if args[0] in {"push", "fetch"}:
            return 0, "", ""  # pretend GitHub accepted it
        return real(*args, cwd=cwd, timeout=timeout, input=input, env=env)

    monkeypatch.setattr(repos, "_run_git", spy)
    monkeypatch.setattr(sync, "_run_git", spy)

    assert sync.push_branch(project_id, AUTHED, "main").get("pushed") is True
    assert sync.fetch_all(project_id, AUTHED).get("fetched") is True
    sync.pull_branch(project_id, AUTHED, "main")

    for args, _ in calls:
        assert all(TOKEN not in a for a in args), args
    network = [(a, e) for a, e in calls if a[0] in {"push", "fetch"}]
    assert network, "expected push/fetch invocations"
    for _, env in network:
        assert env and env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
        assert TOKEN in base64.b64decode(env["GIT_CONFIG_VALUE_0"].split()[-1]).decode()
    assert TOKEN not in _config_dump(path)
    assert _git("config", "--get", "remote.github.url", cwd=path).strip() == PLAIN


def test_clone_from_remote_fresh_and_existing_never_persist_token(repos, monkeypatch):
    project_id = str(uuid.uuid4())
    seen: list[tuple[tuple[str, ...], dict | None]] = []
    real = repos._run_git

    def spy(*args, cwd=None, timeout=30, input=None, env=None):
        seen.append((args, env))
        if args[0] in {"clone", "fetch"} or (args[0] == "remote" and "set-head" in args):
            if args[0] == "clone":
                Path(args[-1]).mkdir(parents=True, exist_ok=True)
                real("init", "--bare", args[-1])
            return 0, "", ""
        return real(*args, cwd=cwd, timeout=timeout, input=input, env=env)

    monkeypatch.setattr(repos, "_run_git", spy)

    # Fresh mirror: `git clone --bare` must receive the plain URL + env.
    path = repos.clone_from_remote(project_id, AUTHED)
    clone_calls = [(a, e) for a, e in seen if a[0] == "clone"]
    assert clone_calls and PLAIN in clone_calls[0][0] and TOKEN not in " ".join(clone_calls[0][0])
    assert clone_calls[0][1]["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"

    # Existing mirror: remote is (re)pointed at the plain URL, fetch gets env.
    seen.clear()
    repos.clone_from_remote(project_id, AUTHED)
    assert _git("config", "--get", "remote.github.url", cwd=path).strip() == PLAIN
    assert TOKEN not in _config_dump(path)
    fetch_calls = [(a, e) for a, e in seen if a[0] == "fetch"]
    assert fetch_calls and fetch_calls[0][1]["GIT_CONFIG_COUNT"] == "1"
    for args, _ in seen:
        assert all(TOKEN not in a for a in args), args


def test_local_path_remote_still_syncs_end_to_end(repos, sync, tmp_path):
    """Regression: credential-free remotes (tests, local paths) are untouched."""
    project_id = str(uuid.uuid4())
    remote = _make_remote(tmp_path)
    repos.init_bare_repo(project_id)
    repos.clone_from_remote(project_id, remote)
    assert repos.branch_head_sha(project_id, "main")
    assert sync.fetch_all(project_id, remote).get("fetched") is True
    assert sync.pull_branch(project_id, remote, "main").get("pulled") is True


# ── The env mechanism really reaches the wire ───────────────────────────────


class _Recorder(BaseHTTPRequestHandler):
    seen: list[str] = []

    def do_GET(self):
        type(self).seen.append(self.headers.get("Authorization") or "")
        # 404 (not 401) so git fails fast instead of consulting credential
        # helpers (Git Credential Manager on Windows would block the test).
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_):
        pass


def test_git_sends_basic_auth_from_env_without_credentials_in_url(repos, tmp_path):
    server = HTTPServer(("127.0.0.1", 0), _Recorder)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://x-access-token:{TOKEN}@127.0.0.1:{port}/acme/dbt.git"
        plain, env = repos.split_remote_credentials(url)
        assert plain == f"http://127.0.0.1:{port}/acme/dbt.git"
        rc, _, _ = repos._run_git(
            "-c", "credential.helper=", "ls-remote", plain, cwd=tmp_path, timeout=30, env=env
        )
        assert rc != 0  # 404 from the recorder; only the header matters
    finally:
        server.shutdown()
        server.server_close()
    expected = "basic " + base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()
    assert any(h.lower() == expected.lower() for h in _Recorder.seen), _Recorder.seen
