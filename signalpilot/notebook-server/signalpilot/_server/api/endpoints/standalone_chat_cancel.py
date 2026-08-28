"""Cancellation route for active standalone chat agents and kernels."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.authentication import requires
from starlette.responses import JSONResponse

from signalpilot._server.ai.claude_agent import stop_agent
from signalpilot._server.api.endpoints.standalone_chat_runtime import (
    _ANALYSIS_SESSIONS_BY_RUN,
    _close_analysis_kernel,
)
from signalpilot._server.auth.standalone_chat import validate_run_id
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.requests import Request

router = APIRouter()


@router.post("/cancel/{run_id}")
@requires("edit")
async def cancel(*, request: Request) -> JSONResponse:
    run_id = validate_run_id(request.path_params["run_id"])
    # The conversation-specific notebook bearer authorizes cancellation.
    stopped = stop_agent(f"standalone-{run_id}")
    kernel_stopped = False
    if analysis_session_id := _ANALYSIS_SESSIONS_BY_RUN.pop(run_id, None):
        try:
            kernel_stopped = _close_analysis_kernel(request.app, analysis_session_id)
        except Exception:
            kernel_stopped = False
    return JSONResponse({"stopped": stopped, "kernel_stopped": kernel_stopped})
