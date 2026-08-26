"""GitHub App settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator

from ._base import _GatewaySettingsBase


class GitHubAppSettings(_GatewaySettingsBase):
    sp_github_app_id: str = Field("", alias="SP_GITHUB_APP_ID")
    sp_github_app_client_id: str = Field("", alias="SP_GITHUB_APP_CLIENT_ID")
    sp_github_app_client_secret: str = Field("", alias="SP_GITHUB_APP_CLIENT_SECRET")
    sp_github_app_private_key: str = Field("", alias="SP_GITHUB_APP_PRIVATE_KEY")
    sp_github_app_slug: str = Field("signalpilot", alias="SP_GITHUB_APP_SLUG")
    sp_web_url: str = Field("http://localhost:3200", alias="SP_WEB_URL")

    @field_validator("sp_github_app_private_key", mode="after")
    @classmethod
    def _fix_pem_newlines(cls, v: str) -> str:
        if v and "\\n" in v:
            return v.replace("\\n", "\n")
        return v

    @property
    def is_configured(self) -> bool:
        if not (self.sp_github_app_id and self.sp_github_app_client_id and self.sp_github_app_private_key):
            return False
        # Cloud mode completes GitHub's user-authorization leg to bind an
        # installation to the caller, which needs the client secret. Local mode
        # has no tenant boundary to cross and never exchanges the code, so the
        # secret stays optional there.
        from ..runtime.mode import is_cloud_mode

        if is_cloud_mode() and not self.sp_github_app_client_secret:
            return False
        return True


@lru_cache(maxsize=1)
def get_github_settings() -> GitHubAppSettings:
    return GitHubAppSettings()
