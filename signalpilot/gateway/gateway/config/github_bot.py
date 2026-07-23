"""PipelineProof GitHub bot settings.

Class A vars managed here:
    SP_GITHUB_BOT_TOKEN       — PAT used to comment on PRs / set statuses when no
                                GitHub App installation covers the repo (local
                                testing; production uses App installation tokens)
    SP_GITHUB_WEBHOOK_SECRET  — HMAC secret for /api/github/webhook signatures.
                                Unset ⇒ webhook rejected in cloud mode, accepted
                                unsigned in local mode (dev convenience).
    SP_GITHUB_BOT_CONNECTION  — default connection name the verification battery
                                runs against when a scan doesn't specify one
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from ._base import _GatewaySettingsBase


class GitHubBotSettings(_GatewaySettingsBase):
    token: str = Field("", alias="SP_GITHUB_BOT_TOKEN")
    webhook_secret: str = Field("", alias="SP_GITHUB_WEBHOOK_SECRET")
    default_connection: str = Field("", alias="SP_GITHUB_BOT_CONNECTION")


@lru_cache(maxsize=1)
def get_github_bot_settings() -> GitHubBotSettings:
    return GitHubBotSettings()
