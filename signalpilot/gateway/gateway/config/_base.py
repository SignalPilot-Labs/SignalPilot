"""Base settings class for gateway configuration.

All domain settings classes inherit from _GatewaySettingsBase.

Design constraints:
- No env_file: reads from process environment only, matching current behavior.
- extra="ignore": pydantic-settings raises on unknown fields by default; we suppress that.
- case_sensitive=True: env var names are uppercase by convention; we do not lowercase them.
- This module depends only on pydantic, pydantic_settings, and stdlib. Nothing from gateway/
  outside config/ may be imported here. All other gateway modules import FROM config/, never
  the reverse.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class _GatewaySettingsBase(BaseSettings):
    """Shared configuration for all gateway settings classes.

    Subclasses declare fields with Field(alias="ENV_VAR_NAME") to map
    environment variable names to typed Python attributes.
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        case_sensitive=True,
    )
