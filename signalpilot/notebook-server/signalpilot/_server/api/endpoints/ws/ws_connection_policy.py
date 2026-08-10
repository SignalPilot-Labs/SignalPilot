from __future__ import annotations

from typing import Protocol

from signalpilot._server.workspace import SpFileKey
from signalpilot._types.ids import SessionId


class SessionLookup(Protocol):
    def get_session(self, session_id: SessionId) -> object | None: ...

    def get_session_by_file_key(
        self,
        file_key: SpFileKey,
    ) -> object | None: ...


def is_exact_session_reattach(
    manager: SessionLookup,
    session_id: SessionId,
    file_key: SpFileKey,
) -> bool:
    existing_by_id = manager.get_session(session_id)
    existing_by_file = manager.get_session_by_file_key(file_key)
    return existing_by_id is not None and existing_by_id is existing_by_file
