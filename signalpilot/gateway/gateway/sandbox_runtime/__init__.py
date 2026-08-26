"""Ephemeral sandbox VMs for automated improvement runs."""

from __future__ import annotations

from gateway.config.sandbox_runtime import get_sandbox_runtime_settings
from gateway.sandbox_runtime.base import (
    ExecResult,
    GitCheckout,
    SandboxNotFound,
    SandboxRuntime,
    SandboxRuntimeError,
    SandboxSpec,
)

__all__ = [
    "ExecResult",
    "GitCheckout",
    "SandboxNotFound",
    "SandboxRuntime",
    "SandboxRuntimeError",
    "SandboxSpec",
    "get_sandbox_runtime",
]


def get_sandbox_runtime() -> SandboxRuntime:
    """Return the configured sandbox runtime, or raise if none is usable."""
    settings = get_sandbox_runtime_settings()
    if not settings.enabled:
        raise SandboxRuntimeError(
            "No sandbox runtime is configured. Set SP_SANDBOX_RUNTIME_PROVIDER "
            "and the provider's credentials (for vercel: VERCEL_TOKEN, "
            "VERCEL_TEAM_ID, VERCEL_PROJECT_ID)."
        )
    if settings.provider == "vercel":
        from gateway.sandbox_runtime.vercel import VercelSandboxRuntime

        return VercelSandboxRuntime(project_id=settings.vercel_project_id)
    raise SandboxRuntimeError(f"Unknown sandbox runtime provider: {settings.provider}")
