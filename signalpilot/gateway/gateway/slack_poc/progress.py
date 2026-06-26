"""Slack progress reporting for notebook-backed analysis."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gateway.store import chat_traces

LOGGER = logging.getLogger(__name__)

INITIAL_PROGRESS_TEXT = "Analyzing your request..."
COMPLETING_PROGRESS_TEXT = "Generating the final answer..."
FALLBACK_PROGRESS_TEXT = "Working through the analysis..."

_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_MAX_RECENT_EVENTS = 12
_SAFE_TEXT_LIMIT = 180

_SIGNAL_ORDER = [
    "notebook_inspected",
    "notebook_edited",
    "runs_notebook_cells",
    "notebook_error",
    "uses_sp_connections",
    "connects_to_fin-db",
    "contains_db_query",
    "reads_dbt_project",
    "uses_dbt_marts",
    "builds_charts",
    "validates_notebook",
    "generates_final_answer",
]


@dataclass(frozen=True)
class ProgressSummary:
    status_text: str
    should_update: bool


class SlackProgressSummarizer:
    """Summarize sanitized trace activity into one Slack-safe status line."""

    def __init__(
        self,
        *,
        provider: str = "anthropic",
        model: str | None = None,
        timeout_seconds: float = 8.0,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider = (provider or "anthropic").strip().lower()
        self.model = (model or "").strip()
        self.timeout_seconds = max(float(timeout_seconds or 8.0), 0.1)
        self.api_key = api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY")
        self._http_client = http_client

    async def summarize(self, payload: dict[str, Any]) -> ProgressSummary:
        if self.provider != "anthropic" or not self.model or not self.api_key:
            return _no_progress_update(payload)
        try:
            summary = await self._anthropic_summary(payload)
        except Exception as exc:
            LOGGER.info("Slack progress model unavailable; skipping progress update: %s", exc)
            return _no_progress_update(payload)
        if summary is None:
            return _no_progress_update(payload)
        if _is_generic_status(summary.status_text) and _payload_has_status_hints(payload):
            retry_payload = {
                **payload,
                "rejectedStatusText": summary.status_text,
                "statusInstruction": (
                    "The rejectedStatusText was too generic. Return a more specific status from recentEvents.safeText, "
                    "recentEvents.objects, observedObjects, or the best statusHints example. If no concrete current work "
                    "is visible, return previousStatus with shouldUpdate false."
                ),
            }
            try:
                retry_summary = await self._anthropic_summary(retry_payload)
            except Exception as exc:
                LOGGER.info("Slack progress model retry unavailable; skipping progress update: %s", exc)
                retry_summary = None
            if retry_summary is not None and not _is_generic_status(retry_summary.status_text):
                return retry_summary
            LOGGER.info("Slack progress model stayed generic; skipping deterministic fallback")
            return _no_progress_update(payload)
        return summary

    async def _anthropic_summary(self, payload: dict[str, Any]) -> ProgressSummary | None:
        request_body = {
            "model": self.model,
            "max_tokens": 80,
            "temperature": 0,
            "system": _progress_system_prompt(),
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                }
            ],
        }
        headers = {
            "x-api-key": self.api_key or "",
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        if self._http_client is not None:
            response = await self._http_client.post(_ANTHROPIC_MESSAGES_URL, headers=headers, json=request_body)
            response.raise_for_status()
            data = response.json()
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(_ANTHROPIC_MESSAGES_URL, headers=headers, json=request_body)
                response.raise_for_status()
                data = response.json()

        raw_text = _anthropic_text(data)
        if not raw_text:
            LOGGER.info("Slack progress model returned empty content")
            return None
        parsed = _parse_model_json(raw_text)
        if parsed is None:
            LOGGER.info("Slack progress model returned non-JSON content: %s", raw_text[:200])
            return None
        status_text = _safe_model_status_text(parsed.get("statusText"))
        should_update = parsed.get("shouldUpdate")
        if status_text is None or not isinstance(should_update, bool):
            LOGGER.info("Slack progress model returned invalid status payload: %s", raw_text[:300])
            return None
        previous_status = _string(payload.get("previousStatus"))
        LOGGER.info(
            "Slack progress AI status=%r should_update=%s hints=%s objects=%s",
            status_text,
            should_update,
            payload.get("statusHints") if isinstance(payload.get("statusHints"), list) else [],
            payload.get("observedObjects") if isinstance(payload.get("observedObjects"), list) else [],
        )
        return ProgressSummary(status_text=status_text, should_update=should_update and status_text != previous_status)

    def _deterministic_summary(self, payload: dict[str, Any]) -> ProgressSummary:
        hint_summary = _summary_from_status_hints(payload)
        if hint_summary is not None:
            return hint_summary
        previous_status = _string(payload.get("previousStatus"))
        signals = set(payload.get("observedSignals") if isinstance(payload.get("observedSignals"), list) else [])
        recent_events = payload.get("recentEvents") if isinstance(payload.get("recentEvents"), list) else []
        recent_signals = {
            _string(signal)
            for event in recent_events
            if isinstance(event, dict) and isinstance(event.get("signals"), list)
            for signal in event.get("signals", [])
        }
        active_signals = recent_signals or signals
        recent_objects = [
            _string(value)
            for event in recent_events
            if isinstance(event, dict) and isinstance(event.get("objects"), list)
            for value in event.get("objects", [])
            if _string(value)
        ]
        table_ref = _first_object(recent_objects, _is_table_ref)
        connection = _first_object(recent_objects, _is_connection_name)
        dbt_model = _first_object(recent_objects, _is_dbt_model_path)
        recent_tool_names = {
            _string(event.get("toolName"))
            for event in recent_events
            if isinstance(event, dict) and _string(event.get("toolName"))
        }
        status_text = FALLBACK_PROGRESS_TEXT
        if "generates_final_answer" in active_signals:
            status_text = "Generating the final answer..."
        elif "builds_charts" in active_signals:
            chart = _best_chart_label(recent_objects)
            status_text = f"Building {_format_chart_label(chart)}..." if chart else "Building charts..."
        elif "contains_db_query" in active_signals:
            if table_ref:
                status_text = f"Querying {table_ref}..."
            elif connection:
                status_text = f"Querying {connection}..."
            else:
                status_text = "Querying database..."
        elif "uses_dbt_marts" in active_signals:
            status_text = "Finding mart models..."
        elif "reads_dbt_project" in active_signals:
            status_text = f"Reading {dbt_model}..." if dbt_model else "Finding dbt models..."
        elif "connects_to_fin-db" in active_signals or "uses_sp_connections" in active_signals:
            status_text = f"Checking {connection}..." if connection else "Checking data connections..."
        elif "runs_notebook_cells" in active_signals or any("run_cells" in name for name in recent_tool_names):
            status_text = "Running notebook cells..."
        elif "notebook_edited" in active_signals:
            status_text = "Writing analysis steps..."
        elif "notebook_inspected" in active_signals:
            status_text = "Inspecting the notebook..."
        return ProgressSummary(status_text=status_text, should_update=status_text != previous_status)


class SlackProgressReporter:
    """Poll gateway chat traces and edit one Slack progress message."""

    def __init__(
        self,
        *,
        slack: Any,
        session_factory: async_sessionmaker[AsyncSession],
        org_id: str,
        user_id: str,
        thread_id: str,
        source_prompt: str,
        channel_id: str,
        message_ts: str,
        interval_seconds: float = 15.0,
        summarizer: SlackProgressSummarizer | None = None,
        initial_status: str = INITIAL_PROGRESS_TEXT,
    ) -> None:
        self.slack = slack
        self.session_factory = session_factory
        self.org_id = org_id
        self.user_id = user_id or "slack-progress"
        self.thread_id = thread_id
        self.source_prompt = source_prompt
        self.channel_id = channel_id
        self.message_ts = message_ts
        self.interval_seconds = max(float(interval_seconds or 15.0), 0.1)
        self.summarizer = summarizer or SlackProgressSummarizer()
        self.previous_status = initial_status
        self._started_monotonic = time.monotonic()
        self._started_wall_time = time.time()
        self._observed_signals: set[str] = set()
        self._observed_objects: list[str] = []
        self._last_index = -1

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.interval_seconds)
                continue
            except TimeoutError:
                pass
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.info("Slack progress reporter tick failed: %s", exc, exc_info=True)

    async def _tick(self) -> None:
        events = await self._fetch_events()
        if not events:
            return
        self._last_index = max(int(_event_get(event, "idx", -1) or -1) for event in events)
        new_signals = extract_progress_signals(events)
        self._observed_signals.update(new_signals)
        recent_events = sanitize_trace_events(events, started_at=self._started_wall_time)
        for value in [
            _string(value)
            for event in recent_events
            if isinstance(event, dict) and isinstance(event.get("objects"), list)
            for value in event.get("objects", [])
        ]:
            _append_safe_object(self._observed_objects, value, 12, allow_label=True)
        if not recent_events and not new_signals:
            return
        payload = {
            "sourcePrompt": sanitize_source_prompt(self.source_prompt),
            "elapsedSeconds": round(time.monotonic() - self._started_monotonic, 2),
            "previousStatus": self.previous_status,
            "runStatus": "Analyzing",
            "recentEvents": recent_events,
            "observedSignals": [signal for signal in _SIGNAL_ORDER if signal in self._observed_signals],
            "observedObjects": self._observed_objects[-12:],
        }
        payload["statusHints"] = build_status_hints(payload)
        LOGGER.info(
            "Slack progress payload thread_id=%s previous=%r signals=%s objects=%s hints=%s events=%s",
            self.thread_id,
            self.previous_status,
            payload["observedSignals"],
            payload["observedObjects"],
            payload["statusHints"],
            _events_for_progress_log(recent_events),
        )
        summary = await self.summarizer.summarize(payload)
        if not summary.should_update or summary.status_text == self.previous_status:
            return
        try:
            await self.slack.update_message(
                channel=self.channel_id,
                ts=self.message_ts,
                text=summary.status_text,
            )
        except Exception as exc:
            LOGGER.info("Could not update Slack progress message: %s", exc, exc_info=True)
            return
        self.previous_status = summary.status_text

    async def _fetch_events(self) -> list[Any]:
        try:
            async with self.session_factory() as db:
                return await chat_traces.get_events(
                    db,
                    org_id=self.org_id,
                    user_id=self.user_id,
                    thread_id=self.thread_id,
                    after_index=self._last_index,
                )
        except ValueError:
            return []


def sanitize_trace_events(
    events: list[Any] | tuple[Any, ...],
    *,
    started_at: float | None = None,
    max_events: int = _MAX_RECENT_EVENTS,
) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    if not events:
        return sanitized
    event_list = list(events)[-max_events:]
    base_time = started_at
    if base_time is None:
        event_times = [
            float(value)
            for event in event_list
            if isinstance((value := _event_get(event, "created_at")), int | float)
        ]
        base_time = min(event_times) if event_times else None

    for event in event_list:
        event_type = _string(_event_get(event, "type")).strip()
        tool_name = _string(_event_get(event, "tool_name")).strip()
        item: dict[str, Any] = {
            "idx": int(_event_get(event, "idx", -1) or -1),
            "type": event_type,
        }
        elapsed = _elapsed_seconds(event, base_time)
        if elapsed is not None:
            item["elapsedSeconds"] = elapsed
        signals = extract_progress_signals([event])
        objects = extract_progress_objects([event])
        if event_type == "tool_use" and tool_name:
            item["toolName"] = tool_name
            if signals:
                item["signals"] = signals
            if objects:
                item["objects"] = objects
            sanitized.append(item)
            continue
        if event_type in {"text", "thinking"}:
            safe_text = _safe_trace_text(_string(_event_get(event, "content")))
            if safe_text:
                item["safeText"] = safe_text
                if signals:
                    item["signals"] = signals
                if objects:
                    item["objects"] = objects
                sanitized.append(item)
            continue
        if event_type == "tool_result":
            safe_text = _safe_tool_result_text(_string(_event_get(event, "content")))
            if safe_text:
                item["safeText"] = safe_text
                if signals:
                    item["signals"] = signals
                if objects:
                    item["objects"] = objects
                sanitized.append(item)
    return sanitized


def extract_progress_signals(events: list[Any] | tuple[Any, ...]) -> list[str]:
    found: set[str] = set()
    for event in events:
        tool_name = _string(_event_get(event, "tool_name")).lower()
        content = _string(_event_get(event, "content"))
        tool_input = _event_get(event, "tool_input")
        input_text = _jsonish_text(tool_input)
        haystack = f"{tool_name}\n{content}\n{input_text}".lower()
        if "get_lightweight_cell_map" in haystack or "cell map" in haystack:
            found.add("notebook_inspected")
        if "edit_notebook" in haystack:
            found.add("notebook_edited")
        if "run_cells" in haystack:
            found.add("runs_notebook_cells")
        if (
            "multipledefinitionerror" in haystack
            or "transaction failed" in haystack
            or "notebook error" in haystack
            or "application/vnd.sp+error" in haystack
        ):
            found.add("notebook_error")
        if "sp.connect" in haystack or "sp.connections" in haystack:
            found.add("uses_sp_connections")
        if "fin-db" in haystack or "fin db" in haystack:
            found.add("connects_to_fin-db")
        if "db.query" in haystack or _looks_like_sql(haystack):
            found.add("contains_db_query")
        if "dbt_project.yml" in haystack or "profiles.yml" in haystack or "/models/" in haystack:
            found.add("reads_dbt_project")
        if "analytics_marts" in haystack or "fct_" in haystack or "dim_" in haystack or "dbt mart" in haystack:
            found.add("uses_dbt_marts")
        if "plotly" in haystack or "matplotlib" in haystack or "chart" in haystack or "notioncharts" in haystack:
            found.add("builds_charts")
        if "get_notebook_errors" in haystack or "has_errors" in haystack:
            found.add("validates_notebook")
        if "finalanswer" in haystack or "notioncomment" in haystack or "slackmessage" in haystack:
            found.add("generates_final_answer")
    return [signal for signal in _SIGNAL_ORDER if signal in found]


def extract_progress_objects(events: list[Any] | tuple[Any, ...], *, limit: int = 6) -> list[str]:
    found: list[str] = []
    for event in events:
        content = _redact_sensitive_text(_string(_event_get(event, "content")))
        tool_input = _redact_sensitive_text(_jsonish_text(_event_get(event, "tool_input")))
        haystack = f"{content}\n{tool_input}"

        for match in re.finditer(r"\bsp\.connect\(\s*\\*['\"]([^'\"\\]{1,80})\\*['\"]\s*\)", haystack, re.I):
            _append_safe_object(found, match.group(1), limit)

        for match in re.finditer(r"\b([A-Za-z_][\w]*\.[A-Za-z_][\w]*)\b", haystack):
            value = match.group(1)
            if _is_table_ref(value):
                _append_safe_object(found, value, limit)

        for match in re.finditer(r"(?<![\w/.-])((?:[\w.-]+/)*models/[\w./-]+\.sql)\b", haystack):
            value = match.group(1)
            model_index = value.find("models/")
            if model_index >= 0:
                _append_safe_object(found, value[model_index:], limit)

        for match in re.finditer(r"(?<![\\\w])build_([A-Za-z0-9_]{2,60})_chart\b", haystack, re.I):
            _append_safe_object(found, f"{match.group(1).replace('_', ' ')} chart", limit, allow_label=True)

        for match in re.finditer(r"(?<![\\\w])([A-Za-z0-9_]{2,60})_chart\b", haystack, re.I):
            if match.group(1).lower().startswith("build_"):
                continue
            _append_safe_object(found, f"{match.group(1).replace('_', ' ')} chart", limit, allow_label=True)

        for match in re.finditer(r"\.set_title\(\s*['\"]([^'\"]{3,100})['\"]", haystack, re.I):
            _append_safe_object(found, match.group(1), limit, allow_label=True)

        for match in re.finditer(r"savefig\(\s*['\"][^'\"]*/([^/'\"]{3,80})\.(?:png|jpg|jpeg|webp|svg)['\"]", haystack, re.I):
            label = match.group(1).replace("_", " ").replace("-", " ")
            _append_safe_object(found, f"{label} chart", limit, allow_label=True)

        for match in re.finditer(
            r"\b(?:for|around|about)\s+the\s+([A-Za-z][A-Za-z0-9&/ -]{2,80}?)\s+(?:chart|comparison|visualization)\b",
            haystack,
            re.I,
        ):
            _append_safe_object(found, f"{match.group(1).strip()} chart", limit, allow_label=True)

        if len(found) >= limit:
            break
    return found


def build_status_hints(payload: dict[str, Any], *, limit: int = 8) -> list[str]:
    hints: list[str] = []
    recent_events = payload.get("recentEvents") if isinstance(payload.get("recentEvents"), list) else []
    raw_observed_objects = payload.get("observedObjects")
    observed_objects = [
        _string(value)
        for value in (raw_observed_objects if isinstance(raw_observed_objects, list) else [])
        if _string(value)
    ]

    for event in recent_events:
        if not isinstance(event, dict):
            continue
        signals = set(event.get("signals") if isinstance(event.get("signals"), list) else [])
        objects = [
            _string(value)
            for value in event.get("objects", [])
            if isinstance(event.get("objects"), list) and _string(value)
        ]
        combined_objects = [value for value in observed_objects if value not in objects] + objects
        table = _first_object(combined_objects, _is_table_ref)
        connection = _first_object(combined_objects, _is_connection_name)
        chart = _best_chart_label(combined_objects)
        model_path = _first_object(combined_objects, _is_dbt_model_path)

        if "contains_db_query" in signals and table:
            _append_hint(hints, f"Querying {table}...", limit)
        if "contains_db_query" in signals and connection:
            _append_hint(hints, f"Querying {connection}...", limit)
        if "builds_charts" in signals and chart:
            _append_hint(hints, f"Building {_format_chart_label(chart)}...", limit)
        if "runs_notebook_cells" in signals and chart:
            _append_hint(hints, f"Rendering {_format_chart_label(chart)}...", limit)
        if "runs_notebook_cells" in signals and table:
            _append_hint(hints, f"Running {table} query...", limit)
        if "runs_notebook_cells" in signals and connection:
            _append_hint(hints, f"Running {connection} notebook cells...", limit)
        if "reads_dbt_project" in signals and model_path:
            _append_hint(hints, f"Reading {model_path}...", limit)
        if "uses_sp_connections" in signals and connection:
            _append_hint(hints, f"Connecting to {connection}...", limit)
        if "validates_notebook" in signals:
            _append_hint(hints, "Checking notebook errors...", limit)

        safe_text = _string(event.get("safeText")).lower()
        prose_chart = _chart_label_from_text(safe_text)
        if prose_chart:
            _append_hint(hints, f"Building {_format_chart_label(prose_chart)}...", limit)
        if ("run the entire notebook" in safe_text or "execute all queries" in safe_text) and chart:
            _append_hint(hints, f"Rendering {_format_chart_label(chart)}...", limit)
        if ("run the entire notebook" in safe_text or "execute all queries" in safe_text) and table:
            _append_hint(hints, f"Running {table} query...", limit)
        if "final json" in safe_text or "final response" in safe_text or "final answer" in safe_text:
            _append_hint(hints, "Generating the final answer...", limit)
        if "final error check" in safe_text or "remaining errors" in safe_text:
            _append_hint(hints, "Checking notebook errors...", limit)
        if "executive summary" in safe_text:
            _append_hint(hints, "Polishing executive summary...", limit)
        if "stale" in safe_text and "variable" in safe_text:
            _append_hint(hints, "Fixing stale variable definitions...", limit)
        if "multipledefinitionerror" in safe_text or "duplicate definition" in safe_text:
            duplicate_name = _duplicate_definition_name(safe_text)
            if duplicate_name:
                _append_hint(hints, f"Fixing duplicate {duplicate_name} definitions...", limit)
            else:
                _append_hint(hints, "Fixing duplicate notebook definitions...", limit)
        if "stale" in safe_text and ("cell" in safe_text or "kernel" in safe_text or "graph" in safe_text):
            _append_hint(hints, "Clearing stale notebook state...", limit)
        if "delete" in safe_text and "cell" in safe_text and ("recreate" in safe_text or "brand new" in safe_text):
            _append_hint(hints, "Recreating notebook cells...", limit)
        if "empty output" in safe_text or "suppresses the display" in safe_text or "last expression" in safe_text:
            _append_hint(hints, "Fixing markdown output rendering...", limit)
        if "renders correctly" in safe_text or "rendering correctly" in safe_text:
            _append_hint(hints, "Checking rendered markdown output...", limit)

        if len(hints) >= limit:
            break

    if not hints:
        for value in observed_objects[-4:]:
            if _is_table_ref(value):
                _append_hint(hints, f"Querying {value}...", limit)
            elif _is_chart_label(value):
                _append_hint(hints, f"Building {_format_chart_label(value)}...", limit)
    return hints


def sanitize_source_prompt(prompt: str) -> str:
    text = _redact_sensitive_text(" ".join(prompt.split()))
    if _looks_like_sql(text):
        return ""
    return _clip(text, _SAFE_TEXT_LIMIT)


def _progress_system_prompt() -> str:
    return (
        "Return strict JSON only with keys statusText and shouldUpdate. Do not wrap the JSON in Markdown fences. "
        "statusText must be one short present-tense sentence for a Slack progress update, usually 3-8 words. "
        "Prefer concrete micro-decisions from recentEvents.safeText, recentEvents.objects, observedObjects, and signals. "
        "Use statusHints only as fallback examples when they match the current recentEvents. Good statuses include "
        "'Querying private-equity-db...', 'Finding mart models...', 'Querying staging.fct_revenue...', "
        "'Building EBITDA chart...', 'Fixing duplicate sp definitions...', 'Clearing stale notebook state...', "
        "'Recreating markdown cells...', 'Checking rendered markdown output...', or 'Generating the final answer...'. "
        "When the current event is chart-related, name the chart/metric from recentEvents.objects or observedObjects. "
        "Avoid generic phrases such as 'Inspecting the notebook', 'Writing analysis steps', 'Running notebook cells', "
        "'Building charts', 'Querying database', or 'Working through the analysis' whenever statusHints or objects exist. "
        "Use only object names provided in the payload. Do not invent table names, connection names, findings, "
        "numbers, SQL, row counts, caveats, stack traces, or draft conclusions. "
        "If the payload only shows generic tool activity and no concrete current work, return previousStatus and shouldUpdate false."
    )


def _anthropic_text(data: dict[str, Any]) -> str:
    content = data.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def _parse_model_json(raw_text: str) -> dict[str, Any] | None:
    text = raw_text.strip()
    candidates = [text]
    candidates.extend(match.group(1).strip() for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text, re.I))
    object_text = _first_json_object(text)
    if object_text:
        candidates.append(object_text)

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _first_json_object(text: str) -> str:
    start = text.find("{")
    while start >= 0:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find("{", start + 1)
    return ""


def _no_progress_update(payload: dict[str, Any]) -> ProgressSummary:
    status_text = _string(payload.get("previousStatus")) or FALLBACK_PROGRESS_TEXT
    return ProgressSummary(status_text=status_text, should_update=False)


def _events_for_progress_log(events: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    logged: list[dict[str, Any]] = []
    for event in events[-limit:]:
        if not isinstance(event, dict):
            continue
        item: dict[str, Any] = {
            "idx": event.get("idx"),
            "type": event.get("type"),
        }
        for key in ("toolName", "signals", "objects"):
            if event.get(key):
                item[key] = event[key]
        safe_text = _string(event.get("safeText"))
        if safe_text:
            item["safeText"] = _clip(safe_text, 120)
        logged.append(item)
    return logged


def _safe_model_status_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.strip().split())
    if not text or len(text) > 140 or "\n" in value:
        return None
    if (
        _looks_like_raw_sql_status(text)
        or _looks_like_stack_trace(text)
        or _looks_like_result_or_answer(text)
        or _contains_numeric_finding(text)
    ):
        return None
    if _contains_sensitive_text(text):
        return None
    if not text.endswith((".", "...")):
        text += "..."
    return text


def _safe_trace_text(value: str) -> str:
    text = _redact_sensitive_text(" ".join(value.split()))
    if not text:
        return ""
    if _looks_like_json_blob(text) or _looks_like_sql(text) or _looks_like_stack_trace(text):
        return ""
    if _looks_like_result_or_answer(text) or _contains_numeric_finding(text):
        return ""
    return _clip(text, _SAFE_TEXT_LIMIT)


def _safe_tool_result_text(value: str) -> str:
    text = _redact_sensitive_text(" ".join(value.split()))
    if not text:
        return ""
    lower = text.lower()
    if "multipledefinitionerror" in lower:
        name = _duplicate_definition_name(text)
        if name:
            return f"Notebook error: MultipleDefinitionError for {name}"
        return "Notebook error: MultipleDefinitionError"
    if "transaction failed" in lower and "cell" in lower and "not found" in lower:
        return "Notebook edit failed: cell not found"
    if "has_errors" in lower:
        if re.search(r"has_errors[\"']?\s*[:=]\s*true", lower):
            return "Notebook still has errors"
        if re.search(r"has_errors[\"']?\s*[:=]\s*false", lower):
            return "Notebook errors cleared"
    if "timed_out" in lower and re.search(r"timed_out[\"']?\s*[:=]\s*true", lower):
        return "Notebook cell run timed out"
    return ""


def _duplicate_definition_name(text: str) -> str:
    match = re.search(r"multipledefinitionerror\(name=\\*['\"]?([A-Za-z_][\w]*)", text, re.I)
    if match:
        return match.group(1)
    match = re.search(r"multipledefinitionerror\s+for\s+([A-Za-z_][\w]*)", text, re.I)
    if match:
        return match.group(1)
    match = re.search(r"duplicate\s+[`'\"]?([A-Za-z_][\w]*)[`'\"]?\s+definitions?", text, re.I)
    if match:
        return match.group(1)
    return ""


def _redact_sensitive_text(text: str) -> str:
    text = re.sub(r"sk-ant-[A-Za-z0-9_-]+", "[secret]", text)
    text = re.sub(r"xox[abprs]-[A-Za-z0-9-]+", "[secret]", text)
    text = re.sub(r"(?i)\bpostgres(?:ql)?://\S+", "[database-url]", text)
    return re.sub(r"(?i)(api[_-]?key|token|password)\s*[:=]\s*[^\s,;]+", r"\1=[secret]", text)


def _contains_sensitive_text(text: str) -> bool:
    return bool(re.search(r"sk-ant-|xox[abprs]-|postgres(?:ql)?://|api[_-]?key\s*[:=]|password\s*[:=]", text, re.I))


def _looks_like_json_blob(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        return True
    return text.count("{") + text.count("[") >= 3 or '":' in text


def _looks_like_sql(text: str) -> bool:
    return bool(
        re.search(r"\b(select|with)\b[\s\S]{0,500}\b(from|join|where|group\s+by|order\s+by)\b", text, re.I)
        or re.search(r"\b(insert|update|delete|create|drop|alter)\b[\s\S]{0,300}\b(table|view|schema)\b", text, re.I)
        or "db.query(" in text
        or "analytics_marts." in text
        or "information_schema." in text
    )


def _looks_like_raw_sql_status(text: str) -> bool:
    return bool(
        re.search(r"\b(select|with)\b[\s\S]{0,300}\b(from|join|where|group\s+by|order\s+by)\b", text, re.I)
        or re.search(r"\b(insert|update|delete|create|drop|alter)\b[\s\S]{0,200}\b(table|view|schema)\b", text, re.I)
        or "db.query(" in text.lower()
        or "information_schema." in text.lower()
    )


def _looks_like_stack_trace(text: str) -> bool:
    return bool(re.search(r"traceback|exception|stack trace|file \"[^\"]+\", line \d+", text, re.I))


def _looks_like_result_or_answer(text: str) -> bool:
    return bool(
        re.search(r"finalanswer|notioncomment|slackmessage|confidencescore|notioncharts|gotchas", text, re.I)
        or re.search(r"signalpilot analysis complete|executive summary|bottom line|what i found", text, re.I)
        or re.search(r"data-initial-value|<sp-table|<table|<span class=", text, re.I)
    )


def _contains_numeric_finding(text: str) -> bool:
    if re.search(r"[$£€¥]\s*\d|\d+\s*%|\d{1,3}(,\d{3})+|\d+\.\d+", text):
        return True
    if re.search(r"\b(revenue|transfers?|customers?|rows?|count|total|sum)\b", text, re.I):
        return len(re.findall(r"\d+", text)) >= 2
    return False


def _append_hint(hints: list[str], value: str, limit: int) -> None:
    value = _safe_model_status_text(value) or ""
    if value and value not in hints and len(hints) < limit:
        hints.append(value)


def _summary_from_status_hints(payload: dict[str, Any]) -> ProgressSummary | None:
    raw_hints = payload.get("statusHints")
    if not isinstance(raw_hints, list):
        return None
    previous_status = _string(payload.get("previousStatus"))
    for value in raw_hints:
        status_text = _safe_model_status_text(value)
        if status_text and not _is_generic_status(status_text):
            return ProgressSummary(status_text=status_text, should_update=status_text != previous_status)
    return None


def _payload_has_status_hints(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("statusHints"), list) and bool(payload["statusHints"])


def _is_generic_status(text: str) -> bool:
    normalized = text.strip().rstrip(".").lower()
    return normalized in {
        "inspecting the notebook",
        "writing analysis steps",
        "running notebook cells",
        "building charts",
        "querying database",
        "checking data connections",
        "working through the analysis",
        "planning the analysis",
    }


def _first_object(values: list[str], predicate: Any) -> str:
    for value in reversed(values):
        if predicate(value):
            return value
    return ""


def _best_chart_label(values: list[str]) -> str:
    chart_values = [value for value in values if _is_chart_label(value)]
    for value in reversed(chart_values):
        if " " in value and any(char.isupper() for char in value):
            return value
    return chart_values[-1] if chart_values else ""


def _format_chart_label(value: str) -> str:
    label = " ".join(value.split())
    if not re.search(r"\b(chart|trend|comparison|visualization)\b", label, re.I):
        label = f"{label} chart"
    return label


def _chart_label_from_text(text: str) -> str:
    for pattern in (
        r"\b(?:for|around|about)\s+the\s+([a-z][a-z0-9&/ -]{2,80}?)\s+(?:chart|comparison|visualization)\b",
        r"\b(?:building|rendering|adding|creating)\s+(?:a\s+|the\s+)?([a-z][a-z0-9&/ -]{2,80}?)\s+(?:chart|comparison|visualization)\b",
    ):
        match = re.search(pattern, text, re.I)
        if match:
            return f"{match.group(1).strip()} chart"
    return ""


def _append_safe_object(found: list[str], value: str, limit: int, *, allow_label: bool = False) -> None:
    value = _normalize_progress_object(value, allow_label=allow_label)
    if value and value not in found and len(found) < limit:
        found.append(value)


def _normalize_progress_object(value: str, *, allow_label: bool = False) -> str:
    value = value.strip().strip("'\"`),;")
    if not value or len(value) > 100:
        return ""
    if _contains_sensitive_text(value) or "://" in value:
        return ""
    if allow_label:
        value = " ".join(value.split())
        if not re.fullmatch(r"[A-Za-z0-9_./@%&() -]+", value):
            return ""
        if _looks_like_sql(value) or _looks_like_result_or_answer(value) or _contains_numeric_finding(value):
            return ""
        return value
    if any(char.isspace() for char in value) or not re.fullmatch(r"[A-Za-z0-9_./@-]+", value):
        return ""
    return value


def _is_table_ref(value: str) -> bool:
    if value.lower().endswith(".sql"):
        return False
    if not re.fullmatch(r"[A-Za-z_][\w]*\.[A-Za-z_][\w]*", value):
        return False
    schema, table = value.split(".", 1)
    schema_lower = schema.lower()
    table_lower = table.lower()
    if schema_lower in {"http", "https", "www", "api", "slack"}:
        return False
    return (
        schema_lower in {"raw", "staging", "analytics", "analytics_marts", "marts", "intermediate", "portfolio", "public"}
        or table_lower.startswith(("fct_", "dim_", "stg_", "int_"))
        or table_lower.endswith(("_metrics", "_financials", "_companies", "_pipeline", "_initiatives", "_notes"))
    )


def _is_connection_name(value: str) -> bool:
    return bool("-" in value and "." not in value and "/" not in value and len(value) <= 80)


def _is_dbt_model_path(value: str) -> bool:
    return value.startswith("models/") and value.endswith(".sql")


def _is_chart_label(value: str) -> bool:
    lower = value.lower()
    if "chart" in lower or "trend" in lower or "comparison" in lower or "visualization" in lower:
        return True
    return " " in value and bool(
        re.search(r"\b(ebitda|revenue|arr|nrr|churn|margin|pipeline|financial|customer|retention)\b", lower)
    )


def _event_get(event: Any, key: str, default: Any = None) -> Any:
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default)


def _elapsed_seconds(event: Any, started_at: float | None) -> float | None:
    created_at = _event_get(event, "created_at")
    if started_at is None or not isinstance(created_at, int | float):
        return None
    return round(max(float(created_at) - float(started_at), 0.0), 2)


def _jsonish_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:50_000]
    try:
        return json.dumps(value, ensure_ascii=True, default=str)[:50_000]
    except TypeError:
        return str(value)[:50_000]


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 14].rstrip() + "... truncated"


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""
