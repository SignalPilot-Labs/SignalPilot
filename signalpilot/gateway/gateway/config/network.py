"""Network / rate-limiting settings for the gateway.

Cached because no test monkeypatches these vars after import.
If you add an env var here, audit tests/ for monkeypatch.setenv("YOUR_VAR")
before adding — if any test touches it, keep it as os.getenv (Class B).

Class A vars managed here: SP_PER_KEY_RPM, SP_PER_ORG_RPM
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from ._base import _GatewaySettingsBase


class NetworkSettings(_GatewaySettingsBase):
    """Typed network/rate-limit configuration read from process environment at instantiation."""

    sp_per_key_rpm: int = Field(1000, alias="SP_PER_KEY_RPM")
    sp_per_org_rpm: int = Field(5000, alias="SP_PER_ORG_RPM")


@lru_cache(maxsize=1)
def get_network_settings() -> NetworkSettings:
    """Return cached NetworkSettings instance.

    Safe to cache: SP_PER_KEY_RPM and SP_PER_ORG_RPM are not monkeypatched by any test
    in tests/ (confirmed by grep before migration).
    """
    return NetworkSettings()
