from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

from signalpilot import _loggers
from signalpilot._server.api.auth import validate_auth
from signalpilot._server.api.deps import AppState
from signalpilot._server.api.endpoints.ws.analysis_trails import (
    is_generated_analysis_trail_notebook,
)
from signalpilot._server.codes import WebSocketCodes
from signalpilot._server.workspace import SpFileKey
from signalpilot._types.ids import SessionId

LOGGER = _loggers.sp_logger()

SESSION_QUERY_PARAM_KEY = "session_id"
FILE_QUERY_PARAM_KEY = "file"
KIOSK_QUERY_PARAM_KEY = "kiosk"


@dataclass
class ConnectionParams:
    """Parameters extracted from WebSocket connection request."""

    session_id: SessionId
    file_key: SpFileKey
    kiosk: bool
    auto_instantiate: bool
    rtc_enabled: bool


class WebSocketConnectionValidator:
    """Validates and extracts connection parameters from WebSocket requests."""

    def __init__(self, websocket: WebSocket, app_state: AppState):
        self.websocket = websocket
        self.app_state = app_state

    async def validate_auth(self) -> bool:
        """Validate authentication, close socket if invalid.

        Returns:
            True if authentication is valid or not required, False otherwise.
        """
        if self.app_state.enable_auth and not validate_auth(self.websocket):
            await self.websocket.close(
                WebSocketCodes.UNAUTHORIZED, "SP_UNAUTHORIZED"
            )
            return False
        return True

    async def extract_connection_params(
        self,
    ) -> ConnectionParams | None:
        """Extract and validate connection parameters.

        Returns:
            ConnectionParams if all parameters are valid, None otherwise.
        """
        # Extract session_id
        raw_session_id = self.app_state.query_params(SESSION_QUERY_PARAM_KEY)
        if raw_session_id is None:
            await self.websocket.close(
                WebSocketCodes.NORMAL_CLOSE, "SP_NO_SESSION_ID"
            )
            return None

        session_id = SessionId(raw_session_id)

        # Extract file_key
        file_key: SpFileKey | None = (
            self.app_state.query_params(FILE_QUERY_PARAM_KEY)
            or self.app_state.session_manager.workspace.get_unique_file_key()
        )
        requested_file_key = file_key

        if file_key is None:
            await self.websocket.close(
                WebSocketCodes.NORMAL_CLOSE, "SP_NO_FILE_KEY"
            )
            return None

        # For cloud projects, resolve relative file_key to absolute synced path
        project_id = self.app_state.query_params("project")
        branch = self.app_state.query_params("branch") or "main"
        if project_id and file_key and not Path(file_key).is_absolute():
            try:
                from signalpilot._server.files.project_sync import local_project_dir
                local_dir = local_project_dir(project_id, branch)
                if local_dir.exists():
                    candidate = local_dir / file_key
                    if candidate.exists():
                        file_key = str(candidate)
                    else:
                        fname = Path(file_key).name
                        for match in local_dir.rglob(fname):
                            file_key = str(match)
                            break
            except Exception:
                pass

        # Extract kiosk mode
        kiosk = self.app_state.query_params(KIOSK_QUERY_PARAM_KEY) == "true"

        # Extract config-based parameters
        config = self.app_state.config_manager_at_file(file_key).get_config()
        rtc_enabled = config.get("experimental", {}).get("rtc_v2", False)
        auto_instantiate = config["runtime"]["auto_instantiate"]
        if is_generated_analysis_trail_notebook(
            project_id=project_id,
            branch=branch,
            file_key=requested_file_key,
        ):
            auto_instantiate = False

        return ConnectionParams(
            session_id=session_id,
            file_key=file_key,
            kiosk=kiosk,
            auto_instantiate=auto_instantiate,
            rtc_enabled=rtc_enabled,
        )

    async def extract_file_key_only(self) -> SpFileKey | None:
        """Extract only the file_key parameter (for RTC endpoint).

        Returns:
            SpFileKey if valid, None otherwise.
        """
        file_key: SpFileKey | None = (
            self.app_state.query_params(FILE_QUERY_PARAM_KEY)
            or self.app_state.session_manager.workspace.get_unique_file_key()
        )

        if file_key is None:
            LOGGER.warning("RTC: Closing websocket - no file key")
            await self.websocket.close(
                WebSocketCodes.NORMAL_CLOSE, "SP_NO_FILE_KEY"
            )
            return None

        return file_key
