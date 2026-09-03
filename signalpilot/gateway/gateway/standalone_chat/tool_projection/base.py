"""Projection result type shared by every tool projector."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gateway.standalone_chat.tool_projection.limits import RESULT_TEXT_MAX, SUMMARY_MAX
from gateway.standalone_chat.tool_projection.text import clip


@dataclass
class ProjectedResult:
    """What ``tool_completed`` carries for one tool call.

    ``result`` always has a ``kind`` (see the wire contract in
    ``web/lib/api/standalone-chat.ts``). ``result_text`` is the capped raw
    text; ``result_chars`` the full length before any cap.
    """

    summary: str
    result: dict[str, Any] = field(default_factory=lambda: {"kind": "text"})
    result_text: str | None = None
    result_chars: int | None = None
    truncated: bool = False


def build(
    result: dict[str, Any],
    *,
    summary: str,
    text: str,
    result_chars: int | None = None,
    truncated: bool = False,
    include_text: bool = True,
) -> ProjectedResult:
    """Assemble a ``ProjectedResult`` with the shared caps applied."""
    clipped_text, text_cut = clip(text, RESULT_TEXT_MAX)
    headline = " ".join(summary.split()) or "The tool completed."
    if len(headline) > SUMMARY_MAX:
        headline = headline[: SUMMARY_MAX - 1] + "…"
    return ProjectedResult(
        summary=headline,
        result=result,
        result_text=clipped_text if include_text else None,
        result_chars=result_chars if result_chars is not None else len(text),
        truncated=truncated or text_cut,
    )


def text_result(text: str, *, summary: str, result_chars: int | None = None) -> ProjectedResult:
    return build({"kind": "text"}, summary=summary, text=text, result_chars=result_chars)
