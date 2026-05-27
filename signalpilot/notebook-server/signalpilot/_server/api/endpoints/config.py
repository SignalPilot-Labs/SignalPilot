# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from typing import TYPE_CHECKING, cast

from starlette.authentication import requires
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse

from signalpilot import _loggers
from signalpilot._config.config import PartialSignalPilotConfig
from signalpilot._messaging.msgspec_encoder import asdict
from signalpilot._runtime.commands import UpdateUserConfigCommand
from signalpilot._server.api.deps import AppState
from signalpilot._server.api.utils import parse_request
from signalpilot._server.lsp import any_lsp_server_running
from signalpilot._server.models.models import (
    SaveUserConfigurationRequest,
    SuccessResponse,
)
from signalpilot._server.router import APIRouter
from signalpilot._types.ids import ConsumerId

if TYPE_CHECKING:
    from starlette.requests import Request

LOGGER = _loggers.sp_logger()

# Router for config endpoints
router = APIRouter()


@router.post("/save_user_config")
@requires("edit")
async def save_user_config(
    *,
    request: Request,
) -> JSONResponse:
    """
    parameters:
        - in: header
          name: Sp-Session-Id
          schema:
            type: string
          required: false
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/SaveUserConfigurationRequest"
    responses:
        200:
            description: Update the user config on disk and in the kernel. Only allowed in edit mode.
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/SuccessResponse"
    """
    app_state = AppState(request)
    session_id = app_state.get_current_session_id()
    session = app_state.get_current_session()
    # Allow unknown keys to handle backward/forward compatibility
    body = await parse_request(
        request, cls=SaveUserConfigurationRequest, allow_unknown_keys=True
    )
    # TODO: we may want to validate deep-partial here, but validating with PartialSignalPilotConfig it too strict
    # so we just cast to PartialSignalPilotConfig
    config = app_state.config_manager.save_config(
        cast(PartialSignalPilotConfig, body.config)
    )

    async def handle_background_tasks() -> None:
        # Update the server's view of the config
        if any_lsp_server_running(config):
            LOGGER.debug("Starting language servers")
            await app_state.session_manager.start_lsp_server()


    background_task = BackgroundTask(handle_background_tasks)

    # Update the kernel's view of the config
    # Session could be None if the user is on the home page
    if session is not None:
        session.put_control_request(
            UpdateUserConfigCommand(config),
            from_consumer_id=ConsumerId(
                app_state.require_current_session_id()
            ),
        )

    return JSONResponse(
        content=asdict(SuccessResponse()),
        background=background_task,
    )
