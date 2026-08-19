from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

from starlette.authentication import requires
from starlette.responses import JSONResponse

from signalpilot import _loggers
from signalpilot._cli.sandbox import SandboxMode
from signalpilot._server.api.deps import AppState
from signalpilot._server.api.endpoints.notebook_file import (
    resolve_notebook_file,
)
from signalpilot._server.files.lsp_workspace import (
    LspWorkspace,
    resolve_lsp_workspace,
)
from signalpilot._server.router import APIRouter
from signalpilot._server.templates.templates import build_mount_config_dict
from signalpilot._server.workspace import NEW_FILE
from signalpilot._session.model import SessionMode
from signalpilot._utils.async_path import AsyncPath

if TYPE_CHECKING:
    from starlette.requests import Request

LOGGER = _loggers.sp_logger()

router = APIRouter()

FILE_QUERY_PARAM_KEY = "file"


class MountConfigResponse(TypedDict):
    filename: str
    cwd: str | None
    lspWorkspace: LspWorkspace | None
    mode: Literal["edit", "read", "home", "gallery"]
    version: str
    serverToken: str
    config: Any
    configOverrides: Any
    appConfig: Any
    view: dict[str, Any]
    notebook: Any
    session: Any
    runtimeConfig: list[dict[str, Any]] | None
    gatewayUrl: str
    gatewayApiKey: str
    rawFallback: bool


@router.get("/mount-config")
@requires("read")
async def get_mount_config(*, request: Request) -> JSONResponse:
    data = await build_mount_config(request)
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


async def build_mount_config(request: Request) -> MountConfigResponse:
    """Build the mount config dict from the current request state."""
    app_state = AppState(request)

    file_key_from_query = app_state.query_params(FILE_QUERY_PARAM_KEY)
    project_id_from_query = app_state.query_params("project")
    del project_id_from_query
    file_key = (
        file_key_from_query
        or app_state.session_manager.workspace.get_unique_file_key()
    )

    if not file_key:
        return _build_home_config(app_state)

    return await _build_notebook_config(app_state, file_key)


def _build_home_config(app_state: AppState) -> MountConfigResponse:
    LOGGER.debug("No file key provided, serving home config")
    app_mode: Literal["home", "gallery"] = (
        "home" if app_state.mode == SessionMode.EDIT else "gallery"
    )
    return cast(
        MountConfigResponse,
        build_mount_config_dict(
            filename=None,
            mode=app_mode,
            server_token=app_state.skew_protection_token,
            user_config=app_state.config_manager.get_user_config(),
            config_overrides=app_state.config_manager.get_config_overrides(),
            app_config=None,
            runtime_config=[{"url": app_state.remote_url}]
            if app_state.remote_url
            else None,
        ),
    )


def _resolve_absolute_filepath(file_key: str) -> str:
    """Resolve a file_key to an absolute path if the file exists on disk."""
    p = Path(file_key)
    return str(p.resolve()) if p.exists() else file_key


async def _build_notebook_config(
    app_state: AppState,
    file_key: str,
) -> MountConfigResponse:
    directory = app_state.session_manager.workspace.directory
    if file_key.startswith(NEW_FILE):
        resolved_file_key = file_key
        is_raw_file = file_key == NEW_FILE + "raw"
    else:
        resolved_file = resolve_notebook_file(file_key, directory)
        resolved_file_key = str(resolved_file.path)
        is_raw_file = resolved_file.raw_fallback
    config_manager = app_state.config_manager_at_file(resolved_file_key)

    if is_raw_file:
        LOGGER.debug("Raw file: %s, using empty notebook session", resolved_file_key)
        app_manager = app_state.session_manager.app_manager(NEW_FILE + "raw")
        app_config = app_manager.app.config
        absolute_filepath = _resolve_absolute_filepath(resolved_file_key)
    else:
        LOGGER.debug("File key provided: %s", resolved_file_key)
        try:
            app_manager = app_state.session_manager.app_manager(resolved_file_key)
            if len(list(app_manager.app.cell_manager.cell_ids())) == 0:
                raise ValueError("Notebook has no cells")
        except Exception as e:
            LOGGER.warning(
                "Failed to load notebook %s, falling back to raw editor: %s",
                resolved_file_key,
                e,
            )
            is_raw_file = True
            app_manager = app_state.session_manager.app_manager(NEW_FILE + "raw")
            app_config = app_manager.app.config
            absolute_filepath = _resolve_absolute_filepath(resolved_file_key)
        else:
            app_config = app_manager.app.config
            absolute_filepath = app_manager.filename

    notebook_snapshot = await _precompute_notebook_snapshot(
        app_state, app_manager, is_raw_file
    )

    filename = absolute_filepath if is_raw_file else app_manager.filename
    directory = app_state.session_manager.workspace.directory
    lsp_workspace = resolve_lsp_workspace(filename, directory)

    if filename and directory:
        try:
            filename = str(Path(filename).relative_to(directory))
        except ValueError:
            pass

    app_mode: Literal["edit", "read"] = (
        "read" if app_state.mode == SessionMode.RUN else "edit"
    )

    return cast(
        MountConfigResponse,
        build_mount_config_dict(
            filename=filename,
            cwd=os.path.dirname(absolute_filepath) if absolute_filepath else None,
            lsp_workspace=lsp_workspace,
            mode=app_mode,
            server_token=app_state.skew_protection_token,
            user_config=config_manager.get_user_config(),
            config_overrides=config_manager.get_config_overrides(),
            app_config=app_config,
            notebook_snapshot=notebook_snapshot,
            runtime_config=[{"url": app_state.remote_url}]
            if app_state.remote_url
            else None,
            raw_fallback=is_raw_file,
        ),
    )


async def _precompute_notebook_snapshot(
    app_state: AppState,
    app_manager: Any,
    is_raw_file: bool,
) -> Any:
    if (
        is_raw_file
        or app_state.session_manager.sandbox_mode is not SandboxMode.MULTI
        or app_state.mode != SessionMode.EDIT
        or not app_manager.filename
    ):
        return None

    from signalpilot._convert.converters import SpConvert

    filepath = AsyncPath(app_manager.filename)
    if not await filepath.exists():
        return None

    try:
        content = await filepath.read_text(encoding="utf-8")
        return SpConvert.from_py(content).to_notebook_v1()
    except Exception:
        LOGGER.debug("Failed to pre-compute notebook snapshot")
        return None
