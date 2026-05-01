"""Application configuration via pydantic-settings.

Required environment variables (no defaults — missing raises ValidationError at startup):
- SP_DEPLOYMENT_MODE: "local" | "cloud"
- WORKSPACES_DATABASE_URL: async SQLAlchemy database URL

Optional environment variables:
- CLAUDE_CODE_OAUTH_TOKEN: required for local inference mode
- ANTHROPIC_API_KEY: required for cloud BYO inference mode
- WORKSPACES_METERED_INFERENCE_ENABLED: reserved for R3+
- SP_GATEWAY_URL: gateway base URL for run-token minting (R3+)
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    sp_deployment_mode: Literal["local", "cloud"] = Field(
        validation_alias="SP_DEPLOYMENT_MODE"
    )
    database_url: str = Field(validation_alias="WORKSPACES_DATABASE_URL")
    claude_code_oauth_token: SecretStr | None = Field(
        default=None, validation_alias="CLAUDE_CODE_OAUTH_TOKEN"
    )
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias="ANTHROPIC_API_KEY"
    )
    workspaces_metered_inference_enabled: bool = Field(
        default=False, validation_alias="WORKSPACES_METERED_INFERENCE_ENABLED"
    )
    gateway_url: str | None = Field(default=None, validation_alias="SP_GATEWAY_URL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
