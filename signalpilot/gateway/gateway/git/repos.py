"""Bare git repo management — init, delete, list branches via git CLI."""

import logging
import os
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

REPOS_ROOT = Path(os.getenv("SP_REPOS_DIR", "/repos"))

# Name of the GitHub remote in each bare repo. Mirrors sync.GITHUB_REMOTE_NAME;
# duplicated here to avoid a circular import (sync.py imports repos.py).
_GITHUB_REMOTE = "github"
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")


def _validate_branch_name(branch: str) -> None:
    if not branch or branch.startswith("-") or not _BRANCH_RE.match(branch):
        raise ValueError(f"Invalid branch name: {branch!r}")


def _run_git(
    *args: str,
    cwd: Path | str | None = None,
    timeout: int = 30,
    input: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input,
        env={**os.environ, **env} if env else None,
    )
    return result.returncode, result.stdout, result.stderr


def repo_path(project_id: str) -> Path:
    import re
    if not re.match(r"^[a-f0-9\-]{36}$", project_id):
        raise ValueError("Invalid project_id: must be a UUID")
    path = REPOS_ROOT / f"{project_id}.git"
    if not str(path.resolve()).startswith(str(REPOS_ROOT.resolve())):
        raise ValueError("Path traversal detected")
    return path


def repo_exists(project_id: str) -> bool:
    try:
        return repo_path(project_id).is_dir()
    except ValueError:
        return False


def init_bare_repo(project_id: str, default_branch: str = "main") -> Path:
    _validate_branch_name(default_branch)
    path = repo_path(project_id)
    if path.exists():
        logger.info("Bare repo already exists: %s", path)
        _ensure_initial_default_branch(path, default_branch)
        return path

    path.mkdir(parents=True, exist_ok=True)
    rc, out, err = _run_git("init", "--bare", "--initial-branch", default_branch, str(path))
    if rc != 0:
        raise RuntimeError(f"git init --bare failed: {err}")

    _run_git("config", "http.receivepack", "true", cwd=path)
    _run_git("config", "receive.denyCurrentBranch", "updateInstead", cwd=path)
    _ensure_initial_default_branch(path, default_branch)

    logger.info("Created bare repo: %s (default branch: %s)", path, default_branch)
    return path


def _ensure_initial_default_branch(path: Path, default_branch: str) -> None:
    """Make fresh managed repos branchable by giving the default branch a root commit."""
    rc, out, _ = _run_git("rev-parse", "--verify", f"refs/heads/{default_branch}", cwd=path)
    if rc == 0 and out.strip():
        return

    rc, out, err = _run_git("for-each-ref", "--format=%(refname)", "refs/heads/", cwd=path)
    if rc == 0 and out.strip():
        return

    rc, tree, err = _run_git("mktree", cwd=path, input="")
    if rc != 0 or not tree.strip():
        raise RuntimeError(f"Could not create empty tree for managed repo: {err}")

    rc, commit, err = _run_git(
        "commit-tree",
        tree.strip(),
        "-m",
        "Initial empty project",
        cwd=path,
        env={
            "GIT_AUTHOR_NAME": "SignalPilot",
            "GIT_AUTHOR_EMAIL": "local@signalpilot.dev",
            "GIT_COMMITTER_NAME": "SignalPilot",
            "GIT_COMMITTER_EMAIL": "local@signalpilot.dev",
        },
    )
    if rc != 0 or not commit.strip():
        raise RuntimeError(f"Could not create initial commit for managed repo: {err}")

    rc, _, err = _run_git("update-ref", f"refs/heads/{default_branch}", commit.strip(), cwd=path)
    if rc != 0:
        raise RuntimeError(f"Could not set initial {default_branch!r} branch: {err}")

    rc, _, err = _run_git("symbolic-ref", "HEAD", f"refs/heads/{default_branch}", cwd=path)
    if rc != 0:
        raise RuntimeError(f"Could not point HEAD at {default_branch!r}: {err}")


def delete_repo(project_id: str) -> bool:
    path = repo_path(project_id)
    if not path.exists():
        return False

    import shutil
    shutil.rmtree(path)
    logger.info("Deleted bare repo: %s", path)
    return True


def clone_from_remote(project_id: str, clone_url: str) -> Path:
    """Populate a bare repo from a remote so it serves a real tree to clients.

    Two paths, both of which MUST leave local refs/heads/* + HEAD populated
    (the notebook pod clones the bare repo's local heads — if they're empty it
    sees 0 files):

    - Fresh: `git clone --bare` natively mirrors the remote's branches into
      refs/heads/* and sets HEAD.
    - Pre-existing (the common case — the bare repo is created empty at project
      creation, before the GitHub remote is known): `git fetch` only updates
      refs/remotes/github/*, so we materialize local heads from them afterward.
    """
    path = repo_path(project_id)
    if path.exists():
        _run_git("fetch", "--all", cwd=path)
        materialize_local_branches(project_id)
        return path

    rc, out, err = _run_git("clone", "--bare", clone_url, str(path), timeout=120)
    if rc != 0:
        raise RuntimeError(f"git clone --bare failed: {err}")

    _run_git("config", "http.receivepack", "true", cwd=path)
    materialize_local_branches(project_id)
    logger.info("Cloned bare repo from remote")
    return path


