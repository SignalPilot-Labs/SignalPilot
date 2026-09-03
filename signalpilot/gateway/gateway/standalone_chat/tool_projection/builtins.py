"""Projections for the Claude Agent SDK's builtin tools and runtime notices.

These tools are not ours, so the shapes come from observing real runs (the
staging ``tool_completed`` audit of 2026-09-02): ``Read`` returns ``cat -n``
text, ``Glob`` a path per line, ``Grep`` a match per line, ``TodoWrite`` a
fixed confirmation sentence, ``Skill`` ``Launching skill: <name>``, and
``ToolSearch`` one ``{"type": "tool_reference", ...}`` JSON object per line.
The runtime also replaces any oversized result with a pointer to a file in
the sandbox; that notice is recognised for every tool so a huge
``list_tables`` does not render as an error.
"""

from __future__ import annotations

import re
from typing import Any

from gateway.standalone_chat.tool_projection.base import ProjectedResult, text_result
from gateway.standalone_chat.tool_projection.text import first_line, format_count, try_json

BUILTIN_TOOLS = frozenset(
    {
        "Read",
        "Glob",
        "Grep",
        "Write",
        "Edit",
        "MultiEdit",
        "NotebookEdit",
        "TodoWrite",
        "Skill",
        "ToolSearch",
        "WebSearch",
        "WebFetch",
    }
)

_TOO_LARGE_RE = re.compile(
    r"^\s*Error: result \(([\d,]+) characters\) exceeds maximum allowed tokens\. "
    r"Output has been saved to (\S+?)\.?\s*$",
    re.MULTILINE,
)
_CAT_N_RE = re.compile(r"^\s*(\d+)\t", re.MULTILINE)
_SKILL_RE = re.compile(r"^\s*Launching skill:\s*(\S+)", re.IGNORECASE)
_GREP_COUNT_RE = re.compile(r"^Found (\d+) (?:files?|matches?|lines?)", re.MULTILINE)


def project_too_large(content: str, *, tool: str) -> ProjectedResult | None:
    """Recognise the runtime's "result too large, saved to file" notice.

    The agent still reads the saved file, so this is not an error; the card
    just cannot show the rows. Returns None when the notice is absent.
    """
    match = _TOO_LARGE_RE.search(content or "")
    if not match:
        return None
    chars = int(match.group(1).replace(",", ""))
    projected = text_result(
        content,
        summary=f"Result too large to display ({format_count(chars)} chars) · saved for the agent",
    )
    projected.result = {
        "kind": "text",
        "too_large": True,
        "result_chars_reported": chars,
        "saved_path": match.group(2),
    }
    return projected


def _count_lines(text: str) -> int:
    return len([line for line in (text or "").splitlines() if line.strip()])


def _path_from_input(tool_input: dict[str, Any] | None, *keys: str) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    for key in keys:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _basename(path: str | None) -> str | None:
    if not path:
        return None
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or path


def project_builtin(base: str, content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    """Summaries for SDK builtins; the body stays the raw text."""
    text = content or ""
    if base == "Read":
        numbered = len(_CAT_N_RE.findall(text))
        lines = numbered or _count_lines(text)
        name = _basename(_path_from_input(tool_input, "file_path", "path", "notebook_path"))
        parts = [f"{format_count(lines)} line{'s' if lines != 1 else ''}"]
        if name:
            parts.append(name)
        return text_result(text, summary=" · ".join(parts))
    if base == "Glob":
        files = _count_lines(text) if not text.startswith("No files") else 0
        return text_result(text, summary=f"{format_count(files)} file{'s' if files != 1 else ''}")
    if base == "Grep":
        counted = _GREP_COUNT_RE.search(text)
        matches = int(counted.group(1)) if counted else (_count_lines(text) if not text.startswith("No ") else 0)
        return text_result(text, summary=f"{format_count(matches)} match{'es' if matches != 1 else ''}")
    if base in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        name = _basename(_path_from_input(tool_input, "file_path", "path", "notebook_path"))
        verb = "Wrote" if base == "Write" else "Edited"
        return text_result(text, summary=f"{verb} {name}" if name else f"{verb} a file")
    if base == "TodoWrite":
        todos = tool_input.get("todos") if isinstance(tool_input, dict) else None
        if isinstance(todos, list) and todos:
            done = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "completed")
            return text_result(text, summary=f"Plan updated · {done}/{len(todos)} done")
        return text_result(text, summary="Plan updated")
    if base == "Skill":
        match = _SKILL_RE.search(text)
        name = match.group(1) if match else _path_from_input(tool_input, "skill", "name")
        return text_result(text, summary=f"Loaded {name}" if name else "Loaded a skill")
    if base == "ToolSearch":
        refs = [try_json(line) for line in text.splitlines() if line.strip()]
        names = [
            r.get("tool_name")
            for r in refs
            if isinstance(r, dict) and isinstance(r.get("tool_name"), str)
        ]
        if names:
            projected = text_result(text, summary=f"{format_count(len(names))} tool{'s' if len(names) != 1 else ''} loaded")
            projected.result = {"kind": "text", "tools": names[:50]}
            return projected
        return text_result(text, summary=first_line(text) or "Searched tools")
    if base == "WebSearch":
        return text_result(text, summary=f"{format_count(_count_lines(text))} result lines")
    if base == "WebFetch":
        return text_result(text, summary=f"Fetched {format_count(len(text))} chars")
    return text_result(text, summary=first_line(text) or f"{base} completed")
