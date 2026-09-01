"""Public error shaping for chat run failures.

Turn an agent runtime exception into redacted, user-safe error fields.
Never forward arbitrary environment values.
"""

from __future__ import annotations

import re
import traceback
from typing import Any

from gateway.standalone_chat.domain import redact_error_text, redact_public_payload


class AnalysisRuntimeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        full_trace: str = "",
        diagnostic_context: Any = None,
    ) -> None:
        super().__init__(message)
        self.full_trace = full_trace
        self.diagnostic_context = diagnostic_context


def public_error_message(exc: Exception) -> str:
    """Return the upstream error verbatim except for credential redaction."""
    return redact_error_text(str(exc))


def public_full_trace(exc: Exception) -> str:
    raw = str(getattr(exc, "full_trace", "") or "")
    if not raw:
        raw = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return redact_error_text(raw)


def public_diagnostic_context(exc: Exception) -> dict[str, Any]:
    """Allowlist safe support metadata; never forward arbitrary env values."""
    source = getattr(exc, "diagnostic_context", None)
    if not isinstance(source, dict):
        return {"error_type": type(exc).__name__}
    allowed = {
        "model",
        "auth_mode",
        "credential_present",
        "resume_requested",
        "max_turns",
        "result_subtype",
        "stop_reason",
        "api_error_status",
        "duration_ms",
        "duration_api_ms",
        "sdk_session_id",
        "operation",
        "http_status",
    }
    root = public_error_message(exc)
    root_type = re.match(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)):", root)
    source_error_type = source.get("error_type")
    result: dict[str, Any] = {
        "error_type": (
            redact_error_text(source_error_type)
            if isinstance(source_error_type, str) and source_error_type
            else root_type.group(1)
            if root_type
            else type(exc).__name__
        )
    }
    for key in allowed:
        value = source.get(key)
        if isinstance(value, (str, bool, int, float)):
            result[key] = redact_error_text(value) if isinstance(value, str) else value
    environment = source.get("environment")
    if isinstance(environment, dict):
        result["environment"] = {
            str(key): value
            for key, value in environment.items()
            if str(key)
            in {
                "CLAUDE_CONFIG_DIR",
                "CLAUDE_CODE_OAUTH_TOKEN",
                "ANTHROPIC_API_KEY",
                "SP_GATEWAY_URL",
            }
            and value in {"configured", "cleared", "defaulted", "missing"}
        }
    rate_limit = source.get("rate_limit")
    if isinstance(rate_limit, dict):
        result["rate_limit"] = redact_public_payload(rate_limit)
    return result
