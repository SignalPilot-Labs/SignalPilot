from __future__ import annotations

import hashlib
import hmac
import os
import secrets

# Derivation key for the code-derived tokens below. These must stay stable
# across instances serving the same notebook, so they cannot simply be random —
# but deriving them from the source alone makes them reproducible by anyone who
# can read that source. Keying the derivation fixes that without losing
# stability, provided every instance shares the secret.
_TOKEN_SECRET_VARS = ("SP_NOTEBOOK_TOKEN_SECRET", "SP_SESSION_JWT_SECRET")


def _derivation_key() -> bytes | None:
    for var in _TOKEN_SECRET_VARS:
        value = os.environ.get(var, "").strip()
        if value:
            return value.encode("utf-8")
    return None


def _derive(label: str, code: str) -> str:
    """Derive a stable token from *code*, keyed when a server secret exists.

    Falls back to a random token rather than an unkeyed digest: an unkeyed value
    is guessable by anyone holding the notebook source, and guessing it is
    enough to reach the edit-gated routers. Losing cross-instance stability is
    the safer failure, and is avoided by setting one of the secret variables or
    by supplying an explicit token.
    """
    key = _derivation_key()
    if key is None:
        return secrets.token_urlsafe(32)
    return hmac.new(key, f"{label}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


# Adapted from starlette, to avoid a dependency when running without starlette.
class AuthToken:
    """
    Holds a string value that should not be revealed in tracebacks etc.
    You should cast the value to `str` at the point it is required.
    """

    def __init__(self, value: str):
        self._value = value

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"{class_name}('**********')"

    def __str__(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    @staticmethod
    def random() -> AuthToken:
        return AuthToken(secrets.token_urlsafe(16))

    @staticmethod
    def from_code(code: str) -> AuthToken:
        return AuthToken(_derive("auth", code))

    @staticmethod
    def is_empty(token: AuthToken) -> bool:
        return str(token) == ""


class SkewProtectionToken:
    """
    Provides a token that is sent to the client on the first request and
    is used to protect against version skew bugs.

    This can happen when new code is deployed to the server but the client
    still has only application loaded.
    """

    def __init__(self, token: str) -> None:
        self.token = token

    @staticmethod
    def from_code(code: str) -> SkewProtectionToken:
        return SkewProtectionToken(_derive("skew", code))

    @staticmethod
    def random() -> SkewProtectionToken:
        return SkewProtectionToken(secrets.token_urlsafe(16))

    def __str__(self) -> str:
        return self.token
