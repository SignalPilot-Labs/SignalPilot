"""Bare git repo management — init, delete, list branches via git CLI."""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

REPOS_ROOT = Path(os.getenv("SP_REPOS_DIR", "/repos"))

# Name of the GitHub remote in each bare repo. Mirrors sync.GITHUB_REMOTE_NAME;
# duplicated here to avoid a circular import (sync.py imports repos.py).
_GITHUB_REMOTE = "github"


def _run_git(*args: str, cwd: Path | str | None = None, timeout: int = 30) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def repo_path(project_id: str) -> Path:
    import re
    if not re.match(r"^[a-f0-9\-]{36}$", project_id):
        raise ValueError(f"Invalid project_id: must be a UUID")
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
    path = repo_path(project_id)
    if path.exists():
        logger.info("Bare repo already exists: %s", path)
        return path

    path.mkdir(parents=True, exist_ok=True)
    rc, out, err = _run_git("init", "--bare", "--initial-branch", default_branch, str(path))
    if rc != 0:
        raise RuntimeError(f"git init --bare failed: {err}")

    _run_git("config", "http.receivepack", "true", cwd=path)
    _run_git("config", "receive.denyCurrentBranch", "updateInstead", cwd=path)

    logger.info("Created bare repo: %s (default branch: %s)", path, default_branch)
    return path


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
