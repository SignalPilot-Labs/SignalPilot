"""Deployment mode helpers."""

import os


def is_cloud_mode() -> bool:
    return os.environ.get("SP_DEPLOYMENT_MODE", "local") == "cloud"


def is_local_mode() -> bool:
    return not is_cloud_mode()


def assert_cloud_hardening_intact() -> None:
    """Validate that security kill-switches are not disabled in cloud mode.

    This is the single canonical source for kill-switch enforcement at runtime.
    A complementary early-failure path exists in gateway/config/k8s.py (pydantic
    settings validation at instantiation time for SP_NOTEBOOK_RUNTIME_CLASS).
    That path fires before lifespan; this validator catches any path that bypasses
    pydantic settings instantiation (subprocess, test harness, misconfigured import).

    Enforced kill-switches (final list — extend only via spec revision):
      SP_NOTEBOOK_NETWORK_POLICY  — case-insensitive "false" is forbidden
      SP_NOTEBOOK_RUNTIME_CLASS   — empty string is forbidden
      SP_NOTEBOOK_DIRECT_URL      — any non-empty value is forbidden
      SP_DISABLE_SANDBOX          — case-insensitive "true", "1", "yes" is forbidden

    Raises RuntimeError listing violated env var NAMES (never values — values may
    contain secrets such as embedded tokens in a direct URL).
    """
    if not is_cloud_mode():
        return

    violations: list[str] = []

    netpol = os.environ.get("SP_NOTEBOOK_NETWORK_POLICY", "true").strip().lower()
    if netpol == "false":
        violations.append("SP_NOTEBOOK_NETWORK_POLICY")

    runtime_class = os.environ.get("SP_NOTEBOOK_RUNTIME_CLASS", "").strip()
    if runtime_class == "":
        violations.append("SP_NOTEBOOK_RUNTIME_CLASS")

    direct_url = os.environ.get("SP_NOTEBOOK_DIRECT_URL", "").strip()
    if direct_url:
        violations.append("SP_NOTEBOOK_DIRECT_URL")

    disable_sandbox = os.environ.get("SP_DISABLE_SANDBOX", "").strip().lower()
    if disable_sandbox in ("true", "1", "yes"):
        violations.append("SP_DISABLE_SANDBOX")

    if violations:
        raise RuntimeError(
            f"Cloud mode hardening kill-switches set: {violations}. Refusing to boot."
        )
