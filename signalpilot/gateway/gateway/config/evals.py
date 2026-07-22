"""Eval-run settings for the gateway ("Evaluate Change" on knowledge entries).

Cached because no test monkeypatches these vars after import (new vars,
verified by grep at introduction — audit tests/ before adding more).

Class A vars managed here:
    SP_EVAL_RUNNER_IMAGE       — docker image with the claude CLI; feature disabled when unset
    SP_EVAL_DOCKER_SOCKET      — Docker Engine socket path mounted into the gateway
    SP_EVAL_DOCKER_NETWORK     — network eval containers join (must reach the gateway)
    SP_EVAL_MCP_URL            — MCP URL eval containers use to reach this gateway
    SP_EVAL_CLAUDE_TOKEN       — CLAUDE_CODE_OAUTH_TOKEN passed to eval containers
    SP_EVAL_ANTHROPIC_KEY      — alternative: ANTHROPIC_API_KEY for eval containers
    SP_EVAL_TIMEOUT_SECONDS    — per-question container timeout
    SP_EVAL_PROJECTS_DIR       — root allowed for local-path eval sets (mounted ro)
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from ._base import _GatewaySettingsBase


class EvalRunSettings(_GatewaySettingsBase):
    """Typed eval-run configuration read from process environment at instantiation."""

    runner_image: str = Field("", alias="SP_EVAL_RUNNER_IMAGE")
    docker_socket: str = Field("/var/run/docker.sock", alias="SP_EVAL_DOCKER_SOCKET")
    docker_network: str = Field("signalpilot_default", alias="SP_EVAL_DOCKER_NETWORK")
    mcp_url: str = Field("http://gateway:3300/mcp", alias="SP_EVAL_MCP_URL")
    claude_token_raw: str = Field("", alias="SP_EVAL_CLAUDE_TOKEN")
    # Fallback for local runs when no token is set in the environment.
    claude_key_1: str = Field("", alias="CLAUDE_KEY_1")
    anthropic_key: str = Field("", alias="SP_EVAL_ANTHROPIC_KEY")
    timeout_seconds: int = Field(600, alias="SP_EVAL_TIMEOUT_SECONDS")
    projects_dir: str = Field("/eval-projects", alias="SP_EVAL_PROJECTS_DIR")
    # ── Setup-state containers (eval-format.md §setup) ──────────────────
    # Host path corresponding to the /eval-projects mount, so local-path eval
    # repos can be bind-mounted into setup containers (docker binds resolve
    # against the HOST, not the gateway container).
    projects_host_dir: str = Field("", alias="SP_EVAL_PROJECTS_HOST_DIR")
    # Host root for manifest `setup.mounts` entries (external dbt trees etc.).
    setup_host_root: str = Field("", alias="SP_EVAL_SETUP_HOST_ROOT")
    setup_timeout_seconds: int = Field(1800, alias="SP_EVAL_SETUP_TIMEOUT_SECONDS")

    @property
    def enabled(self) -> bool:
        return bool(self.runner_image)

    @property
    def claude_token(self) -> str:
        return self.claude_token_raw or self.claude_key_1


@lru_cache(maxsize=1)
def get_eval_run_settings() -> EvalRunSettings:
    """Return cached EvalRunSettings instance."""
    return EvalRunSettings()
