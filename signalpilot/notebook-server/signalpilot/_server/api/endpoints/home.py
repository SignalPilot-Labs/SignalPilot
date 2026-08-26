from __future__ import annotations

import asyncio
import os
import pathlib
import tempfile
from typing import TYPE_CHECKING

from starlette.authentication import requires
from starlette.responses import JSONResponse

from signalpilot import _loggers
from signalpilot._server.api.deps import AppState
from signalpilot._server.api.utils import parse_request
from signalpilot._server.files.directory_scanner import DirectoryScanner
from signalpilot._server.models.home import (
    SpFile,
    OpenTutorialRequest,
    RecentFilesResponse,
    RunningNotebooksResponse,
    ShutdownSessionRequest,
    WorkspaceFilesRequest,
    WorkspaceFilesResponse,
)
from signalpilot._server.router import APIRouter
from signalpilot._server.workspace import (
    count_files,
    flatten_files,
)
from signalpilot._session.model import ConnectionState, SessionMode
try:
    from signalpilot._tutorials import create_temp_tutorial_file
except ImportError:
    create_temp_tutorial_file = None  # type: ignore[assignment]
from signalpilot._utils.http import HTTPException, HTTPStatus
from signalpilot._utils.paths import pretty_path

if TYPE_CHECKING:
    from starlette.requests import Request

MAX_FILES = DirectoryScanner.MAX_FILES

LOGGER = _loggers.sp_logger()

# Router for home endpoints
router = APIRouter()


@router.post("/recent_files")
@requires("edit")
async def read_code(
    *,
    request: Request,
) -> RecentFilesResponse:
    """
    responses:
        200:
            description: Get the recent files
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/RecentFilesResponse"
    """
    app_state = AppState(request)
    # Pass the workspace's directory to filter and relativize paths
    directory = None
    dir_str = app_state.session_manager.workspace.directory
    if dir_str:
        directory = pathlib.Path(dir_str)
    files = app_state.session_manager.recents.get_recents(directory)
    return RecentFilesResponse(files=files)


@router.post("/workspace_files")
@requires("read")
async def workspace_files(
    *,
    request: Request,
) -> WorkspaceFilesResponse:
    """
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/WorkspaceFilesRequest"
    responses:
        200:
            description: Get the files in the workspace
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/WorkspaceFilesResponse"
    """
    body = await parse_request(request, cls=WorkspaceFilesRequest)
    app_state = AppState(request)
    session_manager = app_state.session_manager

    if session_manager.mode == SessionMode.RUN:
        from signalpilot._metadata.opengraph import (
            OpenGraphContext,
            resolve_opengraph_metadata,
        )
        from signalpilot._server.models.files import FileInfo

        if session_manager.watch:
            # In watched folder mode, refresh the index to include new/removed files since the previous request.
            session_manager.workspace.invalidate()

        base_url = app_state.base_url
        mode = session_manager.mode.value

        def get_files_with_metadata() -> list[FileInfo]:
            files = session_manager.workspace.files
            signalpilot_files = [
                file for file in flatten_files(files) if file.is_sp_file
            ]
            result: list[FileInfo] = []
            for file in signalpilot_files:
                try:
                    resolved_path = session_manager.workspace.resolve(
                        file.path
                    )
                except HTTPException as e:
                    if e.status_code == HTTPStatus.NOT_FOUND:
                        continue
                    raise
                opengraph = None
                if resolved_path is not None:
                    # User-defined OpenGraph generators receive this context for dynamic metadata
                    opengraph = resolve_opengraph_metadata(
                        resolved_path,
                        context=OpenGraphContext(
                            filepath=resolved_path,
                            file_key=file.path,
                            base_url=base_url,
                            mode=mode,
                        ),
                    )
                result.append(
                    FileInfo(
                        id=file.id,
                        path=file.path,
                        name=file.name,
                        is_directory=file.is_directory,
                        is_sp_file=file.is_sp_file,
                        last_modified=file.last_modified,
                        children=file.children,
                        opengraph=opengraph,
                    )
                )
            return result

        signalpilot_files = await asyncio.to_thread(get_files_with_metadata)
        file_count = len(signalpilot_files)
        has_more = file_count >= MAX_FILES
        return WorkspaceFilesResponse(
            files=signalpilot_files,
            root=session_manager.workspace.directory or "",
            has_more=has_more,
            file_count=file_count,
        )

    # Both calls are no-ops on workspaces that don't support these
    # capabilities (single-file, fixed-files, empty).
    session_manager.workspace.invalidate()
    session_manager.workspace.set_include_markdown(body.include_markdown)
    root = session_manager.workspace.directory or ""

    # Run file scanning in thread pool to avoid blocking the server
    files = await asyncio.to_thread(lambda: session_manager.workspace.files)

    file_count = count_files(files)
    has_more = file_count >= MAX_FILES

    return WorkspaceFilesResponse(
        files=files,
        root=root,
        has_more=has_more,
        file_count=file_count,
    )


