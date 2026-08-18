"""Sandbox runtime configuration for automated improvement runs.

Environment variables owned by this module:

- SP_SANDBOX_RUNTIME_PROVIDER: which ephemeral-VM provider executes improvement
  workloads. Currently only "vercel". Empty disables the runtime entirely.
- SP_SANDBOX_RUNTIME_TIME_LIMIT: per-sandbox execution time limit in seconds
  (default 900). Sandboxes are destroyed at the end of every run regardless.
- VERCEL_TOKEN / VERCEL_TEAM_ID / VERCEL_PROJECT_ID: Vercel access-token
  authentication for the Sandbox API. All three are required for the vercel
  provider; the token is never logged or echoed.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from gateway.config._base import _GatewaySettingsBase


class SandboxRuntimeSettings(_GatewaySettingsBase):
    provider: str = Field(default="vercel", alias="SP_SANDBOX_RUNTIME_PROVIDER")
    time_limit_seconds: int = Field(default=900, alias="SP_SANDBOX_RUNTIME_TIME_LIMIT")
    vercel_token: str | None = Field(default=None, alias="VERCEL_TOKEN")
    vercel_team_id: str | None = Field(default=None, alias="VERCEL_TEAM_ID")
    vercel_project_id: str | None = Field(default=None, alias="VERCEL_PROJECT_ID")

    @property
    def enabled(self) -> bool:
        if self.provider == "vercel":
            return bool(self.vercel_token and self.vercel_team_id and self.vercel_project_id)
        return False


@lru_cache(maxsize=1)
def get_sandbox_runtime_settings() -> SandboxRuntimeSettings:
    return SandboxRuntimeSettings()


def reset_sandbox_runtime_settings() -> None:
    """Test hook: drop the cached settings so env monkeypatches take effect."""
    get_sandbox_runtime_settings.cache_clear()
