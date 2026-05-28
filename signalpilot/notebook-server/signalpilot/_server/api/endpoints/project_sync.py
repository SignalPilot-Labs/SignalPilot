"""
Project sync endpoints: pull files from gateway to local disk,
push local changes back.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.authentication import requires
from starlette.responses import JSONResponse, Response

from signalpilot import _loggers
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.requests import Request

LOGGER = _loggers.sp_logger()
router = APIRouter()


@router.post("/sync-down")
@requires("edit")
async def sync_down(*, request: Request) -> Response:
    """
    Download all files from the gateway branch to a local directory.
    Returns the local directory path and file count.
    """
    from signalpilot._server.files.project_sync import sync_project

    project_id = request.headers.get("x-gateway-project-id", "")
    branch = request.headers.get("x-gateway-branch-id", "main")

    if not project_id:
        return JSONResponse(
            {"error": "Missing X-Gateway-Project-Id header"},
            status_code=400,
        )

    try:
        result = sync_project(project_id, branch)
        return JSONResponse(result)
    except Exception as e:
        LOGGER.error(f"Sync down failed: {e}")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


@router.post("/sync-status")
@requires("edit")
async def sync_status(*, request: Request) -> Response:
    """Return the local project directory and whether it exists."""
    from signalpilot._server.files.project_sync import local_project_dir

    project_id = request.headers.get("x-gateway-project-id", "")
    branch = request.headers.get("x-gateway-branch-id", "main")

    if not project_id:
        return JSONResponse({"synced": False, "local_dir": None})

    local_dir = local_project_dir(project_id)
    has_git = (local_dir / ".git").exists()
    file_count = sum(
        1 for f in local_dir.rglob("*")
        if f.is_file() and ".git" not in f.parts
    ) if has_git else 0

    return JSONResponse({
        "synced": has_git and file_count > 0,
        "local_dir": str(local_dir),
        "file_count": file_count,
    })
