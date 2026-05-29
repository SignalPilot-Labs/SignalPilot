"""Git operations for cloud project local repos."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.authentication import requires
from starlette.responses import JSONResponse, Response

from signalpilot import _loggers
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.requests import Request

LOGGER = _loggers.sp_logger()
router = APIRouter()


def _get_repo_dir(request: Request) -> Path | None:
    project_id = request.headers.get("x-gateway-project-id")
    if not project_id:
        return None
    from signalpilot._server.files.project_sync import local_project_dir
    d = local_project_dir(project_id)
    return d if d.exists() else None


def _run_git(repo: Path, *args: str) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


@router.post("/status")
@requires("edit")
async def git_status(*, request: Request) -> Response:
    """Get git status: changed, staged, and untracked files."""
    repo = _get_repo_dir(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    code, out, err = _run_git(repo, "status", "--porcelain=v1")
    if code != 0:
        return JSONResponse({"error": err}, status_code=500)

    staged = []
    changed = []
    untracked = []

    for line in out.split("\n"):
        if len(line) < 4:
            continue
        x = line[0]
        y = line[1]
        # Path starts at index 3 (after "XY ")
        path = line[3:]
        # Handle renames: "R  old -> new"
        if " -> " in path:
            path = path.split(" -> ")[-1]

        if x == "?":
            untracked.append({"path": path})
        else:
            if x != " ":
                staged.append({"path": path, "status": x})
            if y != " ":
                changed.append({"path": path, "status": y})

    return JSONResponse({
        "staged": staged,
        "changed": changed,
        "untracked": untracked,
    })


@router.post("/stage")
@requires("edit")
async def git_stage(*, request: Request) -> Response:
    """Stage files. Body: paths list or all flag."""
    repo = _get_repo_dir(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    body = await request.json()
    if body.get("all"):
        code, _, err = _run_git(repo, "add", "-A")
    else:
        paths = body.get("paths", [])
        if not paths:
            return JSONResponse({"error": "No paths"}, status_code=400)
        code, _, err = _run_git(repo, "add", "--", *paths)

    if code != 0:
        return JSONResponse({"error": err}, status_code=500)
    return JSONResponse({"success": True})


@router.post("/unstage")
@requires("edit")
async def git_unstage(*, request: Request) -> Response:
    """Unstage files. Body: paths list or all flag."""
    repo = _get_repo_dir(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    body = await request.json()
    if body.get("all"):
        code, _, err = _run_git(repo, "reset", "HEAD")
    else:
        paths = body.get("paths", [])
        if not paths:
            return JSONResponse({"error": "No paths"}, status_code=400)
        code, _, err = _run_git(repo, "reset", "HEAD", "--", *paths)

    if code != 0:
        return JSONResponse({"error": err}, status_code=500)
    return JSONResponse({"success": True})


@router.post("/commit")
@requires("edit")
async def git_commit(*, request: Request) -> Response:
    """Commit staged files. Body: message string."""
    repo = _get_repo_dir(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    body = await request.json()
    message = body.get("message", "").strip()
    if not message:
        return JSONResponse({"error": "Commit message required"}, status_code=400)

    code, out, err = _run_git(repo, "commit", "-m", message)
    if code != 0:
        return JSONResponse({"error": err.strip() or out.strip()}, status_code=500)
    return JSONResponse({"success": True, "output": out.strip()})


@router.post("/checkout")
@requires("edit")
async def git_checkout(*, request: Request) -> Response:
    """Switch git branch. Body: branch name and optional create flag."""
    repo = _get_repo_dir(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    body = await request.json()
    branch = body.get("branch", "").strip()
    create = body.get("create", False)
    if not branch:
        return JSONResponse({"error": "Branch name required"}, status_code=400)

    from signalpilot._server.files.project_sync import checkout_branch

    project_id = request.headers.get("x-gateway-project-id", "")
    result = checkout_branch(project_id, branch)
    if "error" in result:
        return JSONResponse(result, status_code=500)
    return JSONResponse(result)


@router.post("/push")
@requires("edit")
async def git_push_to_cloud(*, request: Request) -> Response:
    """Push to the gateway bare repo (or GitHub) via git push."""
    repo = _get_repo_dir(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    branch = request.headers.get("x-gateway-branch-id", "main")
    project_id = request.headers.get("x-gateway-project-id", "")

    # Refresh remote URL (token may have changed)
    from signalpilot._server.files.project_sync import _get_clone_url_and_auth

    clone_url, _ = _get_clone_url_and_auth(project_id)
    if clone_url:
        _run_git(repo, "remote", "set-url", "origin", clone_url)

    code, out, err = _run_git(repo, "push", "origin", branch)
    if code != 0:
        return JSONResponse({"error": err.strip() or out.strip()}, status_code=500)

    return JSONResponse({"success": True, "output": out.strip()})


@router.post("/log")
@requires("edit")
async def git_log(*, request: Request) -> Response:
    """Get recent commit history with local/remote sync status."""
    repo = _get_repo_dir(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    branch = request.headers.get("x-gateway-branch-id", "main")

    # Get the remote HEAD sha for this branch (if it exists)
    remote_sha: str | None = None
    code, out, _ = _run_git(repo, "rev-parse", f"origin/{branch}")
    if code == 0:
        remote_sha = out.strip()

    # Get log with full shas for comparison
    code, out, err = _run_git(
        repo, "log", f"--format=%H %s", "-20",
    )
    if code != 0:
        return JSONResponse({"commits": []})

    # Find which commits are ahead of remote
    local_only_shas: set[str] = set()
    if remote_sha:
        rc, ahead_out, _ = _run_git(
            repo, "log", "--format=%H", f"origin/{branch}..HEAD",
        )
        if rc == 0:
            local_only_shas = {s.strip() for s in ahead_out.strip().split("\n") if s.strip()}

    commits = []
    for line in out.strip().split("\n"):
        if not line:
            continue
        full_sha, _, msg = line.partition(" ")
        short_sha = full_sha[:7]
        location = "local" if full_sha in local_only_shas else "remote"
        commits.append({"sha": short_sha, "full_sha": full_sha, "message": msg, "location": location})

    return JSONResponse({
        "commits": commits,
        "remote_sha": remote_sha[:7] if remote_sha else None,
    })


@router.post("/fetch")
@requires("edit")
async def git_fetch(*, request: Request) -> Response:
    """Fetch from remote (GitHub or refresh credentials for managed).
    Returns ahead/behind counts relative to the remote branch."""
    repo = _get_repo_dir(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    branch = request.headers.get("x-gateway-branch-id", "main")
    project_id = request.headers.get("x-gateway-project-id", "")

    # Refresh remote URL if GitHub-linked (token may have expired)
    from signalpilot._server.files.project_sync import _get_clone_url_and_auth

    # Refresh remote URL (token may have expired)
    clone_url, _ = _get_clone_url_and_auth(project_id)
    if clone_url:
        _run_git(repo, "remote", "set-url", "origin", clone_url)

    # Fetch from remote
    has_remote = False
    code, out, _ = _run_git(repo, "remote")
    if out.strip():
        code, _, _ = _run_git(repo, "fetch", "origin")
        has_remote = code == 0

    # Calculate ahead/behind
    ahead = 0
    behind = 0
    if has_remote:
        code, out, _ = _run_git(
            repo, "rev-list", "--left-right", "--count",
            f"HEAD...origin/{branch}",
        )
        if code == 0 and "\t" in out.strip():
            parts = out.strip().split("\t")
            ahead = int(parts[0])
            behind = int(parts[1])

    # Current branch
    _, current_branch, _ = _run_git(repo, "branch", "--show-current")

    return JSONResponse({
        "branch": current_branch.strip(),
        "has_remote": has_remote,
        "ahead": ahead,
        "behind": behind,
    })


@router.post("/pull")
@requires("edit")
async def git_pull(*, request: Request) -> Response:
    """Pull from remote. Merges remote changes into current branch."""
    repo = _get_repo_dir(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    branch = request.headers.get("x-gateway-branch-id", "main")
    project_id = request.headers.get("x-gateway-project-id", "")

    # Refresh remote URL for GitHub projects
    from signalpilot._server.files.project_sync import _get_clone_url_and_auth

    # Refresh remote URL (token may have expired)
    clone_url, _ = _get_clone_url_and_auth(project_id)
    if clone_url:
        _run_git(repo, "remote", "set-url", "origin", clone_url)

    code, out, err = _run_git(repo, "pull", "origin", branch)
    if code != 0:
        # Check for merge conflict
        _, status_out, _ = _run_git(repo, "status", "--porcelain=v1")
        conflicts = [l[3:] for l in status_out.split("\n") if l.startswith("UU") or l.startswith("AA")]
        if conflicts:
            return JSONResponse({
                "success": False,
                "conflict": True,
                "files": conflicts,
                "error": "Merge conflict",
            })
        return JSONResponse({"success": False, "error": err.strip() or out.strip()})

    return JSONResponse({"success": True, "output": out.strip()})


@router.post("/force-reset")
@requires("edit")
async def git_force_reset(*, request: Request) -> Response:
    """Delete local repo and re-clone from remote. Loses all unpushed work."""
    project_id = request.headers.get("x-gateway-project-id", "")
    branch = request.headers.get("x-gateway-branch-id", "main")

    if not project_id:
        return JSONResponse({"error": "No project ID"}, status_code=400)

    import shutil
    from signalpilot._server.files.project_sync import (
        local_project_dir,
        sync_down,
    )

    repo = local_project_dir(project_id)

    # Nuke the local repo (Windows: git locks files, so try multiple strategies)
    if repo.exists():
        # Kill any git processes that might hold locks
        import subprocess
        if sys.platform == "win32":
            subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(repo)],
                           capture_output=True, timeout=10)
        else:
            shutil.rmtree(str(repo), ignore_errors=True)

        # If it still exists, rename it out of the way
        if repo.exists():
            stale = repo.parent / f".stale-{repo.name}-{os.getpid()}"
            try:
                repo.rename(stale)
                shutil.rmtree(str(stale), ignore_errors=True)
            except Exception:
                shutil.rmtree(str(repo), ignore_errors=True)

        LOGGER.info(f"[Force Reset] Deleted {repo}")

    # Fresh clone
    result = sync_down(project_id, branch)
    if "error" in result:
        return JSONResponse(result, status_code=500)

    return JSONResponse({
        "success": True,
        "local_dir": result.get("local_dir"),
        "file_count": result.get("file_count"),
    })


@router.post("/branches-local")
@requires("edit")
async def list_local_branches(*, request: Request) -> Response:
    """List all local git branches (includes agent branches not on remote)."""
    repo = _get_repo_dir(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    code, out, _ = _run_git(repo, "branch", "--format=%(refname:short)\t%(upstream:short)\t%(upstream:track)")
    if code != 0:
        return JSONResponse({"branches": []})

    _, current, _ = _run_git(repo, "branch", "--show-current")
    current = current.strip()

    branches = []
    for line in out.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        name = parts[0]
        upstream = parts[1] if len(parts) > 1 else ""
        track = parts[2] if len(parts) > 2 else ""

        branches.append({
            "name": name,
            "current": name == current,
            "has_remote": bool(upstream),
            "track": track.strip("[] ") if track else "",
            "is_agent": name.startswith("agent/"),
        })

    return JSONResponse({"branches": branches})


@router.post("/diff")
@requires("edit")
async def git_diff(*, request: Request) -> Response:
    """Get diff of working tree changes. Body: optional file path and staged flag."""
    repo = _get_repo_dir(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    file_path = body.get("file")
    staged = body.get("staged", False)

    args = ["diff", "--stat"]
    if staged:
        args.append("--cached")
    if file_path:
        args.extend(["--", file_path])

    code, stat_out, _ = _run_git(repo, *args)

    # Also get the actual diff content
    detail_args = ["diff"]
    if staged:
        detail_args.append("--cached")
    if file_path:
        detail_args.extend(["--", file_path])

    _, diff_out, _ = _run_git(repo, *detail_args)

    return JSONResponse({
        "stat": stat_out.strip(),
        "diff": diff_out[:50000],  # cap at 50KB
    })


@router.post("/info")
@requires("edit")
async def git_info(*, request: Request) -> Response:
    """Comprehensive git info for the panel header."""
    repo = _get_repo_dir(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    project_id = request.headers.get("x-gateway-project-id", "")
    branch = request.headers.get("x-gateway-branch-id", "main")

    # Current branch
    _, current_branch, _ = _run_git(repo, "branch", "--show-current")

    # Last commit
    _, last_commit, _ = _run_git(repo, "log", "-1", "--format=%h %s (%cr)")

    # Ahead/behind (if remote exists)
    ahead = 0
    behind = 0
    code, out, _ = _run_git(repo, "remote")
    has_remote = bool(out.strip())
    if has_remote:
        code, out, _ = _run_git(
            repo, "rev-list", "--left-right", "--count",
            f"HEAD...origin/{branch}",
        )
        if code == 0 and "\t" in out.strip():
            parts = out.strip().split("\t")
            ahead = int(parts[0])
            behind = int(parts[1])

    # File counts
    _, status_out, _ = _run_git(repo, "status", "--porcelain=v1")
    staged_count = 0
    changed_count = 0
    untracked_count = 0
    for line in status_out.split("\n"):
        if len(line) < 4:
            continue
        x, y = line[0], line[1]
        if x == "?":
            untracked_count += 1
        else:
            if x != " ":
                staged_count += 1
            if y != " ":
                changed_count += 1

    return JSONResponse({
        "branch": current_branch.strip(),
        "last_commit": last_commit.strip(),
        "has_remote": has_remote,
        "ahead": ahead,
        "behind": behind,
        "staged_count": staged_count,
        "changed_count": changed_count,
        "untracked_count": untracked_count,
    })
