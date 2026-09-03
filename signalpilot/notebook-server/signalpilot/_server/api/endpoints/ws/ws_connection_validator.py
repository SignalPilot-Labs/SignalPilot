from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

from signalpilot import _loggers
from signalpilot._server.api.auth import validate_auth
from signalpilot._server.api.deps import AppState
from signalpilot._server.api.endpoints.notebook_file import (
    resolve_notebook_file,
)
from signalpilot._server.api.endpoints.ws.analysis_trails import (
    is_generated_analysis_trail_notebook,
)
from signalpilot._server.codes import WebSocketCodes
from signalpilot._server.workspace import NEW_FILE, SpFileKey
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

        # Reconnect-by-id comes first: an EXISTING session already owns its
        # file, so the connection needs no file param at all (the chat live
        # notebook panel attaches with only the kernel session id) and must
        # not run workspace path validation — standalone-chat analysis
        # notebooks live in a run-scoped scratch directory outside the
        # workspace.
        existing_session = self.app_state.session_manager.get_session(
            session_id
        )

        # Extract file_key
        file_key: SpFileKey | None = (
            self.app_state.query_params(FILE_QUERY_PARAM_KEY)
            or self.app_state.session_manager.workspace.get_unique_file_key()
        )
        requested_file_key = file_key

        if existing_session is not None:
            session_path = existing_session.app_file_manager.path
            if session_path:
                file_key = SpFileKey(str(session_path))

        if file_key is None:
            await self.websocket.close(
                WebSocketCodes.NORMAL_CLOSE, "SP_NO_FILE_KEY"
            )
            return None

        # Resolve and semantically classify the requested file before any
        # notebook session can be created.
        project_id = self.app_state.query_params("project")
        branch = self.app_state.query_params("branch") or "main"
        directory = self.app_state.session_manager.workspace.directory

        # S3 mode: this runtime is bound to exactly one project's workspace
        # store (SP_PROJECT_ID). A session for any other project would silently
        # read from and WRITE TO the wrong project's store — fail closed.
        import os

        from signalpilot._server.files.workspace import is_s3_workspace

        pinned = os.environ.get("SP_PROJECT_ID", "").strip()
        if is_s3_workspace() and project_id and pinned and project_id != pinned:
            print(
                f"[WS START] project mismatch: request={project_id} pinned={pinned}",
                flush=True,
            )
            await self.websocket.close(
                WebSocketCodes.FORBIDDEN, "SP_PROJECT_MISMATCH"
            )
            return None

        if existing_session is None and not file_key.startswith(NEW_FILE):
            try:
                resolved_file = resolve_notebook_file(file_key, directory)
            except Exception:
                await self.websocket.close(
                    WebSocketCodes.FORBIDDEN,
                    "SP_INVALID_FILE",
                )
                return None
            if resolved_file.raw_fallback:
                await self.websocket.close(
                    WebSocketCodes.NORMAL_CLOSE,
                    "SP_RAW_FILE",
                )
                return None
            file_key = SpFileKey(str(resolved_file.path))

        # Extract kiosk mode
        kiosk = self.app_state.query_params(KIOSK_QUERY_PARAM_KEY) == "true"

        # Extract config-based parameters
        config = self.app_state.config_manager_at_file(file_key).get_config()
        rtc_enabled = config.get("experimental", {}).get("rtc_v2", False)
        auto_instantiate = config["runtime"]["auto_instantiate"]
        if requested_file_key is not None and is_generated_analysis_trail_notebook(
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
