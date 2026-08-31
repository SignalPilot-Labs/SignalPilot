from __future__ import annotations

from typing import TYPE_CHECKING, Any

import msgspec
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from signalpilot import _loggers
from signalpilot._dependencies.errors import ManyModulesNotFoundError
from signalpilot._messaging.notification import MissingPackageAlertNotification
from signalpilot._runtime.packages.utils import is_python_isolated
from signalpilot._session import send_message_to_consumer
from signalpilot._session.model import SessionMode
from signalpilot._types.ids import ConsumerId
from signalpilot._utils.http import (
    HTTPException as SpHTTPException,
    is_client_error,
)

if TYPE_CHECKING:
    from starlette.requests import Request

LOGGER = _loggers.sp_logger()


def _is_api_request(request: Request) -> bool:
    """Check if the request is an API request (not a page navigation)."""
    # Sandbox notebooks have a base path such as /notebook/{session_id}.
    # Match the API path segment instead of assuming /api is at the origin root.
    path = str(request.scope.get("path", ""))
    if path == "/api" or "/api/" in path:
        return True

    # Check Accept header for application/json (case-insensitive)
    accept = request.headers.get("accept", "")
    return "application/json" in accept.lower()


# Convert exceptions to JSON responses
# In the case of a ModuleNotFoundError, we try to send a MissingPackageAlert to the client
# to install the missing package
async def handle_error(request: Request, response: Any) -> Any:
    if isinstance(response, HTTPException):
        # Page navigations use a Basic-auth challenge to collect credentials.
        # API callers must retain the real 403 and detail; rewriting application
        # authorization failures as generic 401s makes them indistinguishable
        # from a missing notebook bearer.
        if response.status_code == 403 and not _is_api_request(request):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authorization header required"},
                headers={"WWW-Authenticate": "Basic"},
            )
        return JSONResponse(
            {"detail": response.detail},
            status_code=response.status_code,
            headers=response.headers,
        )
    if isinstance(response, SpHTTPException):
        # Log server errors
        if not is_client_error(response.status_code):
            LOGGER.error(response)
        return JSONResponse(
            {"detail": response.detail},
            status_code=response.status_code,
        )
    if isinstance(response, (ModuleNotFoundError, ManyModulesNotFoundError)):
        LOGGER.warning(response.msg)  # print to terminal
        try:
            # Keep the error renderer importable without initializing the full
            # session/plugin graph. AppState is needed only for this recovery path.
            from signalpilot._server.api.deps import AppState

            app_state = AppState(request)
            session_id = app_state.get_current_session_id()
            session = app_state.get_current_session()
            # If we're in an edit session, send an package installation request
            if (
                session_id is not None
                and session is not None
                and app_state.mode == SessionMode.EDIT
            ):
                if isinstance(response, ManyModulesNotFoundError):
                    packages = response.package_names
                    source = response.source
                elif isinstance(response, ModuleNotFoundError):
                    if not response.name:
                        return JSONResponse(
                            {"detail": str(response)}, status_code=500
                        )
                    packages = [response.name]
                    source = "server"
                # TODO(dmadisetti): Consider checking if the server is in a virtual environment
                # and if so, set isolated to False.
                isolated = True if source == "server" else is_python_isolated()
                send_message_to_consumer(
                    session=session,
                    operation=MissingPackageAlertNotification(
                        packages=packages,
                        isolated=isolated,
                        source=source,
                    ),
                    consumer_id=ConsumerId(session_id),
                )
            return JSONResponse({"detail": str(response)}, status_code=500)
        except Exception as e:
            LOGGER.warning(f"Failed to send missing package alert: {e}")
    if isinstance(response, msgspec.ValidationError):
        return JSONResponse({"detail": str(response)}, status_code=400)
    if isinstance(response, NotImplementedError):
        return JSONResponse({"detail": "Not supported"}, status_code=501)
    if isinstance(response, TypeError):
        return JSONResponse({"detail": str(response)}, status_code=500)
    if isinstance(response, Exception):
        return JSONResponse({"detail": str(response)}, status_code=500)
    return response
