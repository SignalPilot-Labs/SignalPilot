"""Inference source resolution for the Workspaces API.

Resolves which inference backend to use based on deployment mode and the
caller's requested inference type. Returns an InferenceBundle dataclass
whose __repr__ masks all secrets — no token ever appears in a log line.

Decision tree:
  local mode  + (None | "local") + CLAUDE_CODE_OAUTH_TOKEN → InferenceBundle(mode="local")
  local mode  + anything else                               → InferenceNotConfigured
  cloud mode  + "metered"                                   → MeteredNotImplemented
  cloud mode  + (None | "byo")   + ANTHROPIC_API_KEY        → InferenceBundle(mode="byo")
  cloud mode  + (None | "byo")   + no key                   → InferenceNotConfigured
  cloud mode  + anything else                               → InferenceNotConfigured
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from workspaces_api.errors import InferenceNotConfigured, MeteredNotImplemented

logger = logging.getLogger(__name__)

_MASKED = "***"


@dataclass(frozen=True, slots=True)
class InferenceBundle:
    """Resolved inference configuration.

    Secrets are masked in __repr__ so that logging a SpawnRequest (which
    embeds this object) never leaks tokens. Tests in tests/test_spawner.py
    and tests/test_inference.py assert this invariant.
    """

    mode: Literal["local", "byo"]
    oauth_token: str | None
    api_key: str | None
    base_url: str | None

    def __repr__(self) -> str:
        oauth_display = _MASKED if self.oauth_token else None
        api_key_display = _MASKED if self.api_key else None
        return (
            f"InferenceBundle(mode={self.mode!r}, "
            f"oauth_token={oauth_display!r}, "
            f"api_key={api_key_display!r}, "
            f"base_url={self.base_url!r})"
        )


def resolve_inference_source(
    settings: object,
    requested: Literal["local", "byo", "metered"] | None,
) -> InferenceBundle:
    """Resolve the inference source from settings and the caller's preference.

    Args:
        settings: A Settings instance (typed as object to avoid circular import;
                  attributes accessed by name).
        requested: Caller-requested inference mode, or None for mode-default.

    Returns:
        InferenceBundle describing the resolved inference configuration.

    Raises:
        InferenceNotConfigured: When the required credentials are absent.
        MeteredNotImplemented: When metered inference is requested (R3+).
    """
    mode = settings.sp_deployment_mode  # type: ignore[attr-defined]

    if mode == "local":
        if requested in (None, "local"):
            token = settings.claude_code_oauth_token  # type: ignore[attr-defined]
            token_value = token.get_secret_value() if token is not None else None
            if not token_value:
                raise InferenceNotConfigured(
                    "Set CLAUDE_CODE_OAUTH_TOKEN for local mode."
                )
            return InferenceBundle(
                mode="local",
                oauth_token=token_value,
                api_key=None,
                base_url=None,
            )
        raise InferenceNotConfigured(
            f"local mode only supports requested='local', got {requested!r}."
        )

    if mode == "cloud":
        if requested == "metered":
            raise MeteredNotImplemented(
                "Metered inference is not yet implemented (round 3+)."
            )
        if requested in (None, "byo"):
            api_key = settings.anthropic_api_key  # type: ignore[attr-defined]
            key_value = api_key.get_secret_value() if api_key is not None else None
            if not key_value:
                raise InferenceNotConfigured(
                    "Configure an Anthropic API key in Settings (BYO)."
                )
            return InferenceBundle(
                mode="byo",
                oauth_token=None,
                api_key=key_value,
                base_url=None,
            )
        raise InferenceNotConfigured(
            f"Unsupported requested inference: {requested!r}"
        )

    raise InferenceNotConfigured(f"Unknown deployment mode: {mode!r}")
