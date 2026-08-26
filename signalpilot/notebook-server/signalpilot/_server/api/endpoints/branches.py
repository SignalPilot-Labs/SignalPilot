"""Branch management over the S3 workspace store.

There is no local git clone anymore: S3 holds every branch as a manifest
history behind the gateway Workspace Files API. Switching branches is
nothing more than pointing the session's :class:`GatewayFileSystem` at a
different branch name; creating a branch is a single reference-upsert
commit that forks the source branch's head manifest.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.authentication import requires
from starlette.responses import JSONResponse, Response

from signalpilot import _loggers
from signalpilot._server.files import workspace
from signalpilot._server.files.gateway_file_system import (
    GatewayFileSystemError,
)
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.requests import Request

LOGGER = _loggers.sp_logger()
router = APIRouter()


def _require_s3() -> JSONResponse | None:
    if not workspace.is_s3_workspace():
        return JSONResponse(
            {"error": "Branches are only available for cloud projects"},
            status_code=400,
        )
    return None


@router.post("/list")
@requires("edit")
async def list_branches(*, request: Request) -> Response:
    """List known branches.

    The gateway Files API has no branch-enumeration endpoint yet, so this
    reports the session's active branch (which always exists in S3).
    """
    del request
    if not workspace.is_s3_workspace():
        return JSONResponse({"branches": []})
    current = workspace.current_branch()
    return JSONResponse(
        {
            "branches": [
                {
                    "name": current,
                    "is_current": True,
                    "is_remote": True,
                    "is_local": True,
                    "is_agent": current.startswith("agent/"),
                }
            ]
        }
    )


@router.post("/create")
@requires("edit")
async def create_branch(*, request: Request) -> Response:
    """Create a branch by forking the source branch's head manifest."""
    error = _require_s3()
    if error is not None:
        return error

    body = await request.json()
    name = str(body.get("name") or "").strip()
    source = str(
        body.get("source_branch") or body.get("from_branch") or ""
    ).strip()
    if not name:
        return JSONResponse({"error": "Branch name required"}, status_code=400)

    try:
        workspace.validate_branch(name)
        if source:
            workspace.validate_branch(source)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    fs = workspace.create_file_system(
        branch=source or workspace.current_branch()
    )
    try:
        revision = fs.fork_branch(name)
    except GatewayFileSystemError as exc:
        LOGGER.error("Branch fork failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)

    workspace.set_current_branch(name)
    return JSONResponse({"name": name, "created": True, "revision": revision})


@router.post("/delete")
@requires("edit")
async def delete_branch(*, request: Request) -> Response:
    """Branch deletion is a gateway/store concern (revision history must be
    preserved); the notebook server cannot delete branches."""
    del request
    return JSONResponse(
        {"error": "Branch deletion is managed by the gateway"},
        status_code=501,
    )


@router.post("/current")
@requires("edit")
async def get_current_branch(*, request: Request) -> Response:
    del request
    return JSONResponse({"active_branch": workspace.current_branch()})


@router.post("/switch")
@requires("edit")
async def switch_branch(*, request: Request) -> Response:
    """Switch the working branch: S3 has every branch, so switching is just
    reconstructing the session's GatewayFileSystem with the new name."""
    error = _require_s3()
    if error is not None:
        return error

    body = await request.json()
    branch = str(body.get("branch") or "").strip()
    if not branch:
        return JSONResponse({"error": "Branch name required"}, status_code=400)

    if branch == workspace.current_branch():
        return JSONResponse({"branch": branch, "switched": False})

    try:
        workspace.set_current_branch(branch)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"branch": branch, "switched": True})
