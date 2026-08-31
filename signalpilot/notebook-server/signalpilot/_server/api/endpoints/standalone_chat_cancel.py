"""Cancellation route for active standalone chat agents and kernels."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.authentication import requires
from starlette.responses import JSONResponse

from signalpilot._server.ai.claude_agent import steer_agent, stop_agent
from signalpilot._server.api.endpoints.standalone_chat_runtime import (
    _ANALYSIS_SESSIONS_BY_RUN,
    _close_analysis_kernel,
)
from signalpilot._server.auth.standalone_chat import validate_run_id
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.requests import Request

router = APIRouter()


@router.post("/steer/{run_id}")
@requires("edit")
async def steer(*, request: Request) -> JSONResponse:
    run_id = validate_run_id(request.path_params["run_id"])
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    message = payload.get("message") if isinstance(payload, dict) else None
    steering_id = payload.get("steering_id") if isinstance(payload, dict) else None
    if not isinstance(message, str) or not message.strip():
        return JSONResponse({"error": "Message cannot be empty"}, status_code=422)
    if len(message) > 50_000:
        return JSONResponse({"error": "Message is too long"}, status_code=422)
    if not isinstance(steering_id, str) or not steering_id.strip():
        return JSONResponse({"error": "steering_id is required"}, status_code=422)
    accepted = await steer_agent(
        f"standalone-{run_id}", message.strip(), steering_id.strip()
    )
    if not accepted:
        return JSONResponse(
            {"error": "The agent is not ready to accept messages"},
            status_code=409,
        )
    return JSONResponse({"accepted": True})


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
