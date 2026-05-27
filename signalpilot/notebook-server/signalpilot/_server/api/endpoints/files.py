from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from starlette.authentication import requires
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse

from signalpilot import _loggers
from signalpilot._runtime.commands import RenameNotebookCommand
from signalpilot._server.api.deps import AppState
from signalpilot._server.api.utils import parse_request
from signalpilot._server.files.path_validator import PathValidator
from signalpilot._server.models.models import (
    BaseResponse,
    CopyNotebookRequest,
    ReadCodeResponse,
    RenameNotebookRequest,
    SaveAppConfigurationRequest,
    SaveNotebookRequest,
    SuccessResponse,
)
from signalpilot._server.router import APIRouter
from signalpilot._types.ids import ConsumerId
from signalpilot._utils.async_path import abspath
from signalpilot._utils.http import HTTPStatus

if TYPE_CHECKING:
    from starlette.requests import Request

LOGGER = _loggers.sp_logger()

# Router for file endpoints
router = APIRouter()


def _get_directory(request: Request, app_state: AppState) -> str | None:
    """Get the working directory, preferring cloud project sync dir."""
    project_id = request.headers.get("x-gateway-project-id")
    if project_id:
        branch = request.headers.get("x-gateway-branch-id", "main")
        from signalpilot._server.files.project_sync import local_project_dir

        local_dir = local_project_dir(project_id, branch)
        if local_dir.exists():
            return str(local_dir)
    return app_state.session_manager.workspace.directory


@router.post("/read_code")
@requires("read")
async def read_code(
    *,
    request: Request,
) -> ReadCodeResponse:
    """
    parameters:
        - in: header
          name: Sp-Session-Id
          schema:
            type: string
          required: true
    responses:
        200:
            description: Read the code from the server
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/ReadCodeResponse"
        400:
            description: File must be saved before downloading
        403:
            description: Code is not available in run mode
    """
    app_state = AppState(request)

    # Check if code should be visible (edit mode or include_code=True)
    if not app_state.session_manager.should_send_code_to_frontend():
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Code is not available",
        )

    session = app_state.require_current_session()

    if not session.app_file_manager.path:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="File must be saved before downloading",
        )

    contents = session.app_file_manager.read_file()

    return ReadCodeResponse(contents=contents)


@router.post("/load_notebook")
@requires("edit")
async def load_notebook(
    *,
    request: Request,
) -> dict:
    """Load a notebook file and return its cells for in-page switching."""
    import msgspec

    class LoadNotebookRequest(msgspec.Struct, rename="camel"):
        path: str

    body = await parse_request(request, cls=LoadNotebookRequest)
    filepath = body.path

    if not Path(filepath).exists():
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f"File not found: {filepath}",
        )

    from signalpilot._ast.load import load_app

    app = load_app(filepath)
    if app is None:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Could not parse notebook: {filepath}",
        )

    cells = []
    cell_manager = app.cell_manager
    for cell_id in cell_manager.cell_ids():
        code = cell_manager.cell_code(cell_id)
        name = cell_manager.cell_name(cell_id)
        config = cell_manager.cell_config(cell_id)
        cells.append({
            "cellId": str(cell_id),
            "code": code,
            "name": name,
            "config": {
                "disabled": config.disabled,
                "hideCode": config.hide_code,
                "column": config.column,
            },
        })

    return {
        "success": True,
        "cells": cells,
        "filename": filepath,
    }


@router.post("/rename")
@requires("edit")
async def rename_file(
    *,
    request: Request,
) -> BaseResponse:
    """
    parameters:
        - in: header
          name: Sp-Session-Id
          schema:
            type: string
          required: true
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/RenameNotebookRequest"
    responses:
        200:
            description: Rename the current app
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/SuccessResponse"
    """
    body = await parse_request(request, cls=RenameNotebookRequest)
    app_state = AppState(request)
    directory = _get_directory(request, app_state)

    # Resolve relative filenames against the workspace's directory
    if not Path(body.filename).is_absolute() and directory:
        body.filename = str(Path(directory) / body.filename)

    filename = await abspath(body.filename)

    # Prevent path traversal: ensure target is inside the router's directory
    if directory:
        PathValidator().validate_inside_directory(
            Path(directory), Path(filename)
        )

    app_state.require_current_session().put_control_request(
        RenameNotebookCommand(filename=filename),
        from_consumer_id=ConsumerId(app_state.require_current_session_id()),
    )

    await app_state.session_manager.rename_session(
        app_state.require_current_session_id(), body.filename
    )

    return SuccessResponse()


