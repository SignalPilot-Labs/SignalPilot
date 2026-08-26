from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.authentication import requires

from signalpilot._runtime.commands import ClearCacheCommand, GetCacheInfoCommand
from signalpilot._server.api.utils import dispatch_control_request
from signalpilot._server.models.models import SuccessResponse
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.requests import Request

# Router for cache endpoints
router = APIRouter()


@router.post("/clear")
@requires("edit")
async def clear_cache(request: Request) -> SuccessResponse:
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
                    $ref: "#/components/schemas/ClearCacheRequest"
    responses:
        200:
            description: Clear all caches
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/SuccessResponse"
    """
    return await dispatch_control_request(request, ClearCacheCommand())


@router.post("/info")
@requires("edit")
async def get_cache_info(request: Request) -> SuccessResponse:
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
                    $ref: "#/components/schemas/GetCacheInfoRequest"
    responses:
        200:
            description: Get cache statistics
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/SuccessResponse"
    """
    return await dispatch_control_request(request, GetCacheInfoCommand())
