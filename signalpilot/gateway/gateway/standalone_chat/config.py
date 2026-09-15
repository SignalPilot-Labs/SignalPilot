"""Environment-backed standalone-chat runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass

from gateway.runtime.mode import runtime_env

__all__ = ["runtime_env"]


CHAT_MODEL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("claude-opus-4-6", "Opus 4.6"),
    ("claude-sonnet-4-6", "Sonnet 4.6"),
    ("claude-opus-5", "Opus 5"),
    ("claude-fable-5-1", "Fable 5.1"),
)
CHAT_MODEL_IDS = frozenset(model_id for model_id, _label in CHAT_MODEL_OPTIONS)
FALLBACK_CHAT_MODEL = "claude-opus-4-6"
CHAT_EFFORT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
    ("xhigh", "Extra high"),
    ("max", "Max"),
)
CHAT_EFFORT_IDS = frozenset(effort_id for effort_id, _label in CHAT_EFFORT_OPTIONS)
FALLBACK_CHAT_EFFORT = "medium"


def default_chat_model() -> str:
    """Return the selectable deployment default, ignoring invalid overrides."""
    configured = os.getenv("SP_CHAT_AGENT_MODEL", "").strip()
    return configured if configured in CHAT_MODEL_IDS else FALLBACK_CHAT_MODEL


def default_chat_effort() -> str:
    """Return the Agent SDK effort default, ignoring invalid overrides."""
    configured = os.getenv("SP_AGENT_EFFORT", "").strip().lower()
    return configured if configured in CHAT_EFFORT_IDS else FALLBACK_CHAT_EFFORT


def _kill_switch_on(name: str) -> bool:
    """Read an emergency kill switch: on in every mode unless explicitly set to false."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def standalone_chat_enabled() -> bool:
    """Kill switch ``SP_FEATURE_STANDALONE_CHAT``: chat and reports are on unless it is set to false.

    Who may use chat is the org's plan (``RequireBillablePlan``). This switch
    exists only to take the whole surface offline in an emergency; when it is
    off the routes answer 503 ``not_available_in_deployment``.
    """
    return _kill_switch_on("SP_FEATURE_STANDALONE_CHAT")


@dataclass(frozen=True)
class EnterpriseChatFeatureFlags:
    """Deployment kill switches for the chat runtime capabilities.

    Every flag is on by default. The ``SP_FEATURE_CHAT_*`` variables are
    emergency switches for operators, not entitlements: whether an org may use
    chat at all is the billable-plan rule, and the bootstrap payload reports
    each capability as ``is_billable and not kill_switch_off``.
    """

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
    # Connectors: external MCP servers for the chat agent.
    mcp_connectors: bool

    def as_dict(self) -> dict[str, bool]:
        return {
            "sandbox_runtime": self.sandbox_runtime,
            "query_approval": self.query_approval,
            "structured_results": self.structured_results,
            "organization_sharing": self.organization_sharing,
            "forking": self.forking,
            "size_router": self.size_router,
            "size_router_shadow": self.size_router_shadow,
            "runtime_results": self.runtime_results,
            "runtime_artifacts": self.runtime_artifacts,
            "dataset_refs": self.dataset_refs,
            "mcp_connectors": self.mcp_connectors,
        }


def enterprise_chat_feature_flags() -> EnterpriseChatFeatureFlags:
    """Read the kill switches. Unset means on.

    ``SP_FEATURE_CHAT_SIZE_ROUTER`` accepts a third value, ``shadow``, which
    estimates routes without enforcing them.
    """
    size_router_raw = os.getenv("SP_FEATURE_CHAT_SIZE_ROUTER")
    size_router_value = (size_router_raw or "").strip().lower()
    size_router_shadow = size_router_value == "shadow"
    size_router = not size_router_shadow and _kill_switch_on("SP_FEATURE_CHAT_SIZE_ROUTER")
    return EnterpriseChatFeatureFlags(
        sandbox_runtime=_kill_switch_on("SP_FEATURE_CHAT_SANDBOX_RUNTIME"),
        query_approval=_kill_switch_on("SP_FEATURE_CHAT_QUERY_APPROVAL"),
        structured_results=_kill_switch_on("SP_FEATURE_CHAT_STRUCTURED_RESULTS"),
        organization_sharing=_kill_switch_on("SP_FEATURE_CHAT_ORG_SHARING"),
        forking=_kill_switch_on("SP_FEATURE_CHAT_FORKING"),
        size_router=size_router,
        size_router_shadow=size_router_shadow,
        runtime_results=_kill_switch_on("SP_FEATURE_CHAT_RUNTIME_RESULTS"),
        runtime_artifacts=_kill_switch_on("SP_FEATURE_CHAT_RUNTIME_ARTIFACTS"),
        dataset_refs=_kill_switch_on("SP_FEATURE_CHAT_DATASET_REFS"),
        mcp_connectors=_kill_switch_on("SP_FEATURE_CHAT_MCP_CONNECTORS"),
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
