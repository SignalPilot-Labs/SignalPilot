"""Environment-backed standalone-chat runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass

from gateway.runtime.mode import is_cloud_mode, runtime_env

__all__ = ["runtime_env"]


CHAT_MODEL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("claude-opus-4-6", "Opus 4.6"),
    ("claude-sonnet-4-6", "Sonnet 4.6"),
    ("claude-opus-5", "Opus 5"),
    ("claude-fable-5-1", "Fable 5.1"),
)
CHAT_MODEL_IDS = frozenset(model_id for model_id, _label in CHAT_MODEL_OPTIONS)
FALLBACK_CHAT_MODEL = "claude-opus-4-6"


def default_chat_model() -> str:
    """Return the selectable deployment default, ignoring invalid overrides."""
    configured = os.getenv("SP_CHAT_AGENT_MODEL", "").strip()
    return configured if configured in CHAT_MODEL_IDS else FALLBACK_CHAT_MODEL


def standalone_chat_enabled() -> bool:
    raw = os.getenv("SP_FEATURE_STANDALONE_CHAT")
    if raw is None:
        return not is_cloud_mode()
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _disabled_by_default_flag(name: str) -> bool:
    """Read an enterprise rollout flag that is always opt-in."""
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _enabled_by_default_flag(name: str) -> bool:
    """Read a flag that is on in every mode unless explicitly turned off."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
    # Connectors: external MCP servers for the chat agent. On everywhere; opt out with
    # SP_FEATURE_CHAT_MCP_CONNECTORS=false.
    mcp_connectors: bool


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
        mcp_connectors=_enabled_by_default_flag("SP_FEATURE_CHAT_MCP_CONNECTORS"),
    )


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


def _bounded_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def chat_file_max_bytes() -> int:
    """Largest single runtime file the gateway accepts. Default 25 MB."""
    return _bounded_int_env(
        "SP_CHAT_FILE_MAX_BYTES",
        25 * 1024 * 1024,
        minimum=1024,
        maximum=1024 * 1024 * 1024,
    )


def conversation_file_quota_bytes() -> int:
    """Total active file bytes allowed per conversation. Default 250 MB."""
    return _bounded_int_env(
        "SP_CHAT_CONVERSATION_FILE_QUOTA_BYTES",
        250 * 1024 * 1024,
        minimum=1024,
        maximum=100 * 1024 * 1024 * 1024,
    )


def conversation_file_quota_count() -> int:
    """Active file rows allowed per conversation. Default 500."""
    return _bounded_int_env(
        "SP_CHAT_CONVERSATION_FILE_QUOTA_COUNT",
        500,
        minimum=1,
        maximum=100_000,
    )
