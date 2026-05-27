"""
Project sync via git clone/pull/push against the gateway's bare git repos.

Local layout:
    ~/.sp/projects/{id}/{name}/
        .git/           ← single repo, all branches
        (working tree)  ← reflects the checked-out branch
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import httpx

from signalpilot import _loggers

LOGGER = _loggers.sp_logger()

PROJECTS_ROOT = Path.home() / ".sp" / "projects"


def _gateway_url() -> str:
    from signalpilot._utils.localhost import fix_localhost_url
    return fix_localhost_url(
        os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")
    ).rstrip("/")


def _gateway_headers() -> dict[str, str]:
    jwt = os.environ.get("SP_SESSION_JWT", "")
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


def _get_clone_url(project_id: str) -> str | None:
    """Return the authenticated clone URL (token embedded for git Basic Auth)."""
    info = get_clone_info(project_id)
    base_url = info.get("clone_url")
    if not base_url:
        return None

    token = info.get("auth_token", "")
    username = info.get("auth_username", "x-access-token")
    if token and "://" in base_url:
        scheme, rest = base_url.split("://", 1)
        return f"{scheme}://{username}:{token}@{rest}"
    return base_url


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
    """Single local path per project: ~/.sp/projects/{id}/{name}/"""
    name = _get_project_name(project_id)
    return PROJECTS_ROOT / project_id / name


# ── Sync operations ─────────────────────────────────────────────

def sync_down(project_id: str, branch: str = "main") -> dict[str, Any]:
    """Clone or pull latest from gateway bare repo."""
    repo = local_project_dir(project_id)
    clone_url = _get_clone_url(project_id)

    if not clone_url:
        return {"error": "No clone URL available", "local_dir": str(repo)}

    if not (repo / ".git").exists():
        # Fresh clone — remove dir if it exists (may be leftover from failed clone)
        import shutil
        import sys as _sys
        if repo.exists():
            if _sys.platform == "win32":
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
        LOGGER.info(f"Cloning project {project_id} to {repo}")
        code, out, err = _run_git(
            repo.parent, "clone", "--branch", branch, clone_url, str(repo),
            timeout=120,
        )
        if code != 0:
            # Branch might not exist, try without --branch
            LOGGER.warning(f"Clone with branch failed: {err.strip()}, trying default")
            code, out, err = _run_git(
                repo.parent, "clone", clone_url, str(repo),
                timeout=120,
            )
            if code != 0:
                LOGGER.error(f"Clone failed: {err}")
                return {"error": f"Clone failed: {err.strip()}", "local_dir": str(repo)}

        _run_git(repo, "config", "user.email", "notebook@signalpilot.dev")
        _run_git(repo, "config", "user.name", "SignalPilot")
    else:
        # Existing repo — fetch latest
        # Update remote URL (token may have refreshed)
        _run_git(repo, "remote", "set-url", "origin", clone_url)
        _run_git(repo, "fetch", "origin")

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
    if _git_remote_branch_exists(repo, branch):
        code, out, err = _run_git(repo, "pull", "--ff-only", "origin", branch)
        if code != 0:
            # ff-only failed (diverged), try regular pull
            _run_git(repo, "pull", "origin", branch, "--no-edit")

    file_count = sum(
        1 for f in repo.rglob("*")
        if f.is_file() and ".git" not in f.parts
    )

    LOGGER.info(f"Sync complete: {repo} branch={branch} files={file_count}")
    return {
        "local_dir": str(repo),
        "file_count": file_count,
        "branch": branch,
    }


def sync_up(project_id: str, branch: str = "main") -> dict[str, Any]:
    """Commit and push local changes to gateway."""
    repo = local_project_dir(project_id)
    if not (repo / ".git").exists():
        return {"error": "No local repo"}

    # Update remote URL (token refresh)
    clone_url = _get_clone_url(project_id)
    if clone_url:
        _run_git(repo, "remote", "set-url", "origin", clone_url)

    code, out, err = _run_git(repo, "push", "origin", branch)
    if code != 0:
        LOGGER.error(f"Push failed: {err}")
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
        LOGGER.error(f"Checkout failed: {err}")
        return {"error": err.strip()}

    return {"branch": branch, "switched": True}


# ── User workspace (S3 flat file backup) ────────────────────────

def _is_agent_mode() -> bool:
    return os.environ.get("SP_AGENT_MODE", "").lower() in ("true", "1", "yes")


def _user_id() -> str | None:
    if _is_agent_mode():
        return None
    return os.environ.get("SP_USER_ID")


def _workspace_url(project_id: str) -> str:
    return f"{_gateway_url()}/api/workspaces/{project_id}"


def workspace_status(project_id: str) -> dict[str, Any] | None:
    """Check if user workspace exists on S3."""
    uid = _user_id()
    if not uid:
        return None

    try:
        resp = httpx.get(
            f"{_workspace_url(project_id)}/status",
            headers=_gateway_headers(),
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def workspace_restore(project_id: str) -> dict[str, Any]:
    """Restore user workspace from S3 to local disk.
    Faster than git clone because it includes uncommitted work."""
    uid = _user_id()
    if not uid:
        return {"restored": False, "reason": "no user ID"}

    status = workspace_status(project_id)
    if not status or not status.get("exists") or status.get("file_count", 0) == 0:
        return {"restored": False, "reason": "no workspace"}

    repo = local_project_dir(project_id)
    repo.mkdir(parents=True, exist_ok=True)
    headers = _gateway_headers()
    base = _workspace_url(project_id)

    # List workspace files
    resp = httpx.get(f"{base}/files", headers=headers, timeout=30.0)
    if resp.status_code != 200:
        return {"restored": False, "reason": "failed to list files"}

    files = resp.json().get("files", [])
    restored = 0

    for f in files:
        key = f.get("key", "")
        if not key:
            continue

        file_resp = httpx.get(
            f"{base}/files/{key}",
            headers=headers,
            timeout=30.0,
        )
        if file_resp.status_code != 200:
            continue

        local_path = repo / key
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(file_resp.content)
        restored += 1

    LOGGER.info(f"Workspace restored: {restored} files to {repo}")
    return {"restored": True, "file_count": restored, "local_dir": str(repo)}


def workspace_save_file(project_id: str, relative_path: str, content: bytes) -> bool:
    """Save a single file to the user's S3 workspace."""
    uid = _user_id()
    if not uid:
        return False

    headers = _gateway_headers()
    ext = os.path.splitext(relative_path)[1].lower()
    ct = {
        ".sql": "text/sql", ".yml": "text/yaml", ".yaml": "text/yaml",
        ".py": "text/x-python", ".json": "application/json", ".csv": "text/csv",
    }.get(ext, "application/octet-stream")

    try:
        resp = httpx.put(
            f"{_workspace_url(project_id)}/files/{relative_path}",
            content=content,
            headers={**headers, "Content-Type": ct},
            timeout=15.0,
        )
        return resp.status_code == 201
    except Exception as e:
        LOGGER.debug(f"Workspace save failed for {relative_path}: {e}")
        return False


