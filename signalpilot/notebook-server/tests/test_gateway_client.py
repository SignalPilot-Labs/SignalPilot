from __future__ import annotations

import os

import pytest

from signalpilot._server.auth.session_token import _reset_for_test, load_session_jwt
from signalpilot._server.gateway_client import gateway_headers


@pytest.fixture(autouse=True)
def _reset_token_state():
    _reset_for_test()
    yield
    _reset_for_test()
    os.environ.pop("SP_SESSION_JWT", None)
    os.environ.pop("SP_API_KEY", None)


def test_gateway_headers_use_cached_session_jwt_as_bearer() -> None:
    os.environ["SP_SESSION_JWT"] = "session.jwt.token"
    assert load_session_jwt() == "session.jwt.token"
    assert "SP_SESSION_JWT" not in os.environ

    assert gateway_headers() == {"Authorization": "Bearer session.jwt.token"}


def test_gateway_headers_use_reexported_jwt_api_key_as_bearer() -> None:
    os.environ["SP_API_KEY"] = "session.jwt.token"

    assert gateway_headers() == {"Authorization": "Bearer session.jwt.token"}


def test_gateway_headers_use_sp_api_key_header_for_sp_keys() -> None:
    os.environ["SP_API_KEY"] = "sp_live_key"

    assert gateway_headers() == {"X-API-Key": "sp_live_key"}
