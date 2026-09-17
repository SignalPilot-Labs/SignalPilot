"""Governance settings for the gateway.

Cached because no test monkeypatches these vars after import.
If you add an env var here, audit tests/ for monkeypatch.setenv("YOUR_VAR")
before adding — if any test touches it, keep it as os.getenv (Class B).

Class A vars managed here: SP_ANNOTATIONS_TTL, SP_MAX_EXPORT_ROWS

Note: SP_ANNOTATIONS_TTL is a float (seconds). Default is 60.0.

The gateway has no platform-staff identity. Customer-facing features are gated
by the org's plan (``gateway.billing.entitlements``) and by the org role; the
former ``SP_ADMIN_USER_IDS`` list no longer exists.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from ._base import _GatewaySettingsBase


class GovernanceSettings(_GatewaySettingsBase):
    """Typed governance configuration read from process environment at instantiation."""

    sp_annotations_ttl: float = Field(60.0, alias="SP_ANNOTATIONS_TTL")
    sp_max_export_rows: int = Field(50000, alias="SP_MAX_EXPORT_ROWS")


@lru_cache(maxsize=1)
def get_governance_settings() -> GovernanceSettings:
    """Return cached GovernanceSettings instance.

    Safe to cache: SP_ANNOTATIONS_TTL and SP_MAX_EXPORT_ROWS are not
    monkeypatched by any test in tests/ (confirmed by grep before migration).
    """
    return GovernanceSettings()
