"""Load worker-authored analysis trace signals for channel delivery."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.store import chat_traces
from gateway.string_utils import string_value as _string
from gateway.trace_markers import iter_trace_marker_payloads

ConfidenceLabel = Literal["high", "medium", "lower"]


@dataclass(frozen=True)
class WorkerPlan:
    steps: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorkerProgress:
    current_step: str = ""
    completed_steps: list[str] = field(default_factory=list)
    status: str = ""


@dataclass(frozen=True)
class FinalStatement:
    statement: str = ""
    confidence_score: ConfidenceLabel | None = None
    caveats: list[str] = field(default_factory=list)
    handoff_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DeliveryPacket:
    user_request: str = ""
    plan: WorkerPlan | None = None
    latest_progress: WorkerProgress | None = None
    final_statement: FinalStatement | None = None
    final_notebook_outputs: dict[str, Any] = field(default_factory=dict)
    charts: list[dict[str, Any]] = field(default_factory=list)
    data_snapshots: list[dict[str, Any]] = field(default_factory=list)
    trail_url: str = ""
    known_errors: list[str] = field(default_factory=list)
    status: str = "active"

    def to_model_payload(self) -> dict[str, Any]:
        return {
            "userRequest": self.user_request,
            "plan": asdict(self.plan) if self.plan else None,
            "latestProgress": asdict(self.latest_progress) if self.latest_progress else None,
            "finalStatement": asdict(self.final_statement) if self.final_statement else None,
            "finalNotebookOutputs": self.final_notebook_outputs,
            "charts": self.charts,
            "dataSnapshots": self.data_snapshots,
            "trailUrl": self.trail_url,
            "knownErrors": self.known_errors,
            "status": self.status,
        }


_GENERIC_REPAIR_TEXT = "Formatting the completed analysis into the required"


async def load_delivery_packet(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    thread_id: str,
    user_request: str = "",
    status_payload: dict[str, Any] | None = None,
    trail_url: str = "",
) -> DeliveryPacket:
    thread = await chat_traces.get_thread(
        session,
        org_id=org_id,
        user_id=user_id,
        thread_id=thread_id,
    )
    events = (
        await chat_traces.get_events(
            session,
            org_id=org_id,
            user_id=user_id,
            thread_id=thread_id,
            require_thread=False,
        )
        if thread
        else []
    )
    return load_delivery_packet_from_events(
        events,
        user_request=user_request,
        status_payload=status_payload,
        trail_url=trail_url,
        thread_status=thread.status if thread else None,
    )


def load_delivery_packet_from_events(
    events: list[Any],
    *,
    user_request: str = "",
    status_payload: dict[str, Any] | None = None,
    trail_url: str = "",
    thread_status: str | None = None,
) -> DeliveryPacket:
    plan: WorkerPlan | None = None
    plan_idx = -1
    progress: WorkerProgress | None = None
    progress_idx = -1
    final_statement: FinalStatement | None = None
    final_idx = -1
    known_errors: list[str] = []
    latest_result: dict[str, Any] = {}

    for event in events:
        idx = int(_event_get(event, "idx", -1) or -1)
        event_type = _string(_event_get(event, "type")).lower()
        content = _string(_event_get(event, "content"))
        metadata = _event_get(event, "metadata") or {}

        if not user_request and event_type == "user" and content:
            user_request = content

        if event_type in {"thinking", "thinking_delta"} or _GENERIC_REPAIR_TEXT in content:
            continue

        if bool(_event_get(event, "is_error")) or event_type == "error":
            _append_unique(known_errors, content.strip() or _string(_event_get(event, "tool_name")), 8)

        if event_type == "done" and isinstance(metadata, dict):
            result = metadata.get("result")
            if isinstance(result, dict):
                latest_result = result

        for marker, payload in iter_trace_marker_payloads(content, metadata):
            if marker == "PLAN" and idx >= plan_idx:
                parsed_plan = _parse_plan(payload)
                if parsed_plan is not None:
                    plan = parsed_plan
                    plan_idx = idx
            elif marker == "PROGRESS" and idx >= progress_idx:
                parsed_progress = _parse_progress(payload)
                if parsed_progress is not None:
                    progress = parsed_progress
                    progress_idx = idx
            elif marker == "FINAL_STATEMENT" and idx >= final_idx:
                parsed_final = _parse_final_statement(payload)
                if parsed_final is not None:
                    final_statement = parsed_final
                    final_idx = idx

    status_payload = status_payload or {}
    notebook_outputs = _compact_notebook_outputs(latest_result, status_payload)
    charts = _charts_from_sources(status_payload, latest_result)
    data_snapshots = _data_snapshots_from_sources(status_payload, latest_result)
    if status_payload.get("error"):
        _append_unique(known_errors, _string(status_payload.get("error")), 8)

    status = _status_from_sources(thread_status, status_payload, known_errors)
    return DeliveryPacket(
        user_request=user_request,
        plan=plan,
        latest_progress=progress,
        final_statement=final_statement,
        final_notebook_outputs=notebook_outputs,
        charts=charts,
        data_snapshots=data_snapshots,
        trail_url=trail_url or _string(status_payload.get("trailUrl") or status_payload.get("trail_url")),
        known_errors=known_errors,
        status=status,
    )


def _parse_plan(payload: dict[str, Any]) -> WorkerPlan | None:
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return None
    parsed = [_string(step).strip() for step in steps if _string(step).strip()]
    return WorkerPlan(steps=parsed) if parsed else None


def _parse_progress(payload: dict[str, Any]) -> WorkerProgress | None:
    current = _string(payload.get("currentStep", payload.get("current_step"))).strip()
    completed_raw = payload.get("completedSteps", payload.get("completed_steps", []))
    completed = (
        [_string(step).strip() for step in completed_raw if _string(step).strip()]
        if isinstance(completed_raw, list)
        else []
    )
    status = _string(payload.get("status")).strip()
    if not current and not completed and not status:
        return None
    return WorkerProgress(current_step=current, completed_steps=completed, status=status)


def _parse_final_statement(payload: dict[str, Any]) -> FinalStatement | None:
    statement = _string(payload.get("statement")).strip()
    caveats_raw = payload.get("caveats", [])
    notes_raw = payload.get("handoffNotes", payload.get("handoff_notes", []))
    confidence = _confidence_label(payload.get("confidenceScore", payload.get("confidence_score")))
    caveats = (
        [_string(item).strip() for item in caveats_raw if _string(item).strip()]
        if isinstance(caveats_raw, list)
        else []
    )
    notes = (
        [_string(item).strip() for item in notes_raw if _string(item).strip()] if isinstance(notes_raw, list) else []
    )
    if not statement and confidence is None and not caveats and not notes:
        return None
    return FinalStatement(
        statement=statement,
        confidence_score=confidence,
        caveats=caveats,
        handoff_notes=notes,
    )


def _compact_notebook_outputs(*sources: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    keys = (
        "summary",
        "finalAnswer",
        "final_answer",
        "gotchas",
        "analysisMethod",
        "analysis_method",
        "notionComment",
        "notion_comment",
    )
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value not in (None, "", []):
                result[key] = value
    return result


def _charts_from_sources(*sources: dict[str, Any]) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        raw_charts = source.get("notionCharts", source.get("notion_charts", []))
        if not isinstance(raw_charts, list):
            continue
        for chart in raw_charts:
            if not isinstance(chart, dict):
                continue
            url = _string(chart.get("url")).strip()
            title = _string(chart.get("title")).strip()
            key = url or title
            if not key or key in seen:
                continue
            seen.add(key)
            charts.append(dict(chart))
    return charts[:3]


def _data_snapshots_from_sources(*sources: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        raw_snapshots = source.get("dataSnapshots", source.get("data_snapshots", []))
        if not isinstance(raw_snapshots, list):
            continue
        for snapshot in raw_snapshots:
            if not isinstance(snapshot, dict):
                continue
            url = _string(snapshot.get("url")).strip()
            name = _string(snapshot.get("name")).strip()
            key = url or name
            if not key or key in seen:
                continue
            seen.add(key)
            snapshots.append(dict(snapshot))
    return snapshots[:5]


def _status_from_sources(
    thread_status: str | None,
    status_payload: dict[str, Any],
    known_errors: list[str],
) -> str:
    status = _string(status_payload.get("status")).lower()
    if status == "done" and not status_payload.get("error"):
        return "done"
    if status == "failed" or status_payload.get("error"):
        return "failed"
    if thread_status in {"done", "failed", "active"}:
        return thread_status
    return "failed" if known_errors else "active"


def _event_get(event: Any, key: str, default: Any = None) -> Any:
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default)


def _confidence_label(value: Any) -> ConfidenceLabel | None:
    if not isinstance(value, str):
        return None
    label = value.strip()
    if label in ("high", "medium", "lower"):
        return cast(ConfidenceLabel, label)
    return None


def _append_unique(items: list[str], value: str, limit: int) -> None:
    value = value.strip()
    if not value or value in items:
        return
    items.append(value)
    del items[limit:]
