"""Git operations: branch creation, pushing, and PR creation.

Handles the case where /workspace is a git submodule (the .git file
points outside the container). On first use we clone from the remote
into a working directory so branches share history with the remote.
"""

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


_WORK_DIR = "/home/agentuser/repo"
_initialized = False
_last_repo = ""  # Track which repo we cloned so we re-clone on change


def get_allowed_repo() -> str:
    """Read GITHUB_REPO at call time (not import time) so runtime changes are picked up."""
    return os.environ.get("GITHUB_REPO", "")


def _run(args: list[str], cwd: str | None = None, timeout: int = 120) -> str:
    """Run a command and return stdout. Raises on failure."""
    result = subprocess.run(
        args,
        cwd=cwd or _WORK_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _run_git(args: list[str], cwd: str | None = None) -> str:
    return _run(["git"] + args, cwd=cwd)


def _run_gh(args: list[str], cwd: str | None = None) -> str:
    return _run(["gh"] + args, cwd=cwd, timeout=120)


def _ensure_repo() -> None:
    """Ensure we have a proper clone of the repo with shared history.

    We clone from the remote into /home/agentuser/repo/ on first use.
    This avoids the submodule .git issue and ensures branches share
    history with the remote (required for PRs).

    If GITHUB_REPO changed since the last clone, we re-clone the new repo.
    """
    global _initialized, _last_repo

    allowed_repo = get_allowed_repo()
    token = os.environ.get("GIT_TOKEN", "")
    if not token or not allowed_repo:
        raise RuntimeError("GIT_TOKEN and GITHUB_REPO must be set")

    # If the repo changed, force a re-clone
    if _initialized and _last_repo and _last_repo != allowed_repo:
        print(f"[git] Repo changed from {_last_repo} to {allowed_repo} — re-cloning")
        _initialized = False

    repo_dir = Path(_WORK_DIR)
    remote_url = f"https://x-access-token:{token}@github.com/{allowed_repo}.git"

    if _initialized and repo_dir.exists() and (repo_dir / ".git").is_dir():
        # Already cloned the same repo — just update remote URL and fetch
        print("[git] Using existing clone, updating remote")
        try:
            _run_git(["remote", "set-url", "origin", remote_url])
            _run_git(["fetch", "origin"])
        except RuntimeError as e:
            print(f"[git] Warning: fetch failed: {e}")
    else:
        # Fresh clone — clear contents first (dir may be a volume mount)
        print(f"[git] Cloning {allowed_repo} into {_WORK_DIR}...")
        if repo_dir.exists():
            for item in repo_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
        else:
            repo_dir.mkdir(parents=True)
        _run(
            ["git", "clone", "--depth", "50", "--no-single-branch", remote_url, "."],
            cwd=_WORK_DIR,
            timeout=300,
        )
        print("[git] Clone complete")

    _last_repo = allowed_repo
    _initialized = True


def setup_git_auth() -> None:
    """Initialize the repo clone and configure auth."""
    # Ensure GH_TOKEN is set for gh CLI (mirrors GIT_TOKEN from env_file)
    token = os.environ.get("GIT_TOKEN", "")
    if token and not os.environ.get("GH_TOKEN"):
        os.environ["GH_TOKEN"] = token
    _ensure_repo()


def get_branch_name() -> str:
    """Generate a unique branch name for this run."""
    import uuid
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    short_id = uuid.uuid4().hex[:6]
    return f"signalpilot/improvements-round-{date_str}-{short_id}"


def create_branch(branch_name: str, base_branch: str = "main") -> str:
    """Create and checkout a new branch from the specified base branch."""
    _ensure_repo()
    try:
        _run_git(["fetch", "origin", base_branch])
        _run_git(["checkout", "-B", base_branch, f"origin/{base_branch}"])
    except RuntimeError:
        try:
            _run_git(["checkout", base_branch])
        except RuntimeError:
            print(f"[git] Warning: could not checkout {base_branch}, using current HEAD")

    _run_git(["checkout", "-b", branch_name])
    print(f"[git] Created branch: {branch_name} (from {base_branch})")
    return branch_name


def ensure_base_branch(base_branch: str = "main") -> None:
    """Verify the target base branch exists on remote.

    If the repo is completely empty, initialize it with a placeholder
    'main' branch (and 'staging' if needed) so the agent has something
    to branch off of.
    """
    _ensure_repo()

    # Check if remote has ANY refs at all
    try:
        all_refs = _run_git(["ls-remote", "--heads", "origin"])
    except RuntimeError:
        all_refs = ""

    if not all_refs.strip():
        # Completely empty repo — bootstrap it
        print(f"[git] Remote is empty — initializing with 'main' and 'staging' branches")
        try:
            _run_git(["checkout", "--orphan", "main"])
            _run_git(["commit", "--allow-empty", "-m", "Initialize repository"])
            _run_git(["push", "-u", "origin", "main"])
            # Also create staging
            _run_git(["checkout", "-b", "staging"])
            _run_git(["push", "-u", "origin", "staging"])
            # Go back to the requested base
            if base_branch not in ("main", "staging"):
                _run_git(["checkout", "-b", base_branch])
                _run_git(["push", "-u", "origin", base_branch])
            else:
                _run_git(["checkout", base_branch])
            print(f"[git] Initialized empty repo with main + staging branches")
        except RuntimeError as e:
            print(f"[git] Could not auto-init remote: {e}")
        return

    # Remote has refs — check if the specific base branch exists
    try:
        _run_git(["ls-remote", "--exit-code", "--heads", "origin", base_branch])
    except RuntimeError:
        print(f"[git] Branch '{base_branch}' not found on remote — creating it")
        try:
            # Create from the default branch (usually main)
            default = _get_default_branch()
            _run_git(["checkout", default])
            _run_git(["checkout", "-b", base_branch])
            _run_git(["push", "-u", "origin", base_branch])
            print(f"[git] Created '{base_branch}' from '{default}'")
        except RuntimeError as e:
            print(f"[git] Could not create branch '{base_branch}': {e}")


def _get_default_branch() -> str:
    """Detect the remote's default branch (main, master, etc)."""
    try:
        ref = _run_git(["symbolic-ref", "refs/remotes/origin/HEAD", "--short"])
        return ref.replace("origin/", "")
    except RuntimeError:
        # Fallback: check if main or master exists
        try:
            _run_git(["ls-remote", "--exit-code", "--heads", "origin", "main"])
            return "main"
        except RuntimeError:
            try:
                _run_git(["ls-remote", "--exit-code", "--heads", "origin", "master"])
                return "master"
            except RuntimeError:
                return "main"


def commit_changes(message: str = "Self-improvement changes") -> bool:
    """Stage and commit all changes. Returns True if a commit was created."""
    _ensure_repo()
    if not has_changes():
        return False
    _run_git(["add", "-A"])
    _run_git(["commit", "-m", message])
    return True


def push_branch(branch_name: str) -> None:
    """Push the current branch to origin."""
    _run_git(["push", "-u", "origin", branch_name])


def create_pr(branch_name: str, run_id: str, base_branch: str = "main") -> str:
    """Create a PR from the branch to the base branch. Returns the PR URL."""
    repo = get_allowed_repo()
    title = f"[Self-Improve] {branch_name}"
    body = (
        "## Self-Improvement Run\n\n"
        f"**Branch:** `{branch_name}`\n"
        f"**Run ID:** `{run_id}`\n\n"
        f"This PR was created by the self-improvement agent.\n"
        f"Review all changes carefully before merging to `{base_branch}`.\n\n"
        "---\n"
        "*Generated by Self-Improve Framework*"
    )

    url = _run_gh([
        "pr", "create",
        "--base", base_branch,
        "--head", branch_name,
        "--title", title,
        "--body", body,
    ])
    return url


def get_branch_diff(branch_name: str, base_branch: str = "main") -> list[dict]:
    """Get file-level diff stats between base and branch.

    Returns a list of {path, added, removed, status} dicts.
    Status is one of: added, modified, deleted, renamed.
    """
    _ensure_repo()
    try:
        # Fetch latest base to compare against
        try:
            _run_git(["fetch", "origin", base_branch])
        except RuntimeError:
            pass

        # --numstat gives machine-readable: added\tremoved\tpath
        raw = _run_git(["diff", "--numstat", f"origin/{base_branch}...{branch_name}"])
        if not raw.strip():
            return []

        # Also get name-status for add/modify/delete/rename
        status_raw = _run_git(["diff", "--name-status", f"origin/{base_branch}...{branch_name}"])
        status_map: dict[str, str] = {}
        for line in status_raw.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                code = parts[0][0]  # A, M, D, R
                path = parts[-1]    # last part (handles renames)
                status_map[path] = {
                    "A": "added", "M": "modified", "D": "deleted", "R": "renamed",
                }.get(code, "modified")

        results: list[dict] = []
        for line in raw.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            added = int(parts[0]) if parts[0] != "-" else 0
            removed = int(parts[1]) if parts[1] != "-" else 0
            path = parts[2]
            results.append({
                "path": path,
                "added": added,
                "removed": removed,
                "status": status_map.get(path, "modified"),
            })

        return results
    except Exception as e:
        print(f"[git] Failed to get branch diff: {e}")
        return []


def get_branch_diff_live(base_branch: str = "main") -> list[dict]:
    """Get diff stats for the current working branch (including uncommitted changes)."""
    _ensure_repo()
    try:
        try:
            _run_git(["fetch", "origin", base_branch])
        except RuntimeError:
            pass

        # Diff from base to HEAD plus any uncommitted changes
        raw = _run_git(["diff", "--numstat", f"origin/{base_branch}...HEAD"])
        # Also include uncommitted changes
        uncommitted = _run_git(["diff", "--numstat", "HEAD"])

        all_lines = (raw.strip() + "\n" + uncommitted.strip()).strip()
        if not all_lines:
            return []

        # Aggregate by path
        path_stats: dict[str, dict] = {}
        for line in all_lines.split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            added = int(parts[0]) if parts[0] != "-" else 0
            removed = int(parts[1]) if parts[1] != "-" else 0
            path = parts[2]
            if path in path_stats:
                path_stats[path]["added"] += added
                path_stats[path]["removed"] += removed
            else:
                path_stats[path] = {"path": path, "added": added, "removed": removed, "status": "modified"}

        return list(path_stats.values())
    except Exception as e:
        print(f"[git] Failed to get live diff: {e}")
        return []


def has_changes() -> bool:
    """Check if there are any uncommitted or staged changes."""
    _ensure_repo()
    status = _run_git(["status", "--porcelain"])
    return bool(status.strip())


def get_current_branch() -> str:
    """Get the current branch name."""
    _ensure_repo()
    return _run_git(["branch", "--show-current"])


def get_work_dir() -> str:
    """Return the working directory where the agent should operate."""
    _ensure_repo()
    return _WORK_DIR
