"""End-to-end suite for the workspace project git system.

Covers the full lifecycle a user exercises: project creation (bare repo
scaffold), branching, linking a GitHub repo (fresh and after local work),
re-linking, the sync protocol in every reachable state (fast-forward both
ways, force push, true divergence, agent-branch exclusion), failure handling,
path confinement, concurrency, and performance floors.

"GitHub" here is a local bare repo used as the remote — every scenario runs
hermetically. The live Vercel/GitHub path is covered separately in
test_vercel_agent_workflow_live.py.
"""

from __future__ import annotations

import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

_GIT_ID = ["-c", "user.email=t@test", "-c", "user.name=test"]


def _pid() -> str:
    return str(uuid.uuid4())


_B1 = _pid()
_B2 = _pid()
_B3 = _pid()
_B4 = _pid()
_B5 = _pid()
_L1 = _pid()
_L2 = _pid()
_L3 = _pid()
_L4 = _pid()
_L5 = _pid()
_L6 = _pid()
_L7 = _pid()
_L8 = _pid()
_P1 = _pid()
_P2 = _pid()
_P3 = _pid()
_P4 = _pid()
_PERF1 = _pid()
_PERF2 = _pid()
_PERF3 = _pid()


def _git(*args: str, cwd: str | Path | None = None) -> str:
    result = subprocess.run(
        ["git", *_GIT_ID, *args],
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _make_remote(tmp_path: Path, name: str, files: dict[str, str], default_branch: str = "main") -> str:
    """A local stand-in for a GitHub repo with real content."""
    src = tmp_path / name
    src.mkdir()
    _git("init", "--initial-branch", default_branch, str(src))
    for rel, text in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=src)
    _git("commit", "-m", "remote content", cwd=src)
    # Accept pushes to the checked-out branch (test remotes are non-bare so
    # tests can also commit "upstream" work into them directly).
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=src)
    return str(src)


def _remote_commit(remote: str, rel: str, text: str, message: str = "remote update") -> str:
    p = Path(remote) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=remote)
    _git("commit", "-m", message, cwd=remote)
    return _git("rev-parse", "HEAD", cwd=remote).strip()


def _local_commit(repos, project_id: str, tmp_path: Path, rel: str, text: str, message: str = "local work") -> str:
    """Commit user work onto the project's main via a working clone."""
    work = tmp_path / f"work-{time.monotonic_ns()}"
    _git("clone", str(repos.repo_path(project_id)), str(work))
    p = work / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=work)
    _git("commit", "-m", message, cwd=work)
    _git("push", "origin", "main", cwd=work)
    return _git("rev-parse", "HEAD", cwd=work).strip()


def _tree_files(repos, project_id: str, ref: str = "main") -> list[str]:
    out = _git("-C", str(repos.repo_path(project_id)), "ls-tree", "-r", ref, "--name-only")
    return [line for line in out.splitlines() if line]


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


# ── Project lifecycle ────────────────────────────────────────────────────────


class TestProjectLifecycle:
    def test_new_project_scaffold_is_pristine(self, repos):
        """The scaffold contract materialize_local_branches depends on:
        exactly one commit, completely empty tree."""
        repos.init_bare_repo(_P1)
        path = repos.repo_path(_P1)
        assert _git("-C", str(path), "rev-list", "--count", "main").strip() == "1"
        assert _tree_files(repos, _P1) == []
        assert repos._is_pristine_scaffold(path, "main")

    def test_scaffold_with_any_content_is_not_pristine(self, repos, tmp_path):
        repos.init_bare_repo(_P2)
        _local_commit(repos, _P2, tmp_path, "a.txt", "x")
        assert not repos._is_pristine_scaffold(repos.repo_path(_P2), "main")

    def test_delete_repo_removes_dir_and_is_idempotent(self, repos):
        repos.init_bare_repo(_P3)
        assert repos.repo_exists(_P3)
        assert repos.delete_repo(_P3)
        assert not repos.repo_exists(_P3)
        assert not repos.delete_repo(_P3)  # second delete: no error, reports False

    def test_repo_path_refuses_traversal(self, repos):
        with pytest.raises(Exception):
            repos.repo_path("../../etc/passwd")

    def test_head_points_at_default_branch(self, repos):
        repos.init_bare_repo(_P4, default_branch="develop")
        assert repos.get_head_ref(_P4) == "develop"


