"""Authentication settings for the gateway.

Cached because no test monkeypatches these vars after import.
If you add an env var here, audit tests/ for monkeypatch.setenv("YOUR_VAR")
before adding — if any test touches it, keep it as os.getenv (Class B).

Class A vars managed here: CLERK_JWT_AUDIENCE, SP_JWT_LEEWAY
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from ._base import _GatewaySettingsBase


class AuthSettings(_GatewaySettingsBase):
    """Typed auth configuration read from process environment at instantiation."""

    clerk_jwt_audience: str = Field("", alias="CLERK_JWT_AUDIENCE")
    sp_jwt_leeway: int = Field(30, alias="SP_JWT_LEEWAY")


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    """Return cached AuthSettings instance.

    Safe to cache: CLERK_JWT_AUDIENCE and SP_JWT_LEEWAY are not monkeypatched
    by any test in tests/ (confirmed by grep before migration).
    """
    return AuthSettings()
