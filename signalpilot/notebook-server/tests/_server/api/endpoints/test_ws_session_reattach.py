from unittest.mock import Mock

from signalpilot._server.api.endpoints.ws.ws_connection_policy import (
    is_exact_session_reattach,
)
from signalpilot._types.ids import SessionId


def _manager(
    *,
    session_by_id: object | None,
    session_by_file: object | None,
) -> Mock:
    manager = Mock()
    manager.get_session.return_value = session_by_id
    manager.get_session_by_file_key.return_value = session_by_file
    return manager


def test_exact_session_can_reattach_while_old_socket_is_closing() -> None:
    session = object()
    manager = _manager(session_by_id=session, session_by_file=session)

    assert is_exact_session_reattach(
        manager,
        SessionId("s_existing"),
        "/workspace/notebooks/intro.py",
    ) is True


def test_different_session_cannot_replace_connected_file() -> None:
    manager = _manager(
        session_by_id=object(),
        session_by_file=object(),
    )

    assert is_exact_session_reattach(
        manager,
        SessionId("s_existing"),
        "/workspace/notebooks/intro.py",
    ) is False
