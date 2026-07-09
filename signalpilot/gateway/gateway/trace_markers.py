"""Helpers for parseable worker control markers in chat traces."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

CONTROL_MARKERS_METADATA_KEY = "control_markers"
TRACE_CONTROL_MARKERS = ("PLAN", "PROGRESS", "FINAL_STATEMENT")


@dataclass(frozen=True)
class TraceMarker:
    marker: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class _MarkerMatch:
    marker: str
    payload: dict[str, Any]
    start: int
    end: int


def redact_trace_control_markers(
    content: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Move parseable control markers from visible content into metadata."""
    matches = _find_marker_matches(content)
    if not matches:
        return content, metadata

    redacted = _redact_matches(content, matches)
    next_metadata = dict(metadata or {})
    existing = next_metadata.get(CONTROL_MARKERS_METADATA_KEY)
    markers = list(existing) if isinstance(existing, list) else []
    markers.extend(
        {"marker": match.marker, "payload": match.payload}
        for match in matches
    )
    next_metadata[CONTROL_MARKERS_METADATA_KEY] = markers
    return redacted, next_metadata


def iter_trace_marker_payloads(
    content: str,
    metadata: dict[str, Any] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Return marker payloads from metadata first, then legacy inline content."""
    payloads: list[tuple[str, dict[str, Any]]] = []
    if isinstance(metadata, dict):
        raw_markers = metadata.get(CONTROL_MARKERS_METADATA_KEY)
        if isinstance(raw_markers, list):
            for item in raw_markers:
                if not isinstance(item, dict):
                    continue
                marker = _normalize_marker(item.get("marker"))
                payload = item.get("payload")
                if marker and isinstance(payload, dict):
                    payloads.append((marker, payload))

    payloads.extend((match.marker, match.payload) for match in _find_marker_matches(content))
    return payloads


def _find_marker_matches(content: str) -> list[_MarkerMatch]:
    if not content:
        return []
    decoder = json.JSONDecoder()
    matches: list[_MarkerMatch] = []
    marker_pattern = "|".join(re.escape(marker) for marker in TRACE_CONTROL_MARKERS)
    for match in re.finditer(
        rf"(?m)^[ \t]*(?P<wrapper>\*\*)?(?P<marker>{marker_pattern})[ \t]*:[ \t]*",
        content,
    ):
        marker = _normalize_marker(match.group("marker"))
        if marker is None:
            continue
        remainder = content[match.end() :]
        stripped = remainder.lstrip()
        offset = len(remainder) - len(stripped)
        try:
            parsed, json_end = decoder.raw_decode(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        end = _extend_to_marker_line_end(
            content,
            match.end() + offset + json_end,
            closing_wrapper=match.group("wrapper"),
        )
        matches.append(_MarkerMatch(marker=marker, payload=parsed, start=match.start(), end=end))
    matches.sort(key=lambda item: item.start)
    return _drop_overlapping(matches)


def _redact_matches(content: str, matches: list[_MarkerMatch]) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in matches:
        pieces.append(content[cursor : match.start])
        cursor = match.end
    pieces.append(content[cursor:])
    return re.sub(r"\n{3,}", "\n\n", "".join(pieces)).strip()


def _extend_to_marker_line_end(
    content: str,
    end: int,
    *,
    closing_wrapper: str | None = None,
) -> int:
    cursor = end
    while cursor < len(content) and content[cursor] in " \t":
        cursor += 1
    if closing_wrapper and content.startswith(closing_wrapper, cursor):
        cursor += len(closing_wrapper)
        while cursor < len(content) and content[cursor] in " \t":
            cursor += 1
    if cursor < len(content) and content[cursor] == "\r":
        cursor += 1
        if cursor < len(content) and content[cursor] == "\n":
            cursor += 1
    elif cursor < len(content) and content[cursor] == "\n":
        cursor += 1
    return cursor


def _drop_overlapping(matches: list[_MarkerMatch]) -> list[_MarkerMatch]:
    result: list[_MarkerMatch] = []
    last_end = -1
    for match in matches:
        if match.start < last_end:
            continue
        result.append(match)
        last_end = match.end
    return result


def _normalize_marker(value: Any) -> str | None:
    marker = str(value or "").strip().upper()
    return marker if marker in TRACE_CONTROL_MARKERS else None