# ── Branching ────────────────────────────────────────────────────────────────


class TestBranching:
    def test_branch_from_main_shares_head(self, repos):
        repos.init_bare_repo(_B1)
        main_sha = repos.branch_head_sha(_B1, "main")
        assert repos.ensure_branch_from(_B1, "signalpilot-agent/run-1", "main") == main_sha
        assert repos.branch_head_sha(_B1, "signalpilot-agent/run-1") == main_sha

    def test_ensure_branch_is_idempotent_and_never_resets(self, repos, tmp_path):
        repos.init_bare_repo(_B2)
        repos.ensure_branch_from(_B2, "feature/x", "main")
        # Advance the feature branch, then ensure again — must not reset it.
        work = tmp_path / "w"
        _git("clone", "--branch", "feature/x", str(repos.repo_path(_B2)), str(work))
        (work / "f.txt").write_text("v1", encoding="utf-8")
        _git("add", "-A", cwd=work)
        _git("commit", "-m", "advance", cwd=work)
        _git("push", "origin", "feature/x", cwd=work)
        advanced = repos.branch_head_sha(_B2, "feature/x")
        assert repos.ensure_branch_from(_B2, "feature/x", "main") == advanced

    def test_branch_from_missing_base_fails_cleanly(self, repos):
        repos.init_bare_repo(_B3)
        with pytest.raises(Exception):
            repos.ensure_branch_from(_B3, "feature/y", "no-such-base")

    def test_invalid_branch_names_are_refused(self, repos):
        repos.init_bare_repo(_B4)
        for bad in ("../evil", "a b", "-flag", ""):
            with pytest.raises(Exception):
                repos.ensure_branch_from(_B4, bad, "main")

    def test_concurrent_branch_creation_is_safe(self, repos):
        repos.init_bare_repo(_B5)
        main_sha = repos.branch_head_sha(_B5, "main")

        def mk(i: int) -> str:
            return repos.ensure_branch_from(_B5, f"analysis/agent-{i}", "main")

        with ThreadPoolExecutor(8) as pool:
            shas = list(pool.map(mk, range(16)))
        assert set(shas) == {main_sha}
        assert len([b for b in repos.list_branches(_B5) if b.startswith("analysis/")]) == 16


# ── GitHub link workflow ─────────────────────────────────────────────────────


