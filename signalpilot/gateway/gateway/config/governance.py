"""Governance settings for the gateway.

Cached because no test monkeypatches these vars after import.
If you add an env var here, audit tests/ for monkeypatch.setenv("YOUR_VAR")
before adding — if any test touches it, keep it as os.getenv (Class B).

Class A vars managed here: SP_ANNOTATIONS_TTL, SP_MAX_EXPORT_ROWS, SP_ADMIN_USER_IDS

Note: SP_ANNOTATIONS_TTL is a float (seconds). Default is 60.0.
Note: SP_ADMIN_USER_IDS default is "local" — the single-user local-deployment sentinel.
      admin_user_ids property returns frozenset[str] matching existing api/security.py behavior.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from ._base import _GatewaySettingsBase


class GovernanceSettings(_GatewaySettingsBase):
    """Typed governance configuration read from process environment at instantiation."""

    sp_annotations_ttl: float = Field(60.0, alias="SP_ANNOTATIONS_TTL")
    sp_max_export_rows: int = Field(50000, alias="SP_MAX_EXPORT_ROWS")
    # Raw CSV string; use the admin_user_ids property for the parsed frozenset.
    sp_admin_user_ids: str = Field("local", alias="SP_ADMIN_USER_IDS")

    @property
    def admin_user_ids(self) -> frozenset[str]:
        """Parse SP_ADMIN_USER_IDS CSV into a frozenset of stripped, non-empty IDs.

        Matches behavior of the original comprehension:
            frozenset(uid.strip() for uid in value.split(",") if uid.strip())
        """
        return frozenset(uid.strip() for uid in self.sp_admin_user_ids.split(",") if uid.strip())


@lru_cache(maxsize=1)
def get_governance_settings() -> GovernanceSettings:
    """Return cached GovernanceSettings instance.

    Safe to cache: SP_ANNOTATIONS_TTL, SP_MAX_EXPORT_ROWS, and SP_ADMIN_USER_IDS are not
    monkeypatched by any test in tests/ (confirmed by grep before migration).
    """
    return GovernanceSettings()
