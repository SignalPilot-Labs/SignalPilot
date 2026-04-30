"""Storage settings for the gateway.

Cached because no test monkeypatches these vars after import.
If you add an env var here, audit tests/ for monkeypatch.setenv("YOUR_VAR")
before adding — if any test touches it, keep it as os.getenv (Class B).

Class A vars managed here: SP_ALLOW_LEGACY_CRYPTO

IMPORTANT — SP_ALLOW_LEGACY_CRYPTO semantics:
    The original code used: os.environ.get("SP_ALLOW_LEGACY_CRYPTO", "false").lower() == "true"
    This means ONLY strings that lowercase to "true" are truthy. Specifically:
    - "true", "True", "TRUE" -> True
    - "1", "yes", "on", "false", "0" -> False (all rejected)
    Pydantic's default bool field parser is MORE permissive ("1", "yes", "on" -> True).
    To preserve bit-identical behavior, we declare the field as str and expose
    a @property that applies .lower() == "true". Do NOT change this to a bool field.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from ._base import _GatewaySettingsBase


class StorageSettings(_GatewaySettingsBase):
    """Typed storage configuration read from process environment at instantiation."""

    # Declared as str intentionally — see module docstring for semantics.
    # Public name required by Pydantic (no leading underscore on fields).
    sp_allow_legacy_crypto_raw: str = Field("false", alias="SP_ALLOW_LEGACY_CRYPTO")

    @property
    def allow_legacy_crypto(self) -> bool:
        """True only when SP_ALLOW_LEGACY_CRYPTO lowercases to "true".

        Matches: os.environ.get("SP_ALLOW_LEGACY_CRYPTO", "false").lower() == "true"
        Rejects "1", "yes", "on" — only explicit "true" (any case) is accepted.
        """
        return self.sp_allow_legacy_crypto_raw.lower() == "true"


@lru_cache(maxsize=1)
def get_storage_settings() -> StorageSettings:
    """Return cached StorageSettings instance.

    Safe to cache: SP_ALLOW_LEGACY_CRYPTO is not monkeypatched by any test in tests/
    (confirmed by grep before migration).
    """
    return StorageSettings()
