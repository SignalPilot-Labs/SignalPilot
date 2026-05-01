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

Chart-execute settings (R5):
- SP_CHART_EXECUTE_TOKEN_TTL_SECONDS: TTL for chart-execute proxy tokens (default 60)
- SP_CHART_STATEMENT_TIMEOUT_MS: statement timeout passed to proxy (default 30000)
- SP_CHART_CONNECT_TIMEOUT_SECONDS: libpq connect timeout (default 5)
- SP_CHART_TOTAL_DEADLINE_SECONDS: asyncio.timeout for full chart execute (default 45)
- SP_CHART_MAX_ROWS: row cap before truncation (default 10000)
- SP_CHART_MAX_CELL_BYTES: cell size cap in bytes before truncation (default 32768)
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

    # R6: Clerk JWT auth settings
    clerk_jwks_url: str | None = Field(
        default=None, validation_alias="SP_CLERK_JWKS_URL"
    )
    clerk_issuer: str | None = Field(
        default=None, validation_alias="SP_CLERK_ISSUER"
    )
    clerk_audience: str | None = Field(
        default=None, validation_alias="SP_CLERK_AUDIENCE"
    )
    clerk_jwks_cache_ttl_seconds: int = Field(
        default=600, validation_alias="SP_CLERK_JWKS_CACHE_TTL_SECONDS"
    )

    # R5: chart-execute settings
    sp_chart_execute_token_ttl_seconds: int = Field(
        default=60, validation_alias="SP_CHART_EXECUTE_TOKEN_TTL_SECONDS"
    )
    sp_chart_statement_timeout_ms: int = Field(
        default=30_000, validation_alias="SP_CHART_STATEMENT_TIMEOUT_MS"
    )
    sp_chart_connect_timeout_seconds: int = Field(
        default=5, validation_alias="SP_CHART_CONNECT_TIMEOUT_SECONDS"
    )
    sp_chart_total_deadline_seconds: int = Field(
        default=45, validation_alias="SP_CHART_TOTAL_DEADLINE_SECONDS"
    )
    sp_chart_max_rows: int = Field(
        default=10_000, validation_alias="SP_CHART_MAX_ROWS"
    )
    sp_chart_max_cell_bytes: int = Field(
        default=32_768, validation_alias="SP_CHART_MAX_CELL_BYTES"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
