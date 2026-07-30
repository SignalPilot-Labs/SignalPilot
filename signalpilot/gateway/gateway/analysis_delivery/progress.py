"""Progress and final-message formatting for delivery channels."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .renderer import DeliveryResult
from .trace_loader import DeliveryPacket, WorkerProgress, load_delivery_packet

ANALYSIS_INITIAL_PROGRESS_TEXT = "Analyzing your request..."
SLACK_TEXT_LIMIT = 35000
LOGGER = logging.getLogger(__name__)


class SlackTraceProgressReporter:
    """Edit one Slack message from worker-authored PLAN/PROGRESS trace entries."""

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
    ) -> None:
        self.slack = slack
        self.session_factory = session_factory
        self.org_id = org_id
        self.user_id = user_id
        self.thread_id = thread_id
        self.source_prompt = source_prompt
        self.channel_id = channel_id
        self.message_ts = message_ts
        self.interval_seconds = max(float(interval_seconds or 15.0), 0.1)
        self.previous_text = ANALYSIS_INITIAL_PROGRESS_TEXT

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
                LOGGER.info("Slack trace progress reporter tick failed: %s", exc, exc_info=True)

    async def _tick(self) -> None:
        async with self.session_factory() as session:
            packet = await load_delivery_packet(
                session,
                org_id=self.org_id,
                user_id=self.user_id,
                thread_id=self.thread_id,
                user_request=self.source_prompt,
            )
        text = render_slack_progress_message(packet)
        if text == self.previous_text:
            return
        await self.slack.update_message(channel=self.channel_id, ts=self.message_ts, text=text)
        self.previous_text = text


def render_slack_progress_message(packet: DeliveryPacket) -> str:
    if packet.plan is None:
        return ANALYSIS_INITIAL_PROGRESS_TEXT
    lines = ["*Analyzing your request...*", *_checklist_lines(packet.plan.steps, packet.latest_progress)]
    if packet.latest_progress and packet.latest_progress.status:
        lines.append("")
        lines.append(packet.latest_progress.status)
    return _clip_text("\n".join(lines))


def render_slack_final_message(
    packet: DeliveryPacket,
    delivery: DeliveryResult,
    *,
    trail_url: str | None = None,
) -> str:
    completed = packet.status == "done"
    parts: list[str] = ["*Analysis complete*" if completed else "*Analysis failed*"]
    if packet.plan and packet.plan.steps:
        parts.extend(_checklist_lines(packet.plan.steps, packet.latest_progress, complete_all=completed))
        parts.append("")
    answer = _to_slack_mrkdwn(delivery.slack_message or delivery.final_answer or delivery.summary)
    parts.append(answer or "I finished the analysis, but there was no written answer in the result.")
    confidence = delivery.confidence_score
    if confidence is None and packet.final_statement is not None:
        confidence = packet.final_statement.confidence_score
    if confidence is not None:
        parts.append(f"*Confidence:* {confidence}")
    resolved_trail = trail_url or packet.trail_url
    if resolved_trail:
        parts.append(f"*Notebook trail:* {_slack_link(resolved_trail, 'Open authenticated notebook')}")
    return _clip_text("\n\n".join(part for part in parts if part))


def _checklist_lines(
    steps: list[str],
    progress: WorkerProgress | None,
    *,
    complete_all: bool = False,
) -> list[str]:
    completed = set(progress.completed_steps if progress else [])
    current = progress.current_step if progress else ""
    lines: list[str] = []
    for step in steps:
        checked = complete_all or step in completed
        marker = "x" if checked else " "
        suffix = " (current)" if current and step == current and not checked and not complete_all else ""
        lines.append(f"- [{marker}] {step}{suffix}")
    return lines


def _slack_link(url: str, label: str) -> str:
    return f"<{url.replace('>', '%3E')}|{label}>"


def _to_slack_mrkdwn(text: str) -> str:
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", r"*\1*", text)
    text = re.sub(r"\*\*([^*\n]+?)\*\*", r"*\1*", text)
    text = re.sub(r"__([^_\n]+?)__", r"*\1*", text)
    return re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", r"<\2|\1>", text)


def _clip_text(text: str) -> str:
    if len(text) <= SLACK_TEXT_LIMIT:
        return text
    return text[: SLACK_TEXT_LIMIT - 20].rstrip() + "\n\n... truncated"
