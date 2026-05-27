# Copyright 2026 SignalPilot. All rights reserved.
"""
Branch management via local git commands.

All operations run against the local git clone.
Branches are pushed to/deleted from the gateway bare repo via git push.
"""
from __future__ import annotations

import subprocess
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


def _get_repo(request: Request) -> Path | None:
    project_id = request.headers.get("x-gateway-project-id")
    if not project_id:
        return None
    from signalpilot._server.files.project_sync import local_project_dir
    d = local_project_dir(project_id)
    return d if (d / ".git").exists() else None


def _run_git(repo: Path, *args: str) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


@router.post("/list")
@requires("edit")
async def list_branches(*, request: Request) -> Response:
    """List all branches (local + remote)."""
    repo = _get_repo(request)
    if not repo:
        return JSONResponse({"branches": []})

    # Fetch latest from remote
    _run_git(repo, "fetch", "origin")

    code, out, _ = _run_git(
        repo, "branch", "-a",
        "--format=%(refname:short)\t%(objectname:short)\t%(creatordate:relative)\t%(creatordate:unix)",
    )
    if code != 0:
        return JSONResponse({"branches": []})

    _, current, _ = _run_git(repo, "branch", "--show-current")
    current = current.strip()

    seen = set()
    branches = []
    for line in out.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        name = parts[0]
        sha = parts[1] if len(parts) > 1 else ""
        date = parts[2] if len(parts) > 2 else ""
        timestamp = int(parts[3]) if len(parts) > 3 and parts[3].strip().isdigit() else 0

        # Normalize remote branch names: origin/main → main
        display_name = name
        is_remote = False
        if name.startswith("origin/"):
            display_name = name[len("origin/"):]
            is_remote = True
            if display_name == "HEAD":
                continue

        if display_name in seen:
            continue
        seen.add(display_name)

        branches.append({
            "name": display_name,
            "sha": sha,
            "date": date,
            "timestamp": timestamp,
            "is_current": display_name == current,
            "is_remote": is_remote,
            "is_local": _branch_exists_local(repo, display_name),
            "is_agent": display_name.startswith("agent/"),
        })

    return JSONResponse({"branches": branches})


def _branch_exists_local(repo: Path, name: str) -> bool:
    code, _, _ = _run_git(repo, "rev-parse", "--verify", f"refs/heads/{name}")
    return code == 0


@router.post("/create")
@requires("edit")
async def create_branch(*, request: Request) -> Response:
    """Create a new branch. Body: name and optional from_branch."""
    repo = _get_repo(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    body = await request.json()
    name = body.get("name", "").strip()
    from_branch = body.get("source_branch") or body.get("from_branch") or ""

    if not name:
        return JSONResponse({"error": "Branch name required"}, status_code=400)

    # Discard local changes before creating branch
    _run_git(repo, "checkout", "--force", "--", ".")
    _run_git(repo, "clean", "-fd")

    # Create from source branch if specified
    if from_branch:
        code, _, err = _run_git(repo, "checkout", "-b", name, from_branch)
    else:
        code, _, err = _run_git(repo, "checkout", "-b", name)

    if code != 0:
        return JSONResponse({"error": err.strip()}, status_code=500)

    # Push to remote so it exists on the gateway
    _run_git(repo, "push", "-u", "origin", name)

    return JSONResponse({"name": name, "created": True})


@router.post("/delete")
@requires("edit")
async def delete_branch(*, request: Request) -> Response:
    """Delete a branch. Body: {name}"""
    repo = _get_repo(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "Branch name required"}, status_code=400)

    # Don't delete current branch
    _, current, _ = _run_git(repo, "branch", "--show-current")
    if name == current.strip():
        return JSONResponse({"error": "Cannot delete current branch"}, status_code=400)

    # Delete local
    _run_git(repo, "branch", "-D", name)

    # Delete remote
    _run_git(repo, "push", "origin", "--delete", name)

    return JSONResponse({"name": name, "deleted": True})


@router.post("/current")
@requires("edit")
async def get_current_branch(*, request: Request) -> Response:
    """Get the current git branch."""
    repo = _get_repo(request)
    if not repo:
        return JSONResponse({"active_branch": "main"})

    _, out, _ = _run_git(repo, "branch", "--show-current")
    return JSONResponse({"active_branch": out.strip() or "main"})


@router.post("/switch")
@requires("edit")
async def switch_branch(*, request: Request) -> Response:
    """Switch branch. Body: {branch}"""
    repo = _get_repo(request)
    if not repo:
        return JSONResponse({"error": "No local repo"}, status_code=400)

    body = await request.json()
    branch = body.get("branch", "").strip()
    if not branch:
        return JSONResponse({"error": "Branch name required"}, status_code=400)

    from signalpilot._server.files.project_sync import checkout_branch

    project_id = request.headers.get("x-gateway-project-id", "")
    result = checkout_branch(project_id, branch)
    if "error" in result:
        return JSONResponse(result, status_code=500)
    return JSONResponse(result)
