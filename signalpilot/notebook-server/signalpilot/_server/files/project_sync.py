"""
Project sync via git clone/pull/push against the gateway's bare git repos.

Local layout:
    ~/.sp/projects/{id}/{name}/
        .git/           ← single repo, all branches
        (working tree)  ← reflects the checked-out branch
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from signalpilot import _loggers
from signalpilot._server.auth.session_token import load_session_jwt

LOGGER = _loggers.sp_logger()

PROJECTS_ROOT = Path.home() / ".sp" / "projects"

_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _validate_branch(branch: str) -> None:
    """Reject branch names that could be used for argument injection."""
    if not branch or branch.startswith("-") or not _BRANCH_RE.match(branch):
        raise ValueError(f"Invalid branch name: {branch!r}")


def _validate_project_id(project_id: str) -> None:
    """Reject project IDs that are not valid UUIDs."""
    if not project_id or not _UUID_RE.match(project_id):
        raise ValueError(f"Invalid project ID: {project_id!r}")


def _redact_url(url: str) -> str:
    """Strip userinfo from a URL to prevent credential leakage in logs."""
    return re.sub(r"://[^@]*@", "://", url)


def _gateway_url() -> str:
    from signalpilot._utils.localhost import fix_localhost_url
    return fix_localhost_url(
        os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")
    ).rstrip("/")


def _gateway_headers() -> dict[str, str]:
    jwt = load_session_jwt()
    if jwt:
        return {"Authorization": f"Bearer {jwt}"}
    api_key = os.environ.get("SP_API_KEY", "")
    if api_key:
        return {"X-API-Key": api_key}
    return {}


def _run_git(repo: Path, *args: str, timeout: int = 60) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def _run_git_authed(repo: Path, auth_header: str, *args: str, timeout: int = 60) -> tuple[int, str, str]:
    """Run a git command with HTTP auth header passed via -c (not URL-embedded)."""
    result = subprocess.run(
        ["git", "-c", f"http.extraHeader=Authorization: {auth_header}", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def _make_basic_auth_header(username: str, token: str) -> str:
    """Return the value for an Authorization header using HTTP Basic Auth."""
    encoded = base64.b64encode(f"{username}:{token}".encode()).decode()
    return f"Basic {encoded}"


# ── Project name cache ───────────────────────────────────────────

_project_name_cache: dict[str, str] = {}


def _fetch_project_name(project_id: str) -> str:
    try:
        resp = httpx.get(
            f"{_gateway_url()}/api/workspace-projects/{project_id}",
            headers=_gateway_headers(),
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("name") or data.get("display_name") or project_id
    except Exception:
        pass
    return project_id


def _get_project_name(project_id: str) -> str:
    if project_id not in _project_name_cache:
        _project_name_cache[project_id] = _fetch_project_name(project_id)
    return _project_name_cache[project_id]


# ── Clone URL ────────────────────────────────────────────────────

_clone_url_cache: dict[str, dict[str, Any]] = {}


def _gateway_url_raw() -> str:
    """Gateway URL without localhost→127.0.0.1 rewrite (for clone URLs)."""
    return os.environ.get("SP_GATEWAY_URL", "http://localhost:3300").rstrip("/")


def get_clone_info(project_id: str) -> dict[str, Any]:
    """Fetch clone URL and metadata from gateway.

    Uses the raw gateway URL (not rewritten) so the clone URL the gateway
    returns matches the hostname its git HTTP handler is bound to.
    """
    cached = _clone_url_cache.get(project_id)
    if cached and cached.get("clone_url"):
        return cached

    try:
        resp = httpx.get(
            f"{_gateway_url_raw()}/api/workspace-projects/{project_id}/clone-url",
            headers=_gateway_headers(),
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("clone_url"):
                _clone_url_cache[project_id] = data
            return data
    except Exception:
        pass
    return {"clone_url": None, "default_branch": "main", "source": "managed"}


def _get_clone_url_and_auth(project_id: str) -> tuple[str | None, str | None]:
    """Return (clean_url, auth_header_value) without embedding credentials in the URL."""
    info = get_clone_info(project_id)
    base_url = info.get("clone_url")
    if not base_url:
        return None, None

    token = info.get("auth_token", "")
    username = info.get("auth_username", "x-access-token")
    if token:
        return base_url, _make_basic_auth_header(username, token)
    return base_url, None


def _get_github_remote(project_id: str) -> str | None:
    """Fetch the git_remote (GitHub URL) from the project metadata."""
    try:
        resp = httpx.get(
            f"{_gateway_url()}/api/workspace-projects/{project_id}",
            headers=_gateway_headers(),
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json().get("git_remote")
    except Exception:
        pass
    return None


# ── Local project directory ──────────────────────────────────────

def local_project_dir(project_id: str, branch: str = "") -> Path:
    """Single local path per project: ~/.sp/projects/{id}/{name}/

    Falls back to scanning the project directory when the gateway name
    lookup fails (e.g. project deleted from DB but files still on disk).
    """
    name = _get_project_name(project_id)
    resolved = PROJECTS_ROOT / project_id / name
    if resolved.exists():
        return resolved

    # Name lookup returned the UUID itself (gateway unreachable or project
    # not found). Scan the project directory for the actual subdirectory.
    project_parent = PROJECTS_ROOT / project_id
    if project_parent.exists():
        subdirs = [d for d in project_parent.iterdir() if d.is_dir() and d.name != project_id]
        if len(subdirs) == 1:
            LOGGER.debug("Resolved project dir via scan: %s", subdirs[0])
            return subdirs[0]
        # Multiple subdirs or none — check for one with .git
        git_dirs = [d for d in subdirs if (d / ".git").exists()]
        if len(git_dirs) == 1:
            LOGGER.debug("Resolved project dir via .git scan: %s", git_dirs[0])
            return git_dirs[0]

    return resolved


# ── Sync operations ─────────────────────────────────────────────

def sync_down(project_id: str, branch: str = "main") -> dict[str, Any]:
    """Clone or pull latest from gateway bare repo."""
    from signalpilot._server.files.git_auth import (
        purge_persisted_auth,
        run_git_authed as _run_ga,
    )

    _validate_branch(branch)
    repo = local_project_dir(project_id)

    # Upgrade safety: scrub any stale http.extraHeader written by pre-F-9 code.
    purge_persisted_auth(repo)

    clone_url, auth_header = _get_clone_url_and_auth(project_id)

    if not clone_url:
        return {"error": "No clone URL available", "local_dir": str(repo)}

    if not (repo / ".git").exists():
        # Fresh clone — remove dir if it exists (may be leftover from failed clone)
        if repo.exists():
            if sys.platform == "win32":
                subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(repo)],
                               capture_output=True, timeout=10)
            if repo.exists():
                shutil.rmtree(str(repo), ignore_errors=True)
            if repo.exists():
                stale = repo.parent / f".stale-{repo.name}-{os.getpid()}"
                try:
                    repo.rename(stale)
                    shutil.rmtree(str(stale), ignore_errors=True)
                except Exception:
                    pass
        repo.parent.mkdir(parents=True, exist_ok=True)
        LOGGER.info("Cloning project %s to %s", project_id, repo)
        if auth_header:
            code, out, err = _run_git_authed(
                repo.parent, auth_header,
                "clone", "--branch", branch, clone_url, str(repo),
                timeout=120,
            )
        else:
            code, out, err = _run_git(
                repo.parent, "clone", "--branch", branch, clone_url, str(repo),
                timeout=120,
            )
        if code != 0:
            LOGGER.warning("Clone with branch failed: %s, trying default", err.strip())
            if auth_header:
                code, out, err = _run_git_authed(
                    repo.parent, auth_header,
                    "clone", clone_url, str(repo),
                    timeout=120,
                )
            else:
                code, out, err = _run_git(
                    repo.parent, "clone", clone_url, str(repo),
                    timeout=120,
                )
            if code != 0:
                LOGGER.error("Clone failed: %s", _redact_url(err))
                return {"error": f"Clone failed: {err.strip()}", "local_dir": str(repo)}

        _run_git(repo, "config", "user.email", "notebook@signalpilot.dev")
        _run_git(repo, "config", "user.name", "SignalPilot")
        # Auth header is per-process via -c; never persist into .git/config.
    else:
        # Existing repo — fetch latest (auth passed per-invocation, not persisted)
        _run_ga(repo, project_id, "fetch", "origin")

    # Checkout the requested branch — hard reset, discard all local changes
    current = _current_git_branch(repo)
    if current != branch:
        _run_git(repo, "checkout", "--force", "--", ".")
        _run_git(repo, "clean", "-fd")

        if _git_branch_exists(repo, branch):
            _run_git(repo, "checkout", branch)
        elif _git_remote_branch_exists(repo, branch):
            _run_git(repo, "checkout", "-b", branch, f"origin/{branch}")
        else:
            _run_git(repo, "checkout", "-b", branch)

    # Pull latest from remote (fast-forward if possible)
    # Use authed runner — pull is a remote operation and credentials must not be persisted.
    if _git_remote_branch_exists(repo, branch):
        code, out, err = _run_ga(repo, project_id, "pull", "--ff-only", "origin", branch)
        if code != 0:
            _run_ga(repo, project_id, "pull", "origin", branch, "--no-edit")

    file_count = sum(
        1 for f in repo.rglob("*")
        if f.is_file() and ".git" not in f.parts
    )

    LOGGER.info("Sync complete: %s branch=%s files=%d", repo, branch, file_count)
    return {
        "local_dir": str(repo),
        "file_count": file_count,
        "branch": branch,
    }


def sync_up(project_id: str, branch: str = "main") -> dict[str, Any]:
    """Commit and push local changes to gateway."""
    from signalpilot._server.files.git_auth import (
        purge_persisted_auth,
        run_git_authed as _run_ga,
    )

    _validate_branch(branch)
    repo = local_project_dir(project_id)
    if not (repo / ".git").exists():
        return {"error": "No local repo"}

    # Upgrade safety: scrub any stale http.extraHeader written by pre-F-9 code.
    purge_persisted_auth(repo)

    # Auth header is per-process via -c; never persist into .git/config.
    code, out, err = _run_ga(repo, project_id, "push", "origin", branch)
    if code != 0:
        LOGGER.error("Push failed: %s", _redact_url(err))
        return {"error": err.strip()}

    return {"success": True, "output": out.strip()}


# ── Branch helpers ───────────────────────────────────────────────

def _current_git_branch(repo: Path) -> str | None:
    code, out, _ = _run_git(repo, "branch", "--show-current")
    return out.strip() if code == 0 and out.strip() else None


def _git_branch_exists(repo: Path, branch: str) -> bool:
    code, _, _ = _run_git(repo, "rev-parse", "--verify", f"refs/heads/{branch}")
    return code == 0


def _git_remote_branch_exists(repo: Path, branch: str) -> bool:
    code, _, _ = _run_git(repo, "rev-parse", "--verify", f"refs/remotes/origin/{branch}")
    return code == 0


def checkout_branch(project_id: str, branch: str) -> dict[str, Any]:
    """Switch to a git branch. Creates from origin if needed."""
    _validate_branch(branch)
    repo = local_project_dir(project_id)
    if not repo.exists():
        return {"error": "Project not synced yet"}

    current = _current_git_branch(repo)
    if current == branch:
        return {"branch": branch, "switched": False}

    # Discard uncommitted local changes before switching
    _run_git(repo, "checkout", "--force", "--", ".")
    _run_git(repo, "clean", "-fd")

    if _git_branch_exists(repo, branch):
        code, _, err = _run_git(repo, "checkout", branch)
    elif _git_remote_branch_exists(repo, branch):
        code, _, err = _run_git(repo, "checkout", "-b", branch, f"origin/{branch}")
    else:
        code, _, err = _run_git(repo, "checkout", "-b", branch)

    if code != 0:
        LOGGER.error("Checkout failed: %s", err)
        return {"error": err.strip()}

    return {"branch": branch, "switched": True}


# ── Unified entry point ─────────────────────────────────────────

def sync_project(project_id: str, branch: str = "main") -> dict[str, Any]:
    """Sync a project to local disk via git clone/pull."""
    return sync_down(project_id, branch)