class TestGitHubLinkWorkflow:
    def test_link_fresh_project_imports_everything(self, repos, tmp_path):
        """The canonical user flow: create project → link repo → see files."""
        repos.init_bare_repo(_L1)
        remote = _make_remote(tmp_path, "gh1", {"models/orders.sql": "select 1", "README.md": "hi"})
        repos.clone_from_remote(_L1, remote)
        assert sorted(_tree_files(repos, _L1)) == ["README.md", "models/orders.sql"]
        assert repos.get_head_ref(_L1) == "main"

    def test_link_without_preexisting_repo_uses_bare_clone(self, repos, tmp_path):
        remote = _make_remote(tmp_path, "gh2", {"a.txt": "x"})
        repos.clone_from_remote(_L2, remote)
        assert _tree_files(repos, _L2) == ["a.txt"]

    def test_link_imports_all_remote_branches(self, repos, tmp_path):
        remote = _make_remote(tmp_path, "gh3", {"a.txt": "x"})
        _git("checkout", "-b", "develop", cwd=remote)
        _remote_commit(remote, "dev.txt", "d")
        _git("checkout", "main", cwd=remote)
        repos.init_bare_repo(_L3)
        repos.clone_from_remote(_L3, remote)
        branches = repos.list_branches(_L3)
        assert "main" in branches and "develop" in branches
        assert "dev.txt" in _tree_files(repos, _L3, "develop")

    def test_link_respects_non_main_default_branch(self, repos, tmp_path):
        remote = _make_remote(tmp_path, "gh4", {"a.txt": "x"}, default_branch="master")
        repos.init_bare_repo(_L4)  # scaffold still creates main
        repos.clone_from_remote(_L4, remote)
        assert "master" in repos.list_branches(_L4)
        assert _tree_files(repos, _L4, "master") == ["a.txt"]

    def test_link_never_overwrites_local_work(self, repos, tmp_path):
        repos.init_bare_repo(_L5)
        user_sha = _local_commit(repos, _L5, tmp_path, "notebook.py", "x = 1")
        remote = _make_remote(tmp_path, "gh5", {"other.txt": "y"})
        repos.clone_from_remote(_L5, remote)
        assert repos.branch_head_sha(_L5, "main") == user_sha

    def test_relink_to_different_remote_rotates_url(self, repos, tmp_path):
        repos.init_bare_repo(_L6)
        first = _make_remote(tmp_path, "gh6a", {"one.txt": "1"})
        repos.clone_from_remote(_L6, first)
        second = _make_remote(tmp_path, "gh6b", {"two.txt": "2"})
        # Re-link: main is no longer pristine (adopted from first) so content
        # is preserved; the remote URL must still rotate for future syncs.
        repos.clone_from_remote(_L6, second)
        url = _git("-C", str(repos.repo_path(_L6)), "remote", "get-url", "github").strip()
        assert url == second
        assert _tree_files(repos, _L6) == ["one.txt"]  # not clobbered

    def test_link_with_unreachable_remote_raises(self, repos, tmp_path):
        repos.init_bare_repo(_L7)
        with pytest.raises(RuntimeError):
            repos.clone_from_remote(_L7, str(tmp_path / "does-not-exist"))
        # And the failure must not have corrupted the scaffold.
        assert repos._is_pristine_scaffold(repos.repo_path(_L7), "main")

    def test_import_survives_repeat_calls(self, repos, tmp_path):
        """Materialize is documented idempotent — prove it."""
        repos.init_bare_repo(_L8)
        remote = _make_remote(tmp_path, "gh8", {"a.txt": "x"})
        repos.clone_from_remote(_L8, remote)
        first = repos.branch_head_sha(_L8, "main")
        repos.clone_from_remote(_L8, remote)
        repos.materialize_local_branches(_L8)
        assert repos.branch_head_sha(_L8, "main") == first


# ── Sync protocol ────────────────────────────────────────────────────────────


