"""Deployment mode helpers."""

import logging
import os

logger = logging.getLogger(__name__)

_TRUTHY_VALUES: frozenset[str] = frozenset({"1", "true", "yes"})


def is_cloud_mode() -> bool:
    return os.environ.get("SP_DEPLOYMENT_MODE", "local") == "cloud"


def is_local_mode() -> bool:
    return not is_cloud_mode()


def byok_custom_endpoint_allowed() -> bool:
    """Return True when custom endpoint_url is permitted for BYOK providers.

    In local mode (SP_DEPLOYMENT_MODE unset or not "cloud"), defaults to True
    so the LocalStack/dev workflow continues to work without requiring an env
    opt-in. In cloud mode, defaults to False; require explicit env opt-in via
    SP_BYOK_ALLOW_CUSTOM_ENDPOINT=1|true|yes.
    """
    raw = os.environ.get("SP_BYOK_ALLOW_CUSTOM_ENDPOINT", "").strip().lower()
    if raw in _TRUTHY_VALUES:
        return True
    if is_local_mode():
        return True
    return False


def _validate_cloud_allowed_origins(raw: str) -> list[str]:
    """Return a list of violation descriptor strings for SP_ALLOWED_ORIGINS.

    Pure helper — no env reads, no logging. Callers pass the raw env value.
    Descriptors use var names only; origin values are never included (they may
    carry sensitive path info — matches the existing "names never values" rule).
    """
    if raw.strip() == "":
        return ["SP_ALLOWED_ORIGINS(unset_or_empty)"]

    descriptors: set[str] = set()
    for entry in raw.split(","):
        stripped = entry.strip()
        if stripped == "":
            descriptors.add("SP_ALLOWED_ORIGINS(empty_entry)")
            continue
        if "*" in stripped:
            descriptors.add("SP_ALLOWED_ORIGINS(wildcard)")
            continue
        if stripped.startswith(("http://localhost", "http://127.0.0.1")):
            continue
        if stripped.startswith("https://"):
            continue
        # Non-https, non-loopback entry — extract scheme without including the value
        if "://" in stripped:
            scheme = stripped.split("://", 1)[0]
        else:
            scheme = "unparseable"
        descriptors.add(f"SP_ALLOWED_ORIGINS(non_https:{scheme})")

    return sorted(descriptors)


def assert_cloud_hardening_intact() -> None:
    """Validate that security kill-switches are not disabled in cloud mode.

    This is the single canonical source for kill-switch enforcement at runtime.
    A complementary early-failure path exists in gateway/config/k8s.py (pydantic
    settings validation at instantiation time for SP_NOTEBOOK_RUNTIME_CLASS).
    That path fires before lifespan; this validator catches any path that bypasses
    pydantic settings instantiation (subprocess, test harness, misconfigured import).

    Enforced kill-switches and required settings (final list — extend only via spec revision):
      CLERK_JWT_AUDIENCE          — optional Clerk client binding; when set,
                                    auth/user.py validates JWT aud at request time.
      SP_NOTEBOOK_NETWORK_POLICY  — case-insensitive "false" logs an explicit
                                    cloud warning because gVisor + VPC CNI
                                    NetworkPolicy currently breaks notebook
                                    pod egress.
      SP_NOTEBOOK_RUNTIME_CLASS   — empty string is forbidden
      SP_NOTEBOOK_DIRECT_URL      — any non-empty value is forbidden
      SP_DISABLE_SANDBOX          — case-insensitive "true", "1", "yes" is forbidden
      SP_ALLOWED_ORIGINS          — must be set; no wildcards; all entries must be
                                    https:// or http://localhost / http://127.0.0.1 (L-5)

    Raises RuntimeError listing violated env var NAMES (never values — values may
    contain secrets such as embedded tokens in a direct URL).
    """
    if not is_cloud_mode():
        return

    violations: list[str] = []

    # Clerk's default session JWTs may not carry an aud claim. Keep
    # CLERK_JWT_AUDIENCE as opt-in hardening: auth/user.py validates aud when
    # configured and disables aud verification only when it is absent.

    # SP_NOTEBOOK_NETWORK_POLICY=false disables full default-deny in cloud mode.
    # Full default-deny requires the AWS VPC CNI NetworkPolicy agent, whose eBPF
    # enforcement does NOT compose with gVisor pods (the runsc userspace netstack
    # egress isn't matched by the agent's ipBlock allow rules), so enabling it
    # severs pod->gateway egress and breaks every notebook. The crown-jewel threat
    # this kill-switch defends — node IAM credential theft via IMDS — is
    # independently closed by the IMDS hop-limit=1 (verified: a pod's IMDSv2 token
    # PUT times out) PLUS the always-on block-imds-egress NetworkPolicy.
    # Revisit if/when gVisor + VPC CNI NetworkPolicy interop is fixed upstream.
    # I-5: This used to require SP_NOTEBOOK_NETWORK_POLICY_CLOUD_ACK=1|true|yes.
    # The active cloud demo can legitimately run with this set to false because
    # VPC CNI NetworkPolicy and gVisor do not currently compose. Warn loudly at
    # startup, but do not refuse to boot.
    netpol = os.environ.get("SP_NOTEBOOK_NETWORK_POLICY", "true").strip().lower()
    if netpol == "false":
        logger.warning(
            "SP_NOTEBOOK_NETWORK_POLICY=false in cloud mode: full default-deny is "
            "disabled (gVisor + VPC CNI NetworkPolicy incompatibility). IMDS "
            "credential theft remains blocked via hop-limit + block-imds-egress "
            "policy; arbitrary outbound egress from notebooks is NOT restricted."
        )

    runtime_class = os.environ.get("SP_NOTEBOOK_RUNTIME_CLASS", "").strip()
    if runtime_class == "":
        violations.append("SP_NOTEBOOK_RUNTIME_CLASS")

    direct_url = os.environ.get("SP_NOTEBOOK_DIRECT_URL", "").strip()
    if direct_url:
        violations.append("SP_NOTEBOOK_DIRECT_URL")

    disable_sandbox = os.environ.get("SP_DISABLE_SANDBOX", "").strip().lower()
    if disable_sandbox in ("true", "1", "yes"):
        violations.append("SP_DISABLE_SANDBOX")

    allowed_origins_raw = os.environ.get("SP_ALLOWED_ORIGINS", "")
    violations.extend(_validate_cloud_allowed_origins(allowed_origins_raw))

    if violations:
        raise RuntimeError(
            f"Cloud mode hardening violations: {violations}. Refusing to boot."
        )
