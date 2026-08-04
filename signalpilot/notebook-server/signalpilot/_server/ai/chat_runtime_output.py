"""Bound and redact notebook outputs before they enter standalone agent traces."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


class ChatRuntimeSessionScopeError(PermissionError):
    pass


def notebook_server_headers(
    *, auth_token: str, server_token: str, session_id: str
) -> dict[str, str]:
    """Authenticate an internal notebook MCP request at both middleware layers."""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "Sp-Server-Token": server_token,
        "Sp-Session-Id": session_id,
    }


def authorize_chat_runtime_session(
    name: str,
    arguments: dict[str, Any],
    session_authorizer: Callable[[str], bool] | None,
) -> None:
    if session_authorizer is None:
        return
    session_id = str(arguments.get("session_id") or "")
    if name == "start_notebook_session" or not session_id or not session_authorizer(session_id):
        raise ChatRuntimeSessionScopeError(
            "NOTEBOOK_SESSION_SCOPE_MISMATCH: notebook tools are restricted to this chat run's analysis kernel"
        )


def redact_chat_runtime_text(value: str, redactions: tuple[str, ...]) -> str:
    for secret in redactions:
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 5:
        return "[nested value omitted]"
    if isinstance(value, dict):
        items = list(value.items())
        compact = {
            str(key)[:100]: _compact_value(item, depth=depth + 1)
            for key, item in items[:50]
        }
        if len(items) > 50:
            compact["__omitted_fields__"] = len(items) - 50
        return compact
    if isinstance(value, list):
        compact = [_compact_value(item, depth=depth + 1) for item in value[:20]]
        if len(value) > 20:
            compact.append({"__omitted_items__": len(value) - 20})
        return compact
    if isinstance(value, str):
        return value[:500] + ("..." if len(value) > 500 else "")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:500]


def compact_chat_runtime_output(
    value: Any,
    *,
    mimetype: str,
    redactions: tuple[str, ...],
) -> str:
    text = redact_chat_runtime_text(str(value), redactions)
    normalized_mimetype = mimetype.lower()
    if any(marker in normalized_mimetype for marker in ("arrow", "parquet", "csv")):
        return "[tabular output retained in the notebook; publish or summarize it to inspect safely]"
    try:
        parsed = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        if "<table" in text.lower() or len(text) > 4_000:
            return "[large tabular output retained in the notebook; publish or summarize it to inspect safely]"
        return text[:2_000] + ("... (preview truncated)" if len(text) > 2_000 else "")
    compact = json.dumps(_compact_value(parsed), ensure_ascii=False, default=str)
    return compact[:4_000] + ("... (preview truncated)" if len(compact) > 4_000 else "")
