"""Structured planning for follow-ups on existing HTML deliverables."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

FollowupMode = Literal["edit_existing", "refresh_data", "clarify"]


@dataclass(frozen=True)
class DeliverableFollowupPlan:
    mode: FollowupMode
    requires_ephemeral_run: bool
    data_instruction: str
    render_instruction: str
    response: str | None = None


_REFRESH_RE = re.compile(
    r"\b(refresh|rerun|re-run|reload|recompute|recalculate|latest|fresh|new data|up-to-date|update data)\b",
    flags=re.I,
)
_EDIT_RE = re.compile(
    r"\b(make|change|edit|update|rename|switch|convert|show|hide|add|remove|replace|use|chart|table|bar|line|title|layout|color|sort|filter)\b",
    flags=re.I,
)
_DIRECT_RE = re.compile(r"^(hi|hello|hey|thanks?|thank you|ok|okay|cool)[.! ]*$", flags=re.I)


def plan_deliverable_followup(prompt: str) -> DeliverableFollowupPlan:
    text = re.sub(r"\s+", " ", prompt or "").strip()
    if not text or _DIRECT_RE.fullmatch(text):
        return DeliverableFollowupPlan(
            mode="clarify",
            requires_ephemeral_run=False,
            data_instruction="",
            render_instruction="",
            response=(
                "Tell me whether to refresh this dashboard/report with fresh data, "
                "edit the current presentation, or both."
            ),
        )

    wants_refresh = bool(_REFRESH_RE.search(text))
    wants_edit = bool(_EDIT_RE.search(text))
    if wants_refresh:
        render_instruction = (
            f"Apply this requested presentation/content change after refreshing the data: {text}"
            if wants_edit
            else "Preserve the existing title, layout, chart types, section order, and copy; replace only the data-backed values."
        )
        return DeliverableFollowupPlan(
            mode="refresh_data",
            requires_ephemeral_run=True,
            data_instruction=(
                "Refresh the underlying governed data for the existing SignalPilot deliverable "
                f"using the immutable original notebook context. User follow-up: {text}"
            ),
            render_instruction=render_instruction,
        )

    if wants_edit:
        return DeliverableFollowupPlan(
            mode="edit_existing",
            requires_ephemeral_run=False,
            data_instruction="",
            render_instruction=f"Edit the existing dashboard/report without rerunning analysis. User follow-up: {text}",
        )

    return DeliverableFollowupPlan(
        mode="clarify",
        requires_ephemeral_run=False,
        data_instruction="",
        render_instruction="",
        response=(
            "I can update this dashboard/report, but I need a concrete change. "
            "For example: refresh it with latest data, or change a chart/table/title."
        ),
    )
