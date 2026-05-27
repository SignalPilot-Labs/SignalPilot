# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.authentication import requires

from signalpilot._server.api.utils import dispatch_control_request
from signalpilot._server.models.models import BaseResponse, ValidateSQLRequest
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.requests import Request

# Router for SQL endpoints
router = APIRouter()


@router.post("/validate")
@requires("edit")
async def validate_sql(request: Request) -> BaseResponse:
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
                    $ref: "#/components/schemas/ValidateSQLRequest"
    responses:
        200:
            description: Validate an SQL query
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/SuccessResponse"
    """
    return await dispatch_control_request(request, ValidateSQLRequest)
