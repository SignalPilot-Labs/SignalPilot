"""Notebook Runtime v2 configuration.

Backend selection mirrors the eval seam (SP_EVAL_EXECUTION_BACKEND):

    SP_NOTEBOOK_EXECUTION_BACKEND
        ""        -> pick by environment: "direct" when SP_NOTEBOOK_DIRECT_URL
                     is set (local compose), else "vercel".
        "vercel"  -> Vercel Sandbox VMs (needs VERCEL_* credentials).
        "direct"  -> one shared notebook container at SP_NOTEBOOK_DIRECT_URL.

There is no Kubernetes notebook backend: Notebook Runtime v2 removed it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

_DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")

KNOWN_BACKENDS = ("", "vercel", "direct")


def chat_force_oauth_token() -> bool:
    """Whether standalone chat must use the gateway's Claude OAuth token.

    Force mode is deliberately separate from normal credential precedence. A
    user chat fails closed when the token is missing, and its notebook process
    is launched without the organization's Anthropic API key.
    """
    return os.getenv("SP_CHAT_FORCE_OAUTH_TOKEN", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class NotebookSettings:
    execution_backend: str = field(
        default_factory=lambda: os.getenv("SP_NOTEBOOK_EXECUTION_BACKEND", "").strip().lower()
    )
    direct_url: str = field(default_factory=lambda: os.getenv("SP_NOTEBOOK_DIRECT_URL", "").strip())
    # Vercel Container Registry image the sandbox boots. Digest-pinned in cloud
    # mode — a floating tag would let what actually runs change silently.
    vercel_image: str = field(default_factory=lambda: os.getenv("SP_NOTEBOOK_VERCEL_IMAGE", "").strip())
    # Per-grant execution time; the lifecycle loop extends active sessions by
    # this much. The provider caps a single grant at 2700 s.
    session_grant_seconds: int = field(
        default_factory=lambda: int(os.getenv("SP_NOTEBOOK_SESSION_GRANT_SECONDS", "1800"))
    )
    # Idle threshold after which a session is flushed, snapshotted, and its
    # sandbox destroyed (scale-to-zero). Resume happens on the next request.
    idle_snapshot_seconds: int = field(
        default_factory=lambda: int(os.getenv("SP_NOTEBOOK_IDLE_SNAPSHOT_SECONDS", "900"))
    )
    # How long snapshots stay resumable before a cold start takes over.
    # Provider floor is one day (verified live); shorter values are clamped.
    snapshot_expiration_seconds: int = field(
        default_factory=lambda: max(
            86400,
            int(os.getenv("SP_NOTEBOOK_SNAPSHOT_EXPIRATION_SECONDS", str(7 * 86400))),
        )
    )
    start_timeout_seconds: int = field(
        default_factory=lambda: max(30, int(os.getenv("SP_NOTEBOOK_START_TIMEOUT_SECONDS", "90")))
    )
    vcpus: int = field(default_factory=lambda: int(os.getenv("SP_NOTEBOOK_VCPUS", "2")))
    memory_mb: int = field(default_factory=lambda: int(os.getenv("SP_NOTEBOOK_MEMORY_MB", "4096")))
    # Comma-separated egress allowlist. Unset = provider default; the deploy
    # sets the gateway public host, warehouse hosts, and pypi.org here.
    egress_allow: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            host.strip()
            for host in os.getenv("SP_NOTEBOOK_EGRESS_ALLOW", "").split(",")
            if host.strip()
        )
    )
    # Cap on concurrently RUNNING sandboxes per org — the provider has no
    # tenant quotas, so the gateway enforces the blast radius.
    max_running_per_org: int = field(
        default_factory=lambda: int(os.getenv("SP_NOTEBOOK_MAX_RUNNING_PER_ORG", "20"))
    )

    def __post_init__(self) -> None:
        if self.execution_backend not in KNOWN_BACKENDS:
            raise ValueError(
                f"Unknown SP_NOTEBOOK_EXECUTION_BACKEND={self.execution_backend!r}; "
                f"one of {KNOWN_BACKENDS}"
            )

    def resolved_backend(self) -> str:
        if self.execution_backend:
            return self.execution_backend
        return "direct" if self.direct_url else "vercel"

    def require_vercel_image(self, *, cloud: bool) -> str:
        if not self.vercel_image:
            raise ValueError(
                "SP_NOTEBOOK_VERCEL_IMAGE is required for the vercel notebook backend"
            )
        if cloud and not _DIGEST_RE.search(self.vercel_image):
            raise ValueError(
                "SP_NOTEBOOK_VERCEL_IMAGE must be digest-pinned (@sha256:...) in cloud mode"
            )
        return self.vercel_image


@lru_cache(maxsize=1)
def get_notebook_settings() -> NotebookSettings:
    return NotebookSettings()


def reset_notebook_settings() -> None:
    get_notebook_settings.cache_clear()
