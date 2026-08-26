"""Agent notebooks: headless execution with durable results.

POST /api/agent-notebooks/run — write a notebook, execute it headlessly
(``sp export session``), and commit both the notebook and its session
snapshot (outputs) to the workspace store. The browser can then replay the
outputs without any kernel — the file plane is independent of compute.

Agent-generated notebooks live under the reserved ``signalpilot-agent/``
prefix so the Notebooks page can list them without scanning the project.
Works identically on the direct container and a Vercel sandbox: it is plain
HTTP against the runtime.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import msgspec
from starlette.authentication import requires
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from signalpilot import _loggers
from signalpilot._server.api.deps import AppState
from signalpilot._server.api.utils import parse_request
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.requests import Request

LOGGER = _loggers.sp_logger()

router = APIRouter()

AGENT_PREFIX = "signalpilot-agent"
_RUN_TIMEOUT_SECONDS = 300


class AgentNotebookRunRequest(msgspec.Struct, rename="camel"):
    filename: str
    code: str


def _agent_rel_path(filename: str) -> PurePosixPath:
    """Validate and confine the notebook under the agent prefix."""
    p = PurePosixPath(filename)
    if not filename.endswith(".py"):
        raise HTTPException(HTTPStatus.BAD_REQUEST, "filename must end with .py")
    if p.is_absolute() or any(part in {"", ".", ".."} for part in p.parts):
        raise HTTPException(HTTPStatus.BAD_REQUEST, "filename must be a plain relative path")
    if p.parts[0] != AGENT_PREFIX:
        p = PurePosixPath(AGENT_PREFIX) / p
    return p


@router.post("/run")
@requires("edit")
async def run_agent_notebook(*, request: Request) -> JSONResponse:
    """Execute a notebook headlessly and persist code + outputs.

    Returns 200 with {success, returncode, log, session, path} — execution
    failures are a 200 with success=false so callers get the log.
    """
    app_state = AppState(request)
    body = await parse_request(request, cls=AgentNotebookRunRequest)
    if not body.code.strip():
        raise HTTPException(HTTPStatus.BAD_REQUEST, "code is empty")

    directory = app_state.session_manager.workspace.directory
    if not directory:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "no workspace configured")

    rel = _agent_rel_path(body.filename)
    local = Path(directory) / rel.as_posix()
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(body.code, encoding="utf-8")

    # Headless execution: `sp export session` spawns a kernel, runs every
    # cell, and writes __sp__/session/<name>.json next to the notebook.
    #
    # Plain subprocess.run in a worker thread, output to a FILE:
    # - asyncio subprocess reaping depends on the loop's child watcher and
    #   silently never completes in this server's loop configuration;
    # - the kernel's forkserver daemon inherits stdout and outlives the
    #   export, so reading a pipe to EOF would block forever anyway.
    import subprocess
    import tempfile

    def _run() -> tuple[int, str]:
        with tempfile.TemporaryFile() as log_fh:
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "signalpilot", "export", "session",
                     str(local), "--force-overwrite"],
                    cwd=directory,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    env={**os.environ, "SP_AGENT_MODE": "true"},
                    timeout=_RUN_TIMEOUT_SECONDS,
                )
                code = proc.returncode
            except subprocess.TimeoutExpired:
                return -1, f"execution timed out after {_RUN_TIMEOUT_SECONDS}s"
            log_fh.seek(0)
            return code, log_fh.read().decode("utf-8", errors="replace")[-8000:]

    returncode, log = await asyncio.to_thread(_run)
    if returncode == -1 and "timed out" in log:
        return JSONResponse(
            {"success": False, "returncode": -1, "log": log,
             "session": None, "path": rel.as_posix()},
        )

    session_data: dict[str, Any] | None = None
    sidecar = local.parent / "__sp__" / "session" / f"{local.name}.json"
    if sidecar.is_file():
        try:
            session_data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            session_data = None

    # Durability: the notebook AND its outputs become workspace revisions,
    # so the sandbox can die and the Notebooks page still replays results.
    def _commit() -> None:
        from signalpilot._server.files.workspace import (
            is_s3_workspace,
            write_through_paths,
        )

        if not is_s3_workspace():
            return
        paths = [str(local)]
        if sidecar.is_file():
            paths.append(str(sidecar))
        write_through_paths(
            paths, root=directory,
            message=f"Agent notebook run: {rel.as_posix()}",
        )

    try:
        await asyncio.to_thread(_commit)
    except Exception:
        LOGGER.warning("Agent notebook write-through failed", exc_info=True)

    return JSONResponse({
        "success": returncode == 0,
        "returncode": returncode,
        "log": log if returncode != 0 else log[-2000:],
        "session": session_data,
        "path": rel.as_posix(),
    })
