from __future__ import annotations

import pytest

from signalpilot._server.concurrent_sessions import (
    allow_concurrent_edit_sessions,
    should_reject_edit_connection,
)


def test_concurrent_edit_sessions_are_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SP_ALLOW_CONCURRENT_EDIT_SESSIONS", raising=False)
    assert allow_concurrent_edit_sessions() is False
    assert should_reject_edit_connection(
        has_connected_client=True,
        kiosk=False,
        rtc_enabled=False,
    ) is True


def test_distinct_local_sessions_can_connect_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SP_ALLOW_CONCURRENT_EDIT_SESSIONS", "true")
    assert allow_concurrent_edit_sessions() is True
    assert should_reject_edit_connection(
        has_connected_client=True,
        kiosk=False,
        rtc_enabled=False,
    ) is False


@pytest.mark.parametrize(
    ("kiosk", "rtc_enabled"),
    [(True, False), (False, True)],
)
def test_existing_multi_consumer_modes_remain_allowed(
    monkeypatch: pytest.MonkeyPatch,
    kiosk: bool,
    rtc_enabled: bool,
) -> None:
    monkeypatch.delenv("SP_ALLOW_CONCURRENT_EDIT_SESSIONS", raising=False)
    assert should_reject_edit_connection(
        has_connected_client=True,
        kiosk=kiosk,
        rtc_enabled=rtc_enabled,
    ) is False
