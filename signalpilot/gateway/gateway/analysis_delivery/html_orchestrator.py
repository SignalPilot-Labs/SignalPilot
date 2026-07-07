"""Render static HTML dashboards/reports from governed analysis packets."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from gateway.string_utils import string_value as _string

from .renderer import DEFAULT_DELIVERY_MODEL
from .trace_loader import DeliveryPacket

LOGGER = logging.getLogger(__name__)

_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_TIMEOUT_SECONDS = 90.0

HtmlKind = Literal["report", "dashboard"]
SnapshotFetcher = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class HtmlDeliverableResult:
    kind: HtmlKind
    title: str
    html: str
    data_json: dict | list | str | int | float | bool | None = None
    report_id: str | None = None


class HtmlOrchestrator:
    def __init__(
        self,
        *,
        provider: str = "anthropic",
        model: str | None = None,
        timeout_seconds: float | None = None,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        fetch_snapshot: SnapshotFetcher | None = None,
    ) -> None:
        self.provider = (provider or "anthropic").strip().lower()
        self.model = (model or os.getenv("SIGNALPILOT_ORCHESTRATOR_MODEL") or DEFAULT_DELIVERY_MODEL).strip()
        self.timeout_seconds = _timeout_seconds(timeout_seconds)
        self.api_key = api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY")
        self._http_client = http_client
        self._fetch_snapshot = fetch_snapshot

    async def render(self, packet: DeliveryPacket) -> HtmlDeliverableResult:
        if self.provider != "anthropic" or not self.model or not self.api_key:
            raise RuntimeError("HTML orchestrator is not configured")
        return await self._anthropic_render(packet)

    async def _anthropic_render(self, packet: DeliveryPacket) -> HtmlDeliverableResult:
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": json.dumps(
                    _html_model_payload(packet),
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
            }
        ]
        for _ in range(4):
            response = await self._anthropic_request(messages)
            content = response.get("content") or []
            result = await self._result_from_content(packet, content)
            if result is not None:
                return result
            tool_results = await self._tool_results(packet, content)
            if not tool_results:
                text = _anthropic_text(response)
                parsed = _parse_json_object(text)
                result = _html_result_from_payload(parsed)
                if result is not None:
                    return result
                raise ValueError("HTML orchestrator did not return a deliverable")
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": tool_results})
        raise TimeoutError("HTML orchestrator exceeded tool loop limit")

    async def _anthropic_request(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        request_body = {
            "model": self.model,
            "max_tokens": 8192,
            "temperature": 0,
            "system": _html_orchestrator_system_prompt(),
            "tools": _html_tools(),
            "messages": messages,
        }
        headers = {
            "x-api-key": self.api_key or "",
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        if self._http_client is not None:
            response = await self._http_client.post(_ANTHROPIC_MESSAGES_URL, headers=headers, json=request_body)
            response.raise_for_status()
            return response.json()
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(_ANTHROPIC_MESSAGES_URL, headers=headers, json=request_body)
            response.raise_for_status()
            return response.json()

    async def _result_from_content(
        self,
        packet: DeliveryPacket,
        content: list[Any],
    ) -> HtmlDeliverableResult | None:
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            name = _string(item.get("name"))
            args = _tool_args_dict(item)
            if args is None:
                return None
            if name in {"create_dashboard", "create_report", "edit_dashboard", "edit_report"}:
                return _html_result_from_tool(name, args)
            if name == "fetch_snapshot":
                continue
        text = "\n".join(
            _string(item.get("text")) for item in content if isinstance(item, dict) and item.get("type") == "text"
        ).strip()
        if not text:
            return None
        try:
            return _html_result_from_payload(_parse_json_object(text))
        except Exception:
            LOGGER.debug("HTML orchestrator text was not final JSON")
            return None

    async def _tool_results(
        self,
        packet: DeliveryPacket,
        content: list[Any],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            tool_use_id = _string(item.get("id"))
            name = _string(item.get("name"))
            args = _tool_args_dict(item)
            if not tool_use_id or args is None:
                continue
            if name == "fetch_snapshot":
                tool_result = await self._fetch_snapshot_result(packet, args)
            else:
                tool_result = {"ok": True}
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": json.dumps(tool_result, ensure_ascii=True),
                }
            )
        return results

    async def _fetch_snapshot_result(
        self,
        packet: DeliveryPacket,
        args: dict[str, Any],
    ) -> Any:
        snapshot = _find_snapshot(packet, args)
        if snapshot is None:
            return {"error": "snapshot not found"}
        if self._fetch_snapshot is None:
            return snapshot
        return await self._fetch_snapshot(snapshot)


async def render_html_deliverable(
    packet: DeliveryPacket,
    *,
    api_key: str | None = None,
    orchestrator: HtmlOrchestrator | None = None,
    fetch_snapshot: SnapshotFetcher | None = None,
) -> HtmlDeliverableResult:
    if orchestrator is not None:
        return await orchestrator.render(packet)
    return await HtmlOrchestrator(api_key=api_key, fetch_snapshot=fetch_snapshot).render(packet)


def _html_model_payload(packet: DeliveryPacket) -> dict[str, Any]:
    outputs = packet.final_notebook_outputs
    statement = packet.final_statement.statement if packet.final_statement else ""
    return {
        "userRequest": packet.user_request,
        "answer": statement
        or _string(outputs.get("finalAnswer") or outputs.get("final_answer"))
        or _string(outputs.get("summary")),
        "summary": _string(outputs.get("summary")),
        "dataSnapshots": packet.data_snapshots,
        "charts": packet.charts,
    }


def _timeout_seconds(value: float | None) -> float:
    if value is not None:
        return max(float(value), 0.1)
    raw = os.getenv("SIGNALPILOT_ORCHESTRATOR_TIMEOUT_SECONDS", "").strip()
    if raw:
        try:
            return max(float(raw), 0.1)
        except ValueError:
            LOGGER.warning("Invalid SIGNALPILOT_ORCHESTRATOR_TIMEOUT_SECONDS=%r; using default", raw)
    return _DEFAULT_TIMEOUT_SECONDS


def _html_orchestrator_system_prompt() -> str:
    return (
        "You create one complete self-contained inline HTML document for a SignalPilot "
        "Notion deliverable. Choose dashboard or report from the user's ask and the "
        "available snapshot data. Use only supplied packet facts and snapshot data. "
        "Do not use CDNs, external fonts, external scripts, remote images, or network "
        "requests. Embed the data used by the page inside "
        '<script type="application/json" id="sp-data">...</script>. Return the '
        "deliverable by calling create_dashboard or create_report with title, html, "
        "and data_json. If editing, call edit_dashboard or edit_report. The HTML must "
        "not include confidence score, caveats, methodology, audit notes, trail links, "
        "handoff notes, source-query commentary, or internal execution language."
    )


def _html_tools() -> list[dict[str, Any]]:
    data_json_schema = {
        "type": "object",
        "description": "Structured data embedded in the HTML data island",
        "additionalProperties": True,
    }
    return [
        {
            "name": "create_dashboard",
            "description": "Return a complete static HTML dashboard deliverable.",
            "input_schema": _deliverable_tool_schema(data_json_schema, require_data=True),
        },
        {
            "name": "create_report",
            "description": "Return a complete static HTML report deliverable.",
            "input_schema": _deliverable_tool_schema(data_json_schema, require_data=False),
        },
        {
            "name": "edit_dashboard",
            "description": "Return edited complete static HTML dashboard content.",
            "input_schema": _deliverable_tool_schema(data_json_schema, require_data=False, include_id=True),
        },
        {
            "name": "edit_report",
            "description": "Return edited complete static HTML report content.",
            "input_schema": _deliverable_tool_schema(data_json_schema, require_data=False, include_id=True),
        },
        {
            "name": "fetch_snapshot",
            "description": "Fetch one saved data snapshot by name or URL before rendering.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                },
            },
        },
    ]


def _deliverable_tool_schema(
    data_json_schema: dict[str, Any],
    *,
    require_data: bool,
    include_id: bool = False,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "title": {"type": "string"},
        "html": {"type": "string"},
        "data_json": data_json_schema,
    }
    required = ["title", "html"]
    if require_data:
        required.append("data_json")
    if include_id:
        properties["report_id"] = {"type": "string"}
    return {"type": "object", "properties": properties, "required": required}


def _tool_args_dict(item: dict[str, Any]) -> dict[str, Any] | None:
    args = item.get("input")
    return args if isinstance(args, dict) else None


def _html_result_from_tool(name: str, args: dict[str, Any]) -> HtmlDeliverableResult | None:
    kind: HtmlKind = "dashboard" if "dashboard" in name else "report"
    title = _string(args.get("title")).strip()
    html = _string(args.get("html")).strip()
    if not title or not html:
        return None
    data_json = args.get("data_json", args.get("dataJson"))
    return HtmlDeliverableResult(
        kind=kind,
        title=title,
        html=html,
        data_json=data_json,
        report_id=_string(args.get("report_id") or args.get("reportId")).strip() or None,
    )


def _html_result_from_payload(payload: dict[str, Any]) -> HtmlDeliverableResult | None:
    kind_raw = _string(payload.get("kind")).strip().lower()
    kind: HtmlKind = "dashboard" if kind_raw == "dashboard" else "report"
    title = _string(payload.get("title")).strip()
    html = _string(payload.get("html")).strip()
    if not title or not html:
        return None
    return HtmlDeliverableResult(
        kind=kind,
        title=title,
        html=html,
        data_json=payload.get("dataJson", payload.get("data_json")),
        report_id=_string(payload.get("reportId", payload.get("report_id"))).strip() or None,
    )


def _find_snapshot(packet: DeliveryPacket, args: dict[str, Any]) -> dict[str, Any] | None:
    name = _string(args.get("name")).strip()
    url = _string(args.get("url")).strip()
    for snapshot in packet.data_snapshots:
        if name and _string(snapshot.get("name")).strip() == name:
            return snapshot
        if url and _string(snapshot.get("url")).strip() == url:
            return snapshot
    return None


def _anthropic_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in data.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(parts).strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    stripped = text.strip()
    if stripped.startswith("{"):
        parsed, _ = decoder.raw_decode(stripped)
        if isinstance(parsed, dict):
            return parsed
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("HTML orchestrator did not return a JSON object")
