"""Text helpers shared by the tool-result projectors."""

from __future__ import annotations

import ast
import json
import re
from typing import Any

from gateway.errors.mcp import sanitize_mcp_error
from gateway.standalone_chat.tool_projection.limits import (
    ERROR_TEXT_MAX,
    JSON_DEPTH_MAX,
    JSON_ITEMS_MAX,
    JSON_KEYS_MAX,
    JSON_STR_MAX,
    SUMMARY_MAX,
)

_COUNT_RE = re.compile(r"^\s*([\d][\d,]*(?:\.\d+)?)\s*([kKmMbB])?\s*$")
_MS_RE = re.compile(r"^\s*([\d][\d,]*(?:\.\d+)?)\s*(ms|s)?\s*$")
_LEGACY_DICT_PREFIX = "[{'type': 'text'"
_LEGACY_TEXTCONTENT_RE = re.compile(
    r"^\[TextContent\(type='text', text=(?P<literal>'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")",
    re.DOTALL,
)
_SUFFIX_MULTIPLIER = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def clip(text: str, limit: int) -> tuple[str, bool]:
    """Return ``text`` cut to ``limit`` chars and whether it was cut."""
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def clip_tail(text: str, limit: int) -> tuple[str, bool]:
    """Keep the last ``limit`` chars (logs are read from the end)."""
    if len(text) <= limit:
        return text, False
    return text[-limit:], True


def first_line(text: str, limit: int = SUMMARY_MAX) -> str:
    """First non-empty line, whitespace-collapsed, capped at ``limit``."""
    for raw in (text or "").splitlines():
        line = " ".join(raw.split())
        if line:
            return line if len(line) <= limit else line[: limit - 1] + "…"
    return ""


def parse_count(token: Any) -> int | None:
    """Parse ``1,204`` / ``1.2M`` / ``45K`` / ``312`` into an int."""
    if isinstance(token, bool):
        return None
    if isinstance(token, int):
        return token
    if isinstance(token, float):
        return int(token)
    match = _COUNT_RE.match(str(token or ""))
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    suffix = (match.group(2) or "").lower()
    return int(round(number * _SUFFIX_MULTIPLIER.get(suffix, 1)))


def parse_ms(token: Any) -> float | None:
    """Parse ``312ms`` / ``1.5s`` / ``312`` into milliseconds."""
    if isinstance(token, (int, float)) and not isinstance(token, bool):
        return float(token)
    match = _MS_RE.match(str(token or ""))
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    return number * 1000 if match.group(2) == "s" else number


def format_count(value: int | None) -> str:
    return "?" if value is None else f"{value:,}"


def format_ms(value: float | None) -> str:
    if value is None:
        return ""
    if value >= 1_000:
        return f"{value / 1000:.1f} s"
    return f"{int(round(value))} ms"


def compact_json(value: Any, *, depth: int = 0) -> Any:
    """Bound a JSON value: depth ≤5, ≤50 keys, ≤20 items, strings ≤500."""
    if isinstance(value, str):
        return value if len(value) <= JSON_STR_MAX else value[:JSON_STR_MAX] + "…"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if depth >= JSON_DEPTH_MAX:
        return "…"
    if isinstance(value, dict):
        items = list(value.items())
        out = {str(key): compact_json(item, depth=depth + 1) for key, item in items[:JSON_KEYS_MAX]}
        if len(items) > JSON_KEYS_MAX:
            out["…"] = f"{len(items) - JSON_KEYS_MAX} more keys"
        return out
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        out_list = [compact_json(item, depth=depth + 1) for item in items[:JSON_ITEMS_MAX]]
        if len(items) > JSON_ITEMS_MAX:
            out_list.append(f"…{len(items) - JSON_ITEMS_MAX} more items")
        return out_list
    return str(value)


def try_json(text: str) -> Any | None:
    """Parse ``text`` as a JSON object/array; None when it is not one."""
    stripped = (text or "").strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def legacy_repr_text(content: str) -> str | None:
    """Extract the text from a legacy ``str(content_blocks)`` tool result.

    Older sandbox images forwarded MCP results as a Python repr of the block
    list. ``ast.literal_eval`` handles the dict form; the ``TextContent(...)``
    form is unwrapped from its first ``text=`` literal. Anything else → None.
    """
    body = (content or "").strip()
    if body.startswith(_LEGACY_DICT_PREFIX):
        try:
            blocks = ast.literal_eval(body)
        except (ValueError, SyntaxError, MemoryError, RecursionError, TypeError):
            return None
        if not isinstance(blocks, list):
            return None
        parts = [
            str(block.get("text") or "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(parts) if parts else None
    match = _LEGACY_TEXTCONTENT_RE.match(body)
    if match:
        try:
            literal = ast.literal_eval(match.group("literal"))
        except (ValueError, SyntaxError, MemoryError, RecursionError, TypeError):
            return None
        return literal if isinstance(literal, str) else None
    return None


def normalize_content(content: Any) -> str:
    """Coerce a tool result to text, unwrapping legacy repr bodies."""
    if content is None:
        text = ""
    elif isinstance(content, str):
        text = content
    else:
        try:
            text = json.dumps(content, default=str)
        except (TypeError, ValueError):
            text = str(content)
    legacy = legacy_repr_text(text)
    text = legacy if legacy is not None else text
    return unwrap_result_envelope(text)


def unwrap_result_envelope(text: str) -> str:
    """Strip the ``{"result": "<text>"}`` envelope Claude Code puts around MCP results.

    FastMCP publishes a plain ``str`` return as ``structuredContent``
    ``{"result": value}`` and the agent runtime hands the model that JSON
    rather than the text block. Every gateway tool therefore arrives wrapped;
    the audit of staging ``tool_completed`` rows showed 11/11 query results
    in this form. Only the exact single-key string form is unwrapped so real
    JSON tools keep their shape.
    """
    stripped = text.lstrip()
    if not stripped.startswith('{"result"'):
        return text
    parsed = try_json(stripped)
    if isinstance(parsed, dict) and set(parsed) == {"result"} and isinstance(parsed["result"], str):
        return parsed["result"]
    return text


def error_projection(content: str) -> tuple[str, str]:
    """Return ``(summary, result_text)`` for a failed tool call.

    Both are passed through ``sanitize_mcp_error`` so credential-looking
    fragments never reach the browser. Connector sign-in errors ("… needs
    you to sign in …") survive verbatim because the sanitizer only rewrites
    secrets, paths and traceback frames.
    """
    raw = strip_tool_use_error(content) or "The tool returned an error."
    headline = first_line(sanitize_mcp_error(first_line(raw, limit=ERROR_TEXT_MAX), cap=SUMMARY_MAX))
    body = sanitize_mcp_error(raw, cap=ERROR_TEXT_MAX)
    return headline or "The tool returned an error.", body


_TOOL_USE_ERROR_RE = re.compile(r"^\s*<tool_use_error>(.*?)</tool_use_error>\s*$", re.DOTALL)


def strip_tool_use_error(text: str) -> str:
    """Unwrap the ``<tool_use_error>…</tool_use_error>`` tags the SDK puts around builtin failures."""
    match = _TOOL_USE_ERROR_RE.match(text or "")
    return match.group(1).strip() if match else (text or "")


def summary_text(text: str, fallback: str) -> str:
    """Summary line for free-text results: first line or ``fallback``."""
    return first_line(text) or fallback
