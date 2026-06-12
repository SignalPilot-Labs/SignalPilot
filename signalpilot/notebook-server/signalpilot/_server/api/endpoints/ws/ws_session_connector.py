from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from signalpilot._server.api.endpoints.ws.ws_connection_validator import (
    ConnectionParams,
)

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

    from signalpilot._server.api.endpoints.ws_endpoint import WebSocketHandler
    from signalpilot._server.session_manager import SessionManager
    from signalpilot._session import Session

from starlette.websockets import WebSocketDisconnect

from signalpilot import _loggers
from signalpilot._messaging.types import NoopStream
from signalpilot._runtime.params import QueryParams
from signalpilot._server.codes import WebSocketCodes
from signalpilot._server.models.models import InstantiateNotebookRequest
from signalpilot._session.model import ConnectionState, SessionMode

LOGGER = _loggers.sp_logger()


class ConnectionType(Enum):
    """Type of session connection established."""

    KIOSK = "kiosk"
    RECONNECT = "reconnect"
    RTC_EXISTING = "rtc_existing"
    RESUME = "resume"
    NEW = "new"


class SessionConnector:
    """Handles different session connection strategies."""

    def __init__(
        self,
        manager: SessionManager,
        handler: WebSocketHandler,
        params: ConnectionParams,
        websocket: WebSocket,
    ):
        self.manager = manager
        self.handler = handler
        self.params = params
        self.websocket = websocket

    def connect(self) -> tuple[Session, ConnectionType]:
        """Determine connection type and establish session connection."""
        print(f"[CONNECTOR] connect() called: file_key={self.params.file_key} session_id={self.params.session_id}", flush=True)
        # 1. Kiosk mode
        if self.params.kiosk:
            return self._connect_kiosk()

        # 2. If raw file, convert to __new__ key so we get an empty session
        raw_extensions = {".sql", ".yml", ".yaml", ".toml", ".txt", ".csv", ".json"}
        from pathlib import Path as _Path
        file_ext = _Path(self.params.file_key).suffix.lower() if self.params.file_key else ""
        if file_ext in raw_extensions:
            from signalpilot._server.workspace import NEW_FILE
            self.params = ConnectionParams(
                session_id=self.params.session_id,
                file_key=f"{NEW_FILE}raw",
                kiosk=self.params.kiosk,
                auto_instantiate=self.params.auto_instantiate,
                rtc_enabled=self.params.rtc_enabled,
            )

        # 3. Reconnect to existing session with same ID
        existing_by_id = self.manager.get_session(self.params.session_id)
        if existing_by_id is not None:
            return self._reconnect_session(existing_by_id)

        # 4. Connect to existing session (RTC mode)
        existing_by_file = self.manager.get_session_by_file_key(
            self.params.file_key
        )
        if (
            existing_by_file is not None
            and self.params.rtc_enabled
            and self.manager.mode == SessionMode.EDIT
        ):
            return self._connect_rtc_session(existing_by_file)

        # 4. Resume previous session
        resumable = self.manager.maybe_resume_session(
            self.params.session_id, self.params.file_key
        )
        if resumable is not None:
            return self._resume_session(resumable)

        # 5. Create new session
        print("[CONNECTOR] no existing session found, creating new", flush=True)
        return self._create_new_session()

    def _connect_kiosk(self) -> tuple[Session, ConnectionType]:
        """Connect to kiosk session.

        Raises:
            WebSocketDisconnect: If kiosk mode is not supported or session
                not found.
        """
        if self.manager.mode is not SessionMode.EDIT:
            LOGGER.debug("Kiosk mode is only supported in edit mode")
            raise WebSocketDisconnect(
                WebSocketCodes.FORBIDDEN, "SP_KIOSK_NOT_ALLOWED"
            )

        # Try to find session by ID first
        kiosk_session = self.manager.get_session(self.params.session_id)
        if kiosk_session is None:
            LOGGER.debug(
                "Kiosk session not found for session id %s",
                self.params.session_id,
            )
            # Try to find by file key
            kiosk_session = self.manager.get_session_by_file_key(
                self.params.file_key
            )

        if kiosk_session is None:
            LOGGER.debug(
                "Kiosk session not found for file key %s",
                self.params.file_key,
            )
            raise WebSocketDisconnect(
                WebSocketCodes.NORMAL_CLOSE, "SP_NO_SESSION"
            )

        LOGGER.debug("Connecting to kiosk session")
        self.handler._connect_kiosk(kiosk_session)
        return kiosk_session, ConnectionType.KIOSK

    def _reconnect_session(
        self, session: Session
    ) -> tuple[Session, ConnectionType]:
        """Reconnect to existing session.

        The session already exists, but it was disconnected. This can happen
        in local development when the client goes to sleep and wakes later.
        Always replay cells so the frontend gets the notebook state.
        """
        LOGGER.debug("Reconnecting session %s", self.params.session_id)
        # In case there is a lingering connection, close it
        session.disconnect_main_consumer()
        self.handler._reconnect_session(session, replay=True)
        return session, ConnectionType.RECONNECT

    def _connect_rtc_session(
        self, session: Session
    ) -> tuple[Session, ConnectionType]:
        """Connect to RTC-enabled session."""
        LOGGER.debug(
            "Connecting to existing session for file %s", self.params.file_key
        )
        self.handler._connect_to_existing_session(session)
        return session, ConnectionType.RTC_EXISTING

    def _resume_session(
        self, session: Session
    ) -> tuple[Session, ConnectionType]:
        """Resume a previous session."""
        LOGGER.debug("Resuming session %s", self.params.session_id)
        self.handler._reconnect_session(session, replay=True)
        return session, ConnectionType.RESUME

    @property
    def _is_run_mode(self) -> bool:
        """Check if we're in run mode (read-only app mode)."""
        return self.manager.mode == SessionMode.RUN

    def _create_new_session(self) -> tuple[Session, ConnectionType]:
        """Create a new session."""
        print(f"[CONNECTOR] _create_new_session: file_key={self.params.file_key}", flush=True)

        query_params = self._extract_query_params()
        print(f"[CONNECTOR] calling manager.create_session...", flush=True)

        new_session = self.manager.create_session(
            query_params=query_params.to_dict(),
            session_id=self.params.session_id,
            session_consumer=self.handler,
            file_key=self.params.file_key,
            auto_instantiate=self.params.auto_instantiate,
        )

        self._notify_kernel_ready(new_session)

        # Auto-instantiate server-side in run mode (frontend won't call it)
        # or in edit mode when auto_instantiate is configured, to eliminate
        # the round-trip wait for the frontend to request instantiation.
        if self._is_run_mode or self.params.auto_instantiate:
            self._auto_instantiate(new_session)

        return new_session, ConnectionType.NEW

    def _extract_query_params(self) -> QueryParams:
        """Extract query params from the websocket, filtering ignored keys."""
        query_params = QueryParams({}, NoopStream())
        for key, value in self.websocket.query_params.multi_items():
            if key not in QueryParams.IGNORED_KEYS:
                query_params.append(key, value)
        return query_params

    def _notify_kernel_ready(self, session: Session) -> None:
        """Send kernel-ready notification to the frontend."""
        self.handler.status = ConnectionState.CONNECTING
        self.handler._write_kernel_ready(
            session,
            resumed=False,
            ui_values={},
            last_executed_code={},
            last_execution_time={},
            kiosk=False,
            auto_instantiated=(
                self._is_run_mode or self.params.auto_instantiate
            ),
        )
        self.handler.status = ConnectionState.OPEN
        self.handler._replay_previous_session(session)

    def _auto_instantiate(self, session: Session) -> None:
        """Auto-instantiate the session (used in run mode)."""
        from signalpilot._runtime.commands import HTTPRequest

        session.instantiate(
            InstantiateNotebookRequest(
                object_ids=[],
                values=[],
                auto_run=True,
            ),
            http_request=HTTPRequest.from_request(self.websocket),
        )
