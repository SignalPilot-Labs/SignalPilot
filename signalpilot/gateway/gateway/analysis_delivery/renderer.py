"""Render shared analysis delivery content from a trace loader packet."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from gateway.string_utils import string_value as _string

from .trace_loader import ConfidenceLabel, DeliveryPacket

LOGGER = logging.getLogger(__name__)

_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_DELIVERY_MODEL = "claude-sonnet-4-5-20250929"
_PLACEHOLDER_CHART_TITLE_RE = re.compile(
    r"(?:notebook\s+)?(?:chart|image|figure|visualization)(?:\s+\d+)?",
    flags=re.I,
)


@dataclass(frozen=True)
class DeliveryResult:
    summary: str = ""
    slack_message: str = ""
    notion_comment: str = ""
    final_answer: str = ""
    gotchas: list[str] = field(default_factory=list)
    analysis_method: str = ""
    notion_charts: list[dict[str, Any]] = field(default_factory=list)
    confidence_score: ConfidenceLabel | None = None


class DeliveryRenderer:
    def __init__(
        self,
        *,
        provider: str = "anthropic",
        model: str | None = None,
        timeout_seconds: float = 15.0,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider = (provider or "anthropic").strip().lower()
        self.model = (model or os.getenv("SIGNALPILOT_DELIVERY_MODEL") or DEFAULT_DELIVERY_MODEL).strip()
        self.timeout_seconds = max(float(timeout_seconds or 15.0), 0.1)
        self.api_key = api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY")
        self._http_client = http_client

    async def render(self, packet: DeliveryPacket) -> DeliveryResult:
        fallback = fallback_delivery(packet)
        if self.provider != "anthropic" or not self.model or not self.api_key:
            return fallback
        try:
            rendered = await self._anthropic_render(packet)
        except Exception:
            LOGGER.info(
                "Analysis delivery renderer unavailable; using FINAL_STATEMENT fallback "
                "model=%s packet_status=%s has_final_statement=%s",
                self.model,
                packet.status,
                packet.final_statement is not None,
                exc_info=True,
            )
            return fallback
        return rendered or fallback

    async def _anthropic_render(self, packet: DeliveryPacket) -> DeliveryResult | None:
        request_body = {
            "model": self.model,
            "max_tokens": 1400,
            "temperature": 0,
            "system": _delivery_system_prompt(),
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(packet.to_model_payload(), ensure_ascii=True, separators=(",", ":")),
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
        text = _anthropic_text(data)
        if not text:
            return None
        parsed = _parse_json_object(text)
        return _delivery_result_from_payload(parsed, packet)


async def render_delivery(
    packet: DeliveryPacket,
    *,
    renderer: DeliveryRenderer | None = None,
    api_key: str | None = None,
) -> DeliveryResult:
    if renderer is not None:
        return await renderer.render(packet)
    return await DeliveryRenderer(api_key=api_key).render(packet)


def fallback_delivery(packet: DeliveryPacket) -> DeliveryResult:
    statement = packet.final_statement.statement if packet.final_statement else ""
    notebook_outputs = packet.final_notebook_outputs
    fallback_text_raw = (
        statement
        or _string(notebook_outputs.get("finalAnswer") or notebook_outputs.get("final_answer"))
        or _string(notebook_outputs.get("summary"))
        or ("I could not complete the analysis." if packet.status == "failed" else "The analysis completed.")
    )
    fallback_text = _compact_bullet_answer(fallback_text_raw) or fallback_text_raw
    gotchas = list(packet.final_statement.caveats if packet.final_statement else [])
    for error in packet.known_errors:
        if error and error not in gotchas:
            gotchas.append(error)
    method = "; ".join(packet.final_statement.handoff_notes) if packet.final_statement else ""
    if not method:
        method = _string(notebook_outputs.get("analysisMethod") or notebook_outputs.get("analysis_method"))
    return DeliveryResult(
        summary=_clip(_string(notebook_outputs.get("summary")) or fallback_text, 500),
        slack_message=fallback_text,
        notion_comment=_clip(
            _string(notebook_outputs.get("notionComment") or notebook_outputs.get("notion_comment")) or fallback_text,
            1200,
        ),
        final_answer=_string(notebook_outputs.get("finalAnswer") or notebook_outputs.get("final_answer"))
        or fallback_text,
        gotchas=gotchas,
        analysis_method=method,
        notion_charts=[_clean_chart_labels(chart) for chart in packet.charts],
        confidence_score=packet.final_statement.confidence_score if packet.final_statement else None,
    )


def delivery_result_to_status(
    result: DeliveryResult,
    packet: DeliveryPacket,
    *,
    base_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = dict(base_status or {})
    status.update(
        {
            "status": "Done" if packet.status == "done" else status.get("status", "Done"),
            "summary": result.summary,
            "slackMessage": result.slack_message,
            "notionComment": result.notion_comment,
            "finalAnswer": result.final_answer,
            "gotchas": result.gotchas,
            "analysisMethod": result.analysis_method,
            "notionCharts": result.notion_charts,
        }
    )
    if result.confidence_score is not None:
        status["confidenceScore"] = result.confidence_score
    elif packet.final_statement and packet.final_statement.confidence_score is not None:
        status["confidenceScore"] = packet.final_statement.confidence_score
    if packet.trail_url:
        status["trailUrl"] = packet.trail_url
    return status


def _delivery_system_prompt() -> str:
    return (
        "You render SignalPilot analysis delivery copy from a JSON packet. "
        "Use only facts present in the packet. Do not add external facts, numbers, "
        "methodology, caveats, chart interpretations, or conclusions that are not in the packet. "
        "Preserve the worker's meaning. The user audits the final chat thread, so render "
        "slackMessage, notionComment, and finalAnswer as concise user-friendly Markdown bullets, "
        "not as one dense paragraph and never as raw FINAL_STATEMENT JSON. Prefer 3-6 bullets. "
        "Each bullet must be on its own line and must start with '- '. Split independent findings, "
        "metrics, comparisons, caveats, and dataset-scope notes into separate bullets. If the worker "
        "statement contains several sentences, do not keep them inside one bullet; turn the key "
        "sentences into separate bullets. Do not write paragraph-style bullets with multiple unrelated "
        "facts joined together. "
        "Use gotchas for caveats instead of burying them in the answer. Return only valid JSON with keys: "
        "summary, slackMessage, notionComment, finalAnswer, gotchas, analysisMethod, notionCharts. "
        "notionCharts must reuse packet chart URLs. Include at least the first packet chart when charts are present, "
        "and include the first two packet charts when two are present for the Notion page. You may add concise "
        "captions only when supported by the packet. Do not label charts as Chart 1, Chart 2, Figure 1, "
        "Notebook image 1, or similarly generic placeholders; leave chart title/caption fields empty when "
        "the packet does not support a meaningful label."
    )


def _delivery_result_from_payload(payload: dict[str, Any], packet: DeliveryPacket) -> DeliveryResult | None:
    required = ("summary", "slackMessage", "notionComment", "finalAnswer", "gotchas", "analysisMethod", "notionCharts")
    if any(key not in payload for key in required):
        return None
    gotchas_raw = payload.get("gotchas")
    charts_raw = payload.get("notionCharts")
    if not isinstance(gotchas_raw, list) or not isinstance(charts_raw, list):
        return None
    allowed_chart_keys = {
        _string(chart.get("url")) or _string(chart.get("title")) for chart in packet.charts if isinstance(chart, dict)
    }
    charts: list[dict[str, Any]] = []
    for chart in charts_raw:
        if not isinstance(chart, dict):
            continue
        key = _string(chart.get("url")) or _string(chart.get("title"))
        if allowed_chart_keys and key not in allowed_chart_keys:
            continue
        charts.append(_clean_chart_labels(chart))
    packet_charts = [_clean_chart_labels(chart) for chart in packet.charts if isinstance(chart, dict)]
    if packet_charts:
        seen_chart_keys = {_string(chart.get("url")) or _string(chart.get("title")) for chart in charts}
        for chart in packet_charts:
            chart_key = _string(chart.get("url")) or _string(chart.get("title"))
            if not chart_key or chart_key in seen_chart_keys:
                continue
            charts.append(chart)
            seen_chart_keys.add(chart_key)
    return DeliveryResult(
        summary=_string(payload.get("summary")).strip(),
        slack_message=_string(payload.get("slackMessage")).strip(),
        notion_comment=_string(payload.get("notionComment")).strip(),
        final_answer=_string(payload.get("finalAnswer")).strip(),
        gotchas=[_string(item).strip() for item in gotchas_raw if _string(item).strip()],
        analysis_method=_string(payload.get("analysisMethod")).strip(),
        notion_charts=charts[:3],
        confidence_score=packet.final_statement.confidence_score if packet.final_statement else None,
    )


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
    raise ValueError("delivery renderer did not return a JSON object")


def _clip(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _is_placeholder_chart_label(value: str) -> bool:
    return bool(_PLACEHOLDER_CHART_TITLE_RE.fullmatch(value.strip()))


def _clean_chart_labels(chart: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(chart)
    for key in ("title", "caption", "altText", "alt_text"):
        value = _string(cleaned.get(key)).strip()
        if value and _is_placeholder_chart_label(value):
            cleaned[key] = ""
    return cleaned


def _compact_bullet_answer(content: str, max_bullets: int = 6) -> str:
    stripped = re.sub(r"^Here's what I found:\s*", "", content.strip(), flags=re.IGNORECASE)
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    bullets: list[str] = []
    for line in lines:
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        if line:
            bullets.append(line)
    if not bullets and stripped:
        bullets = re.split(r"(?<=[.!?])\s+", stripped)
    unique = [bullet for index, bullet in enumerate(bullets) if bullet and bullets.index(bullet) == index]
    return "\n".join(f"- {bullet}" for bullet in unique[:max_bullets])
