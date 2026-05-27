from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.authentication import requires
from starlette.responses import JSONResponse

from signalpilot import _loggers
from signalpilot._runtime.commands import RefreshSecretsCommand
from signalpilot._secrets.secrets import write_secret
from signalpilot._server.api.deps import AppState
from signalpilot._server.api.utils import dispatch_control_request, parse_request
from signalpilot._server.models.models import (
    BaseResponse,
    ListSecretKeysRequest,
    SuccessResponse,
)
from signalpilot._server.models.secrets import CreateSecretRequest
from signalpilot._server.router import APIRouter
from signalpilot._types.ids import ConsumerId

if TYPE_CHECKING:
    from starlette.requests import Request

LOGGER = _loggers.sp_logger()

# Router for secrets endpoints
router = APIRouter()


@router.post("/keys")
@requires("edit")
async def list_keys(request: Request) -> SuccessResponse:
    """
    parameters:
        - in: header
          name: Sp-Session-Id
          schema:
            type: string
          required: true
    requestBody:
        required: true
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/ListSecretKeysRequest"
    responses:
        200:
            description: List all secret keys
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/ListSecretKeysResponse"
    """
    return await dispatch_control_request(request, ListSecretKeysRequest)


@router.post("/create")
@requires("edit")
async def create_secret(request: Request) -> BaseResponse:
    """
    parameters:
        - in: header
          name: Sp-Session-Id
          schema:
            type: string
          required: true
    requestBody:
        required: true
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/CreateSecretRequest"
    responses:
        200:
            description: Create a secret
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/BaseResponse"
    """
    body = await parse_request(request, cls=CreateSecretRequest)
    app_state = AppState(request)
    session_id = app_state.require_current_session_id()

    # Write to the provider
    write_secret(body, app_state.config_manager.get_config(hide_secrets=False))

    # Refresh the secrets
    app_state.require_current_session().put_control_request(
        RefreshSecretsCommand(),
        from_consumer_id=ConsumerId(session_id),
    )
    return SuccessResponse(success=True)


@router.post("/delete")
@requires("edit")
async def delete_secret(request: Request) -> JSONResponse:
    """
    responses:
        200:
            description: Delete a secret
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/BaseResponse"
    """
    del request
    return JSONResponse(
        content={"success": False, "message": "Not implemented"},
        status_code=501,
    )