def workspace_delete_file(project_id: str, relative_path: str) -> bool:
    """Delete a file from the user's S3 workspace."""
    uid = _user_id()
    if not uid:
        return False

    try:
        resp = httpx.delete(
            f"{_workspace_url(project_id)}/files/{relative_path}",
            headers=_gateway_headers(),
            timeout=10.0,
        )
        return resp.status_code == 204
    except Exception:
        return False


def workspace_clear(project_id: str) -> bool:
    """Clear the user's workspace for this project."""
    uid = _user_id()
    if not uid:
        return False

    try:
        resp = httpx.delete(
            _workspace_url(project_id),
            headers=_gateway_headers(),
            timeout=15.0,
        )
        return resp.status_code == 204
    except Exception:
        return False


# ── Unified entry point ─────────────────────────────────────────

def sync_project(project_id: str, branch: str = "main") -> dict[str, Any]:
    """Sync a project to local disk.

    1. Git clone/pull (always, this is the source of truth)
    2. Overlay workspace files on top (uncommitted work from last session)
    """
    # Always git clone/pull first
    result = sync_down(project_id, branch)
    if "error" in result:
        return result

    # Then overlay workspace files (restores uncommitted changes)
    if _user_id():
        ws = workspace_restore(project_id)
        if ws.get("restored"):
            LOGGER.info(f"Overlaid {ws.get('file_count', 0)} workspace files on top of clone")
            result["workspace_restored"] = ws.get("file_count", 0)

    return result


