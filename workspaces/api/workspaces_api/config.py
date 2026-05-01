"""Application configuration via pydantic-settings.

Required environment variables (no defaults — missing raises ValidationError at startup):
- SP_DEPLOYMENT_MODE: "local" | "cloud"
- WORKSPACES_DATABASE_URL: async SQLAlchemy database URL

Optional environment variables:
- CLAUDE_CODE_OAUTH_TOKEN: required for local inference mode
- ANTHROPIC_API_KEY: required for cloud BYO inference mode
- WORKSPACES_METERED_INFERENCE_ENABLED: reserved for R3+
- SP_GATEWAY_URL: gateway base URL for run-token minting
- SP_API_KEY: Bearer token for gateway API calls (required in cloud mode)
- SP_RUN_WORKDIR_ROOT: root directory for per-run working directories
- SP_DBT_PROXY_TOKEN_TTL_SECONDS: TTL for minted dbt-proxy tokens
- SP_DBT_PROXY_HOST: hostname for the dbt-proxy (loopback default)
- SP_SANDBOX_PYTHON: Python executable to run sandbox server.py
- SP_SANDBOX_SERVER_PATH: path to the sandbox server.py entrypoint
- SP_USE_SUBPROCESS_SPAWNER: use real subprocess spawner (true) or stub (false)
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent


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

    # R4: subprocess spawner and token fields
    sp_api_key: SecretStr | None = Field(
        default=None, validation_alias="SP_API_KEY"
    )
    sp_run_workdir_root: Path = Field(
        default=Path("/tmp/workspaces-runs"),
        validation_alias="SP_RUN_WORKDIR_ROOT",
    )
    sp_dbt_proxy_token_ttl_seconds: int = Field(
        default=3600, validation_alias="SP_DBT_PROXY_TOKEN_TTL_SECONDS"
    )
    sp_dbt_proxy_host: str = Field(
        default="127.0.0.1", validation_alias="SP_DBT_PROXY_HOST"
    )
    sp_sandbox_python: str = Field(
        default="python3", validation_alias="SP_SANDBOX_PYTHON"
    )
    sp_sandbox_server_path: Path = Field(
        default=_REPO_ROOT / "workspaces" / "agent" / "sandbox" / "server.py",
        validation_alias="SP_SANDBOX_SERVER_PATH",
    )
    sp_use_subprocess_spawner: bool = Field(
        default=True, validation_alias="SP_USE_SUBPROCESS_SPAWNER"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
