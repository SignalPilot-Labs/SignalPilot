"""Environment-backed standalone-chat runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass

from gateway.runtime.mode import is_cloud_mode


def standalone_chat_enabled() -> bool:
    raw = os.getenv("SP_FEATURE_STANDALONE_CHAT")
    if raw is None:
        return not is_cloud_mode()
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _disabled_by_default_flag(name: str) -> bool:
    """Read an enterprise rollout flag that is always opt-in."""
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class EnterpriseChatFeatureFlags:
    """Independent rollout boundaries for the enterprise runtime phases."""

    sandbox_runtime: bool
    query_approval: bool
    structured_results: bool
    organization_sharing: bool
    forking: bool
    size_router: bool
    size_router_shadow: bool
    runtime_results: bool
    runtime_artifacts: bool
    dataset_refs: bool


def enterprise_chat_feature_flags() -> EnterpriseChatFeatureFlags:
    size_router_value = os.getenv("SP_FEATURE_CHAT_SIZE_ROUTER", "").strip().lower()
    return EnterpriseChatFeatureFlags(
        sandbox_runtime=_disabled_by_default_flag("SP_FEATURE_CHAT_SANDBOX_RUNTIME"),
        query_approval=_disabled_by_default_flag("SP_FEATURE_CHAT_QUERY_APPROVAL"),
        structured_results=_disabled_by_default_flag("SP_FEATURE_CHAT_STRUCTURED_RESULTS"),
        organization_sharing=_disabled_by_default_flag("SP_FEATURE_CHAT_ORG_SHARING"),
        forking=_disabled_by_default_flag("SP_FEATURE_CHAT_FORKING"),
        size_router=size_router_value in {"1", "true", "yes", "on", "enforced"},
        size_router_shadow=size_router_value == "shadow",
        runtime_results=_disabled_by_default_flag("SP_FEATURE_CHAT_RUNTIME_RESULTS"),
        runtime_artifacts=_disabled_by_default_flag("SP_FEATURE_CHAT_RUNTIME_ARTIFACTS"),
        dataset_refs=_disabled_by_default_flag("SP_FEATURE_CHAT_DATASET_REFS"),
    )


def runtime_env() -> str | None:
    """Environment label stamped on runs and used for worker claim affinity.

    Unset/empty means unpartitioned: runs are stamped NULL and the worker
    claims every run regardless of label (the pre-partitioning behavior).
    """
    value = os.getenv("SP_RUNTIME_ENV", "").strip()
    return value[:50] or None


def worker_concurrency() -> int:
    raw = os.getenv("CHAT_WORKER_CONCURRENCY", "4")
    try:
        value = int(raw)
    except ValueError:
        return 4
    return min(32, max(1, value))


def lease_seconds() -> int:
    raw = os.getenv("CHAT_WORKER_LEASE_SECONDS", "45")
    try:
        value = int(raw)
    except ValueError:
        return 45
    return min(600, max(15, value))


def worker_poll_seconds() -> float:
    raw = os.getenv("CHAT_WORKER_POLL_SECONDS", "1.0")
    try:
        value = float(raw)
    except ValueError:
        return 1.0
    return min(10.0, max(0.1, value))