def list_branches(project_id: str) -> list[str]:
    path = repo_path(project_id)
    if not path.exists():
        return []

    rc, out, err = _run_git("branch", "--list", cwd=path)
    if rc != 0:
        return []

    branches = []
    for line in out.strip().split("\n"):
        name = line.strip().lstrip("* ")
        if name:
            branches.append(name)
    return branches


def ensure_branch_from(project_id: str, branch: str, from_branch: str = "main") -> str:
    """Ensure a local bare-repo branch exists from another branch and return its HEAD SHA."""
    _validate_branch_name(branch)
    _validate_branch_name(from_branch)
    path = repo_path(project_id)
    if not path.exists():
        raise RuntimeError(f"Git repository not initialized for project {project_id}")

    rc, out, _ = _run_git("rev-parse", "--verify", f"refs/heads/{branch}", cwd=path)
    if rc == 0 and out.strip():
        return out.strip()

    rc, out, err = _run_git("rev-parse", "--verify", f"refs/heads/{from_branch}", cwd=path)
    if rc != 0 or not out.strip():
        raise RuntimeError(f"Default branch {from_branch!r} not found for project {project_id}: {err.strip()}")

    sha = out.strip()
    rc, _, err = _run_git("update-ref", f"refs/heads/{branch}", sha, cwd=path)
    if rc != 0:
        raise RuntimeError(f"Could not create branch {branch!r}: {err.strip()}")
    return sha


def branch_head_sha(project_id: str, branch: str) -> str | None:
    """Return the local bare-repo branch HEAD SHA, if present."""
    _validate_branch_name(branch)
    path = repo_path(project_id)
    if not path.exists():
        return None
    rc, out, _ = _run_git("rev-parse", "--verify", f"refs/heads/{branch}", cwd=path)
    return out.strip() if rc == 0 and out.strip() else None


def _detect_remote_default_branch(path: Path) -> str | None:
    """Best-effort: ask the github remote which branch HEAD points to."""
    # Populates refs/remotes/github/HEAD as a symref to the default branch.
    _run_git("remote", "set-head", _GITHUB_REMOTE, "-a", cwd=path)
    rc, out, _ = _run_git(
        "symbolic-ref", f"refs/remotes/{_GITHUB_REMOTE}/HEAD", cwd=path
    )
    if rc == 0 and out.strip():
        return out.strip().removeprefix(f"refs/remotes/{_GITHUB_REMOTE}/")
    return None


def materialize_local_branches(project_id: str, default_branch: str | None = None) -> None:
    """Ensure local refs/heads/* + HEAD reflect the fetched github branches.

    A bare repo serves refs/heads/* to clients (the notebook pod clones these).
    A `git fetch` only populates refs/remotes/github/*, so without this the
    served repo looks empty (0 files). Idempotent and safe to call after every
    clone/fetch.

    Only creates local heads that don't already exist — never force-overwrites a
    local branch, which could discard commits not yet pushed to GitHub. The
    sync push/pull path is responsible for fast-forwarding existing branches.
    """
    path = repo_path(project_id)
    if not path.exists():
        return

    rc, out, _ = _run_git(
        "for-each-ref", "--format=%(refname)", f"refs/remotes/{_GITHUB_REMOTE}/", cwd=path
    )
    if rc != 0 or not out.strip():
        return  # nothing fetched from github (e.g. fresh clone --bare already set heads)

    created: list[str] = []
    for ref in out.strip().splitlines():
        ref = ref.strip()
        branch = ref.removeprefix(f"refs/remotes/{_GITHUB_REMOTE}/")
        if not branch or branch == "HEAD":
            continue
        # Skip branches that already have a local head — don't clobber local work.
        exists, _, _ = _run_git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=path)
        if exists != 0:
            _run_git("update-ref", f"refs/heads/{branch}", ref, cwd=path)
        created.append(branch)

    # Point HEAD at the default branch (resolve it if not given).
    if default_branch is None:
        default_branch = _detect_remote_default_branch(path)
    if default_branch is None:
        default_branch = "main" if "main" in created else (created[0] if created else "main")

    rc, _, _ = _run_git("rev-parse", "--verify", "--quiet", f"refs/heads/{default_branch}", cwd=path)
    if rc == 0:
        _run_git("symbolic-ref", "HEAD", f"refs/heads/{default_branch}", cwd=path)


def get_head_ref(project_id: str) -> str | None:
    path = repo_path(project_id)
    if not path.exists():
        return None

    rc, out, err = _run_git("symbolic-ref", "HEAD", cwd=path)
    if rc != 0:
        return None
    return out.strip().removeprefix("refs/heads/")


def ensure_repos_dir() -> None:
    REPOS_ROOT.mkdir(parents=True, exist_ok=True)
    logger.info("Git repos directory: %s", REPOS_ROOT)