class TestSyncProtocol:
    def _linked(self, repos, tmp_path, files=None) -> tuple[str, str]:
        project_id = _pid()
        remote = _make_remote(tmp_path, f"gh-{project_id[:8]}", files or {"base.txt": "b"})
        repos.init_bare_repo(project_id)
        repos.clone_from_remote(project_id, remote)
        return project_id, remote

    def test_local_ahead_pushes_fast_forward(self, repos, sync, tmp_path):
        project_id, remote = self._linked(repos, tmp_path)
        sha = _local_commit(repos, project_id, tmp_path, "new.txt", "n")
        result = sync.push_branch(project_id, remote, "main")
        assert result.get("pushed") is True
        assert _git("rev-parse", "main", cwd=remote).strip() == sha

    def test_remote_ahead_fast_forwards_local(self, repos, sync, tmp_path):
        project_id, remote = self._linked(repos, tmp_path)
        # Remote must be non-checked-out to accept pushes; detach its worktree head.
        _git("checkout", "--detach", cwd=remote)
        remote_sha = _remote_commit(remote, "upstream.txt", "u")
        _git("update-ref", "refs/heads/main", remote_sha, cwd=remote)
        result = sync.push_branch(project_id, remote, "main")
        assert result.get("fast_forwarded") is True
        assert repos.branch_head_sha(project_id, "main") == remote_sha

    def test_true_divergence_is_reported_not_destroyed(self, repos, sync, tmp_path):
        project_id, remote = self._linked(repos, tmp_path)
        local_sha = _local_commit(repos, project_id, tmp_path, "mine.txt", "m")
        _git("checkout", "--detach", cwd=remote)
        remote_sha = _remote_commit(remote, "theirs.txt", "t")
        _git("update-ref", "refs/heads/main", remote_sha, cwd=remote)
        result = sync.push_branch(project_id, remote, "main")
        assert result.get("diverged") is True
        # Neither side lost anything.
        assert repos.branch_head_sha(project_id, "main") == local_sha
        assert _git("rev-parse", "main", cwd=remote).strip() == remote_sha

    def test_agent_branches_never_leave_the_gateway(self, repos, sync, tmp_path):
        project_id, remote = self._linked(repos, tmp_path)
        repos.ensure_branch_from(project_id, "signalpilot-agent/run-9", "main")
        result = sync.push_branch(project_id, remote, "signalpilot-agent/run-9")
        assert result.get("skipped") is True
        assert "signalpilot-agent/run-9" not in _git("branch", "--list", "-a", cwd=remote)

    def test_pushing_a_missing_branch_errors_cleanly(self, repos, sync, tmp_path):
        project_id, remote = self._linked(repos, tmp_path)
        result = sync.push_branch(project_id, remote, "never-created")
        assert "error" in result

    def test_full_roundtrip_link_edit_sync_edit_sync(self, repos, sync, tmp_path):
        """The whole user story: link → local work → sync → upstream work →
        sync — both sides converge with no manual git."""
        project_id, remote = self._linked(repos, tmp_path, {"start.txt": "s"})
        _local_commit(repos, project_id, tmp_path, "local1.txt", "a")
        assert sync.push_branch(project_id, remote, "main").get("pushed") is True
        # The push updated the remote's ref but not its (non-bare) worktree —
        # sync it before committing upstream work on top.
        _git("checkout", "-f", "main", cwd=remote)
        _git("reset", "--hard", "main", cwd=remote)
        upstream_sha = _remote_commit(remote, "upstream1.txt", "b")
        _git("checkout", "--detach", cwd=remote)
        result = sync.push_branch(project_id, remote, "main")
        assert result.get("fast_forwarded") is True
        assert repos.branch_head_sha(project_id, "main") == upstream_sha
        assert sorted(_tree_files(repos, project_id)) == [
            "local1.txt", "start.txt", "upstream1.txt",
        ]


# ── Performance floors ───────────────────────────────────────────────────────
# Bounds are deliberately generous (CI-safe); their purpose is catching
# order-of-magnitude regressions, not micro-benchmarks.


class TestPerformance:
    def test_import_of_2000_file_repo_under_15s(self, repos, tmp_path):
        files = {f"models/m{i:04d}.sql": f"select {i}" for i in range(2000)}
        remote = _make_remote(tmp_path, "big", files)
        repos.init_bare_repo(_PERF1)
        started = time.monotonic()
        repos.clone_from_remote(_PERF1, remote)
        elapsed = time.monotonic() - started
        assert len(_tree_files(repos, _PERF1)) == 2000
        assert elapsed < 15, f"import took {elapsed:.1f}s"

    def test_branch_creation_under_1s(self, repos):
        repos.init_bare_repo(_PERF2)
        started = time.monotonic()
        repos.ensure_branch_from(_PERF2, "analysis/quick", "main")
        assert time.monotonic() - started < 1.0

    def test_noop_sync_under_2s(self, repos, sync, tmp_path):
        remote = _make_remote(tmp_path, "perf3-remote", {"a.txt": "x"})
        repos.init_bare_repo(_PERF3)
        repos.clone_from_remote(_PERF3, remote)
        started = time.monotonic()
        result = sync.push_branch(_PERF3, remote, "main")
        assert time.monotonic() - started < 2.0
        assert "error" not in result
