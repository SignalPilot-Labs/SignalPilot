"""
Structured audit logging for sandbox code execution.

Emits a single JSON log line per execution event. The log is designed to be
grep-friendly and compatible with log aggregators (CloudWatch, Datadog, ELK).

The code itself is never logged — only its SHA-256 hash — because user code may
contain credentials (e.g., database connection strings).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("sandbox_audit")

_SESSION_TOKEN_PREFIX_LEN = 8


def _hash_code(code: str) -> str:
    """Return SHA-256 hex digest of code string."""
    return hashlib.sha256(code.encode()).hexdigest()


def log_execution(
    *,
    session_token: str,
    vm_id: str,
    code_length: int,
    code_hash: str,
    timeout: int,
    mount_count: int,
    success: bool,
    error: str | None,
    execution_ms: float,
    client_ip: str | None,
) -> None:
    """Emit a structured JSON audit log line for a sandbox execution event.

    The ``session_token`` is truncated to the first 8 characters to avoid
    leaking full tokens into log aggregators. Never pass the code itself —
    callers should compute ``code_hash`` via :func:`hash_code_for_audit`.

    This function is guaranteed not to raise. Any internal error is logged at
    WARNING level so the caller's execution response is not affected.
    """
    try:
        payload = {
            "event": "sandbox_execution",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_token": session_token[:_SESSION_TOKEN_PREFIX_LEN],
            "vm_id": vm_id,
            "code_length": code_length,
            "code_hash": code_hash,
            "timeout": timeout,
            "mount_count": mount_count,
            "success": success,
            "error": error,
            "execution_ms": execution_ms,
            "client_ip": client_ip,
        }
        logger.info(json.dumps(payload))
    except Exception as e:  # noqa: BLE001
        logger.warning("audit log failed: %s", e)


def hash_code_for_audit(code: str) -> str:
    """Return SHA-256 hex digest of ``code`` for use as ``code_hash``."""
    return _hash_code(code)
