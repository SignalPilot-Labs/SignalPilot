"""Storage settings for the gateway.

Cached because no test monkeypatches these vars after import.
If you add an env var here, audit tests/ for monkeypatch.setenv("YOUR_VAR")
before adding: if any test touches it, keep it as os.getenv (Class B).


"""

from __future__ import annotations

from functools import lru_cache

from ._base import _GatewaySettingsBase


class StorageSettings(_GatewaySettingsBase):
    """Typed storage configuration read from process environment at instantiation."""

    # Declared as str intentionally: see module docstring for semantics.
    # Public name required by Pydantic (no leading underscore on fields).



@lru_cache(maxsize=1)
def get_storage_settings() -> StorageSettings:
    """Return cached StorageSettings instance.

    (confirmed by grep before migration).
    """
    return StorageSettings()
