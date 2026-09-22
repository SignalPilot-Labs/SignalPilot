"""Public error shaping for chat run failures.

Turn an agent runtime exception into redacted, user-safe error fields.
Never forward arbitrary environment values.
"""

from __future__ import annotations

import os
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
        raw_error: str | None = None,
        stderr: str | None = None,
        raw_error_truncated: bool = False,
        stderr_truncated: bool = False,
        public_error_code: str | None = None,
        public_error_message: str | None = None,
    ) -> None:
        super().__init__(message)
        # Set when the runtime already classified the failure (for example
        # the transport breaker's ``gateway_unavailable``); the worker then
        # persists that code and sentence instead of ``analysis_failed``.
        self.public_error_code = (
            str(public_error_code).strip()[:100] or None
            if isinstance(public_error_code, str)
            else None
        )
        self.public_error_message = (
            str(public_error_message).strip() or None
            if isinstance(public_error_message, str)
            else None
        )
        self.full_trace = full_trace
        self.diagnostic_context = diagnostic_context
        self.raw_error = raw_error if isinstance(raw_error, str) else message
        self.stderr = stderr if isinstance(stderr, str) else ""
        self.raw_error_truncated = raw_error_truncated
        self.stderr_truncated = stderr_truncated


def public_raw_error_fields(exc: Exception) -> dict[str, Any]:
    """Persist bounded original runtime diagnostics for every chat consumer."""
    from gateway.errors.mcp import sanitize_mcp_error

    result: dict[str, Any] = {}
    for field, limit in (("raw_error", 8192), ("stderr", 4096)):
        value = getattr(exc, field, str(exc) if field == "raw_error" else "")
        text = value if isinstance(value, str) else ""
        for name in ("CLAUDE_CODE_OAUTH_TOKEN", "OAUTH_TOKEN", "ANTHROPIC_API_KEY", "SP_CHAT_TEST_OAUTH_TOKEN"):
            secret = os.environ.get(name)
            if secret:
                text = text.replace(secret, "[REDACTED]")
        text = redact_error_text(text)
        text = re.sub(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s<>\"']+", "[URL REDACTED]", text)
        text = re.sub(r"(?i)\bBearer\s+[^\s\"']+", "Bearer [REDACTED]", text)
        text = re.sub(r"(?i)(?:api[_-]?key|token|password|secret)[\"']?\s*[:=]\s*[\"']?[^\s,;\"']+", "[REDACTED]", text)
        text = re.sub(r"\b(?:spa_[\w.-]+|eyJ[\w-]+\.[\w-]+\.[\w-]+)\b", "[REDACTED]", text)
        safe = sanitize_mcp_error(text, cap=limit + 1)
        result[field] = safe[:limit]
        result[field + "_truncated"] = getattr(exc, field + "_truncated", False) is True or len(safe) > limit
    return result


_DEFAULT_OPERATION = "finishing the run"
# `ReadTimeout('')`, `ConnectError('[Errno 111] ...')`: an exception repr that
# the runtime forwarded as text. Never show it to the user as the answer.
_REPR_FORM = re.compile(r"^\s*(?:[\w.]+\.)?(?P<type>[A-Za-z_]\w*)\((?P<body>.*)\)\s*$", re.DOTALL)
# Only applied to HTTPStatusError text ("Server error '502 Bad Gateway' ...").
_HTTP_STATUS_IN_TEXT = re.compile(r"\b(?P<code>[1-5]\d{2})\b")


def _http_status_of(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def _sentence_for_type(type_name: str, *, operation: str, status: int | None, body: str = "") -> str | None:
    """Map a known runtime exception type (by name) to a plain sentence."""
    if type_name.endswith(("Timeout", "TimeoutException", "TimeoutError")):
        return f"The analysis runtime timed out while {operation}"
    if type_name == "HTTPStatusError":
        if status is None:
            found = _HTTP_STATUS_IN_TEXT.search(body)
            status = int(found.group("code")) if found else None
        return f"The analysis runtime returned HTTP {status}" if status else "The analysis runtime returned an HTTP error"
    if type_name.endswith(("ConnectionError", "ConnectError", "NetworkError", "RemoteProtocolError")):
        return "Could not reach the analysis runtime"
    return None


def _plain_sentence(text: str) -> str | None:
    """First line of ``text`` if it reads as a sentence, else None.

    Rejects empty text, exception reprs (``Type('...')``) and anything that
    starts a traceback.
    """
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    if not first or first.startswith("Traceback") or _REPR_FORM.match(first):
        return None
    return first


def public_error_message(exc: Exception, *, operation: str = _DEFAULT_OPERATION) -> str:
    """Return a user-safe sentence for a chat run failure.

    Never returns ``str(exc)`` or ``repr(exc)`` raw. Known runtime failures map
    to fixed sentences; other errors contribute their first line only when it
    reads as a sentence. The raw text stays in the trace and raw_error fields.
    """
    operation = operation.strip() or _DEFAULT_OPERATION
    text = str(exc)
    mapped = _sentence_for_type(type(exc).__name__, operation=operation, status=_http_status_of(exc), body=text)
    if mapped:
        return mapped
    # Text that is itself an exception repr (the runtime forwards
    # `repr(exc)` inside an AnalysisRuntimeError): map by the named type.
    forwarded = _REPR_FORM.match(text.strip().splitlines()[0]) if text.strip() else None
    if forwarded:
        mapped = _sentence_for_type(
            forwarded.group("type"), operation=operation, status=None, body=forwarded.group("body")
        )
        return mapped or f"{forwarded.group('type')} during {operation}"
    sentence = _plain_sentence(text)
    if sentence is None:
        return f"{type(exc).__name__} during {operation}"
    return redact_error_text(sentence)


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
        "num_turns",
        "notebook_session_id",
        "notebook_session_status",
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
