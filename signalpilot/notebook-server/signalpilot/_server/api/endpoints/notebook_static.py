from __future__ import annotations

import asyncio
import json
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starlette.authentication import requires
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from signalpilot._server.api.deps import AppState
from signalpilot._server.files.path_validator import PathValidator
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.requests import Request

router = APIRouter()

# Top-level keys that must be present in a valid session cache document.
_SESSION_REQUIRED_KEYS: frozenset[str] = frozenset({"version", "metadata", "cells"})


def _get_directory(request: Request, app_state: AppState) -> str | None:
    """Get the working directory, preferring cloud project sync dir.

    Copied from files.py to avoid a shared util in this round.
    """
    project_id = request.headers.get("x-gateway-project-id")
    if project_id:
        branch = request.headers.get("x-gateway-branch-id", "main")
        from signalpilot._server.files.project_sync import local_project_dir

        local_dir = local_project_dir(project_id, branch)
        if local_dir.exists():
            return str(local_dir)
    return app_state.session_manager.workspace.directory


@router.get("/static")
@requires("read")
async def get_notebook_static(*, request: Request) -> JSONResponse:
    """Return notebook code, session snapshot, and structural metadata.

    Does not spawn a kernel. Safe to call before any session is created.

    Query params:
        file: Relative (or absolute) path to the .py notebook file.

    Headers (optional):
        X-Gateway-Project-Id: Cloud project id — resolves the working dir.
        X-Gateway-Branch-Id: Branch name (default: main).

    Returns 200 JSON: {code, session, notebook, filename}
    Returns 400 on missing/invalid file param, path traversal, or no workspace.
    Returns 403 on code-visibility gate denial or path outside workspace.
    Returns 404 on file not found.
    """
    app_state = AppState(request)

    # Mirror files.py:read_code — enforce the edit-vs-run code-visibility gate.
    if not app_state.session_manager.should_send_code_to_frontend():
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Code is not available",
        )

    raw_file = request.query_params.get("file")
    if not raw_file:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "missing file param")

    directory = _get_directory(request, app_state)

    resolved = _resolve_and_validate(raw_file, directory)

    if not resolved.is_file():
        raise HTTPException(HTTPStatus.NOT_FOUND, "file not found")

    payload = await asyncio.to_thread(_build_static_payload, resolved, directory)
    return JSONResponse(payload)


def _resolve_and_validate(raw_file: str, directory: str | None) -> Path:
    """Resolve raw_file against directory and validate no path traversal.

    Raises HTTPException(400) when directory is None (no workspace configured).
    Raises HTTPException(403) on path traversal (re-raised from PathValidator).
    Returns the resolved absolute Path.
    """
    if directory is None:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "no workspace configured")

    candidate = Path(raw_file)
    if not candidate.is_absolute():
        candidate = Path(directory) / raw_file
    PathValidator().validate_inside_directory(Path(directory), candidate)
    return candidate


def _validate_session_shape(data: Any) -> bool:
    """Return True iff data is a dict containing the required top-level session keys."""
    if not isinstance(data, dict):
        return False
    return _SESSION_REQUIRED_KEYS.issubset(data.keys())


def _build_static_payload(resolved: Path, directory: str | None) -> dict[str, Any]:
    """Build the static notebook payload synchronously.

    Intended to run inside asyncio.to_thread since all operations are
    blocking IO or CPU-bound (file reads, parse, serialization).
    """
    from signalpilot._server.export._session_cache import (
        is_session_snapshot_stale,
    )
    from signalpilot._session.notebook import load_notebook
    from signalpilot._session.state.serialize import (
        get_session_cache_file,
        serialize_notebook,
    )
    from signalpilot._session.state.session_view import SessionView
    from signalpilot._utils.sp_path import SpPath

    code = resolved.read_text(encoding="utf-8")

    # Build notebook structural snapshot from an empty SessionView.
    # serialize_notebook reads view.last_executed_code per cell; an empty
    # view causes every cell's per-cell code to fall back to "". The
    # verbatim source-of-truth code is returned separately in payload["code"].
    file_manager = load_notebook(str(resolved))
    empty_view = SessionView()
    notebook_typed = serialize_notebook(empty_view, file_manager.app.cell_manager)
    notebook: dict[str, Any] = dict(notebook_typed)

    # Session snapshot: only return when cache exists, is not stale, and has
    # the expected shape.  Validate the top-level structure before returning
    # to prevent a malicious/corrupted cache from injecting arbitrary JSON.
    session: dict[str, Any] | None = None
    cache_path = get_session_cache_file(resolved)
    if cache_path.exists() and not is_session_snapshot_stale(
        cache_path, SpPath(str(resolved))
    ):
        try:
            parsed = json.loads(cache_path.read_text(encoding="utf-8"))
            if _validate_session_shape(parsed):
                session = parsed
        except (OSError, json.JSONDecodeError):
            session = None

    # Return the relative filename (basename) rather than the absolute server
    # path to avoid leaking pod filesystem layout to the client.
    if directory is not None:
        try:
            filename = str(resolved.relative_to(directory))
        except ValueError:
            filename = resolved.name
    else:
        filename = resolved.name

    return {
        "code": code,
        "session": session,
        "notebook": notebook,
        "filename": filename,
    }
