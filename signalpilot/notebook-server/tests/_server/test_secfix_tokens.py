"""SP-01: derived tokens are keyed only by SP_NOTEBOOK_TOKEN_SECRET."""

from __future__ import annotations

import pytest

from signalpilot._server import tokens


def test_jwt_secret_is_not_a_derivation_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SP_NOTEBOOK_TOKEN_SECRET", raising=False)
    monkeypatch.setenv("SP_SESSION_JWT_SECRET", "gateway-secret-that-must-be-ignored")
    assert "SP_SESSION_JWT_SECRET" not in tokens._TOKEN_SECRET_VARS
    assert tokens._derivation_key() is None
    # Unkeyed -> random rather than a reproducible digest of the source.
    assert str(tokens.AuthToken.from_code("x")) != str(tokens.AuthToken.from_code("x"))


def test_notebook_token_secret_keys_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SP_NOTEBOOK_TOKEN_SECRET", "per-launch-secret")
    monkeypatch.delenv("SP_SESSION_JWT_SECRET", raising=False)
    assert tokens._derivation_key() == b"per-launch-secret"
    assert str(tokens.AuthToken.from_code("x")) == str(tokens.AuthToken.from_code("x"))