def _get_active_sessions(app_state: AppState) -> list[SpFile]:
    """Get list of active sessions with prettified paths."""
    # Get directory from workspace for path relativization
    base_dir = app_state.session_manager.workspace.directory

    files: list[SpFile] = []
    for session_id, session in app_state.session_manager.sessions.items():
        state = session.connection_state()
        if state == ConnectionState.OPEN or state == ConnectionState.ORPHANED:
            filename = session.app_file_manager.filename
            basename = os.path.basename(filename) if filename else None
            files.append(
                SpFile(
                    name=(basename or "new notebook"),
                    path=pretty_path(filename, base_dir)
                    if filename
                    else session_id,
                    last_modified=0,
                    session_id=session_id,
                    initialization_id=session.initialization_id,
                )
            )
    # These are better in reverse
    return files[::-1]


@router.post("/running_notebooks")
@requires("edit")
async def running_notebooks(
    *,
    request: Request,
) -> RunningNotebooksResponse:
    """
    responses:
        200:
            description: Get the running files
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/RunningNotebooksResponse"
    """
    app_state = AppState(request)
    return RunningNotebooksResponse(files=_get_active_sessions(app_state))


@router.post("/shutdown_session")
@requires("edit")
async def shutdown_session(
    *,
    request: Request,
) -> RunningNotebooksResponse:
    """
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/ShutdownSessionRequest"
    responses:
        200:
            description: Shutdown the current session
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/RunningNotebooksResponse"
    """
    app_state = AppState(request)
    body = await parse_request(request, cls=ShutdownSessionRequest)
    app_state.session_manager.close_session(body.session_id)
    return RunningNotebooksResponse(files=_get_active_sessions(app_state))


@router.post("/tutorial/open")
@requires("edit")
async def tutorial(
    *,
    request: Request,
) -> SpFile | JSONResponse:
    """
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/OpenTutorialRequest"
    responses:
        200:
            description: Open a new tutorial
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/SpFile"
    """
    import msgspec

    # Create a new tutorial file and return the filepath
    try:
        body = await parse_request(request, cls=OpenTutorialRequest)
    except msgspec.ValidationError:
        return JSONResponse({"detail": "Tutorial not found"}, status_code=400)
    temp_dir = tempfile.TemporaryDirectory()
    path = create_temp_tutorial_file(body.tutorial_id, temp_dir)

    import atexit

    atexit.register(temp_dir.cleanup)

    # Register the temp file/directory with the workspace so it can be accessed.
    # Each method is a no-op on workspaces that don't support that capability.
    app_state = AppState(request)
    app_state.session_manager.workspace.register_temp_dir(temp_dir.name)
    app_state.session_manager.workspace.register_allowed_path(
        path.absolute_name
    )

    return SpFile(
        name=os.path.basename(path.absolute_name),
        path=path.absolute_name,
    )
