"""Environment-backed standalone-chat runtime settings."""

from __future__ import annotations

import os

from gateway.runtime.mode import is_cloud_mode


def standalone_chat_enabled() -> bool:
    raw = os.getenv("SP_FEATURE_STANDALONE_CHAT")
    if raw is None:
        return not is_cloud_mode()
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
