"""Pure standalone-chat domain rules."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    waiting_for_user = "waiting_for_user"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


NONTERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.queued.value,
        RunStatus.running.value,
        RunStatus.waiting_for_user.value,
    }
)
TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.completed.value,
        RunStatus.failed.value,
        RunStatus.cancelled.value,
    }
)

_RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    RunStatus.queued.value: frozenset(
        {
            RunStatus.running.value,
            RunStatus.cancelled.value,
            RunStatus.failed.value,
        }
    ),
    RunStatus.running.value: frozenset(
        {
            RunStatus.queued.value,
            RunStatus.waiting_for_user.value,
            RunStatus.completed.value,
            RunStatus.failed.value,
            RunStatus.cancelled.value,
        }
    ),
    RunStatus.waiting_for_user.value: frozenset(
        {
            RunStatus.queued.value,
            RunStatus.cancelled.value,
            RunStatus.failed.value,
        }
    ),
    RunStatus.completed.value: frozenset(),
    RunStatus.failed.value: frozenset(),
    RunStatus.cancelled.value: frozenset(),
}


def assert_run_transition(current: str, target: str) -> None:
    """Raise when a durable run transition is not part of the state machine."""
    if current == target:
        return
    allowed = _RUN_TRANSITIONS.get(current)
    if allowed is None or target not in allowed:
        raise ValueError(f"Invalid chat run transition: {current} -> {target}")


def fallback_conversation_title(question: str, max_chars: int = 60) -> str:
    """Create the locked fallback title from the first user question."""
    normalized = re.sub(r"\s+", " ", question).strip()
    if len(normalized) <= max_chars:
        return normalized or "New chat"
    return normalized[: max_chars - 1].rstrip() + "…"


def redact_public_payload(value: Any) -> Any:
    """Remove credential-like fields before a tool payload becomes author-visible."""
    sensitive = {
        "access_token",
        "api_key",
        "authorization",
        "connection_string",
        "credential",
        "credentials",
        "password",
        "private_key",
        "secret",
        "token",
    }
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(marker in normalized for marker in sensitive):
                clean[str(key)] = "[REDACTED]"
            else:
                clean[str(key)] = redact_public_payload(item)
        return clean
    if isinstance(value, list):
        return [redact_public_payload(item) for item in value]
    if isinstance(value, str):
        value = re.sub(
            r"(?i)\b(?:postgres(?:ql)?|mysql|snowflake|redshift|clickhouse)://[^\s]+",
            "[REDACTED_CONNECTION]",
            value,
        )
        value = re.sub(
            r"(?i)\b(?:api[_-]?key|token|password|secret)\s*[=:]\s*[^\s,;]+",
            "[REDACTED]",
            value,
        )
        return value[:20_000]
    return value


def select_context_for_summary(
    messages: list[dict[str, Any]],
    *,
    artifact_refs: list[dict[str, Any]],
    usable_context_chars: int,
    threshold: float = 0.60,
    recent_exchange_count: int = 8,
) -> dict[str, Any] | None:
    """Return deterministic summary inputs once serialized context crosses 60%."""
    serialized_chars = sum(len(str(message.get("content") or "")) for message in messages)
    if serialized_chars < int(usable_context_chars * threshold):
        return None

    keep_count = recent_exchange_count * 2
    older = messages[:-keep_count] if len(messages) > keep_count else []
    recent = messages[-keep_count:]
    older_lines = [
        f"{str(message.get('role') or 'message')}: {str(message.get('content') or '').strip()[:1200]}"
        for message in older
        if str(message.get("content") or "").strip()
    ]
    summary = "\n".join(older_lines)
    if len(summary) > 60_000:
        summary = summary[-60_000:]
    return {
        "summary": summary,
        "recent_messages": recent,
        "artifact_refs": artifact_refs,
    }