@router.post("/save")
@requires("edit")
async def save(
    *,
    request: Request,
) -> PlainTextResponse:
    """
    parameters:
        - in: header
          name: Sp-Session-Id
          schema:
            type: string
          required: true
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/SaveNotebookRequest"
    responses:
        200:
            description: Save the current app
            content:
                text/plain:
                    schema:
                        type: string
    """
    app_state = AppState(request)
    body = await parse_request(request, cls=SaveNotebookRequest)
    directory = _get_directory(request, app_state)

    # Resolve relative filenames against the workspace's directory
    if body.filename and not Path(body.filename).is_absolute():
        if directory:
            body.filename = str(Path(directory) / body.filename)

    # Prevent path traversal: ensure target is inside the router's directory
    if directory and body.filename:
        PathValidator().validate_inside_directory(
            Path(directory), Path(body.filename)
        )

    session = app_state.require_current_session()

    # DEFENSE: Verify the save target matches the session's actual file.
    # Prevents autosave race conditions from writing one notebook's cells to another file.
    session_path = session.app_file_manager.path
    if session_path and body.filename:
        from signalpilot._utils.paths import normalize_path
        session_normalized = str(normalize_path(Path(session_path)))
        request_normalized = str(normalize_path(Path(body.filename)))
        if session_normalized != request_normalized:
            LOGGER.warning(
                "Save rejected: filename mismatch. "
                "Session file: %s, request file: %s",
                session_normalized,
                request_normalized,
            )
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=f"Cannot save: file mismatch. Session is for '{Path(session_path).name}' but save targets '{Path(body.filename).name}'",
            )

    contents = session.app_file_manager.save(body)

    return PlainTextResponse(content=contents)


@router.post("/copy")
@requires("edit")
async def copy(
    *,
    request: Request,
) -> PlainTextResponse:
    """
    parameters:
        - in: header
          name: Sp-Session-Id
          schema:
            type: string
          required: true
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/CopyNotebookRequest"
    responses:
        200:
            description: Copy notebook
            content:
                text/plain:
                    schema:
                        type: string
    """
    app_state = AppState(request)
    body = await parse_request(request, cls=CopyNotebookRequest)

    # Resolve relative filenames against the workspace's directory
    directory = _get_directory(request, app_state)
    if directory:
        if body.source and not Path(body.source).is_absolute():
            body.source = str(Path(directory) / body.source)
        if body.destination and not Path(body.destination).is_absolute():
            body.destination = str(Path(directory) / body.destination)

    # Prevent path traversal: ensure source and destination are inside the router's directory
    if directory:
        validator = PathValidator()
        if body.source:
            validator.validate_inside_directory(
                Path(directory), Path(body.source)
            )
        if body.destination:
            validator.validate_inside_directory(
                Path(directory), Path(body.destination)
            )

    session = app_state.require_current_session()
    contents = session.app_file_manager.copy(body)

    return PlainTextResponse(content=contents)


@router.post("/save_app_config")
@requires("edit")
async def save_app_config(
    *,
    request: Request,
) -> PlainTextResponse:
    """
    parameters:
        - in: header
          name: Sp-Session-Id
          schema:
            type: string
          required: true
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/SaveAppConfigurationRequest"
    responses:
        200:
            description: Save the app configuration
            content:
                text/plain:
                    schema:
                        type: string
    """
    app_state = AppState(request)
    body = await parse_request(request, cls=SaveAppConfigurationRequest)
    session = app_state.require_current_session()
    contents = session.app_file_manager.save_app_config(body.config)

    return PlainTextResponse(content=contents)
