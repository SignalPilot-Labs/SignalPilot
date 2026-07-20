"""Notion comment-to-notebook orchestration for OAuth installations."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.analysis_delivery import (
    DeliveryPacket,
    delivery_api_key_for_org,
    delivery_result_to_status,
    load_delivery_packet,
    load_delivery_packet_from_events,
    render_delivery,
    render_followup,
    render_html_deliverable,
)
from gateway.analysis_delivery.design_system import DEFAULT_THEME, theme_token_map
from gateway.analysis_delivery.intake_actions import analysis_status_for_source_thread
from gateway.analysis_delivery.intake_agent import IntakeSession, run_intake_agent
from gateway.auth.jwt_secret import load_session_jwt_secret
from gateway.db.models import NotionInstallationConfig
from gateway.git.repos import ensure_branch_from
from gateway.models.analysis_trails import AnalysisTrailUpdate, AnalysisTrailUpsert
from gateway.models.deliverable_theme import DeliverableTheme
from gateway.models.reports import ReportCreate, ReportUpdate
from gateway.notebooks.session_service import NotebookRuntime, ensure_analysis_notebook_session
from gateway.notion import client as notion_client
from gateway.notion import dashboards as notion_dashboards
from gateway.notion import formatting as notion_formatting
from gateway.notion.webhooks import RoutedNotionInstallation
from gateway.store import analysis_trails, chat_traces, workspace_projects
from gateway.store import notion as notion_store
from gateway.store import reports as reports_store
from gateway.store import settings as settings_store

NOTION_RICH_TEXT_MAX_LENGTH = notion_formatting.NOTION_RICH_TEXT_MAX_LENGTH
_PLACEHOLDER_CHART_TITLE_RE = re.compile(
    r"(?:notebook\s+)?(?:chart|image|figure|visualization)(?:\s+\d+)?",
    flags=re.I,
)
logger = logging.getLogger(__name__)
_HTML_DELIVERABLE_SUCCESS_NOTE = "- HTML block inserted on this Notion page."
_HTML_DELIVERABLE_FAILURE_NOTE = (
    "- I could not insert the HTML block in Notion, so I delivered the analysis text here instead."
)
NOTION_ACTIVE_TRAIL_STALE_SECONDS = 30 * 60
NOTION_INTAKE_OPERATIONAL_FAILURE_TEXT = "I could not safely decide how to handle that. Try again in a moment."
NOTION_BUSY_TEXT = (
    "Still working on the earlier question in this thread. "
    "Resend this after I post the result and I'll build on it."
)
NOTION_MISSING_ANTHROPIC_KEY_TEXT = (
    "SignalPilot needs an Anthropic API key. Ask your admin to add it on the integrations page."
)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


@dataclass(frozen=True)
class NotionCommentProcessResult:
    status: str
    reason: str | None = None


@dataclass(frozen=True)
class AnalysisRoute:
    source: str
    request_id: str
    project_id: str
    branch: str
    default_branch: str
    analysis_user_id: str


class AnalysisSetupRequiredError(RuntimeError):
    """Raised when an external analysis source has no configured default project."""


class NotionIntakeConfigurationError(RuntimeError):
    """Raised when Notion intake cannot run because org credentials are missing."""


def _ignored(reason: str, **context: Any) -> NotionCommentProcessResult:
    details = " ".join(f"{key}={value}" for key, value in context.items() if value is not None)
    logger.info("Ignoring Notion comment event: %s%s", reason, f" ({details})" if details else "")
    return NotionCommentProcessResult(status="ignored", reason=reason)


async def _run_notion_intake(
    *,
    db: AsyncSession,
    routed: RoutedNotionInstallation,
    surface: str,
    prompt: str,
    source_thread_id: str,
    source_url: str,
    previous_messages: list[str],
    available_terminal_actions: tuple[str, ...],
    deliverable_context: dict[str, Any] | None = None,
):
    api_key = await delivery_api_key_for_org(db, org_id=routed.installation.org_id)
    if not api_key:
        raise NotionIntakeConfigurationError("missing org Anthropic key for Notion intake")
    session = IntakeSession(
        source="notion",
        surface=surface,
        org_id=routed.installation.org_id,
        user_id=routed.installation.user_id,
        prompt=prompt,
        source_thread_id=source_thread_id,
        source_url=source_url,
        previous_messages=previous_messages,
        continuation_state={
            "workspaceId": routed.installation.workspace_id,
            "installationId": routed.installation.id,
        },
        deliverable_context=deliverable_context or {},
        available_terminal_actions=available_terminal_actions,
        active_stale_seconds=NOTION_ACTIVE_TRAIL_STALE_SECONDS,
    )
    return await run_intake_agent(session, db=db, api_key=api_key)


async def _notion_notebook_update_status(
    db: AsyncSession,
    *,
    org_id: str,
    discussion_id: str,
) -> str:
    status = await analysis_status_for_source_thread(
        db,
        org_id=org_id,
        source="notion",
        source_thread_id=discussion_id,
        active_stale_seconds=NOTION_ACTIVE_TRAIL_STALE_SECONDS,
    )
    return status.status


def _deliverable_intake_context(deliverable: Any) -> dict[str, Any]:
    return {
        "deliverableId": _text(getattr(deliverable, "id", "")),
        "reportId": _text(getattr(deliverable, "report_id", "")),
        "embedBlockAvailable": bool(getattr(deliverable, "embed_block_id", None)),
        "fileUploadAvailable": bool(getattr(deliverable, "file_upload_id", None)),
        "embedBlockId": _text(getattr(deliverable, "embed_block_id", "")),
    }


async def _org_deliverable_theme(db: AsyncSession, org_id: str) -> DeliverableTheme:
    try:
        settings = await settings_store.load_settings(db, org_id=org_id)
    except Exception:
        logger.debug("Could not load deliverable theme for org_id=%s; using defaults", org_id, exc_info=True)
        return DEFAULT_THEME
    return settings.deliverable_theme or DEFAULT_THEME


def _rich_text(content: str) -> list[dict[str, Any]]:
    return notion_formatting.plain_rich_text(content)


def _paragraph_block(content: str) -> dict[str, Any]:
    return notion_formatting.paragraph_block(content)


def _heading_block(content: str, level: int = 2) -> dict[str, Any]:
    return notion_formatting.heading_block(content, level=level)


def _chart_value(chart: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = chart.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _status_charts(status: dict[str, Any]) -> list[dict[str, Any]]:
    charts = status.get("notionCharts", status.get("notion_charts", []))
    if not isinstance(charts, list):
        return []
    return [chart for chart in charts if isinstance(chart, dict)]


def _chart_file_upload_id(chart: dict[str, Any]) -> str:
    return _chart_value(chart, "fileUploadId", "file_upload_id")


def _chart_title(chart: dict[str, Any]) -> str:
    return _chart_value(chart, "title") or "Chart"


def _is_placeholder_chart_title(value: str) -> bool:
    return bool(_PLACEHOLDER_CHART_TITLE_RE.fullmatch(value.strip()))


def _meaningful_chart_text(chart: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _chart_value(chart, key)
        if value and not _is_placeholder_chart_title(value):
            return value
    return ""


def _chart_comment_title(chart: dict[str, Any]) -> str:
    return _meaningful_chart_text(chart, "title", "caption", "altText", "alt_text")


def _selected_charts(status: dict[str, Any], target: str) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for chart in _status_charts(status):
        if not (_chart_file_upload_id(chart) or _chart_value(chart, "url")):
            continue
        if target == "comment" and chart.get("includeInComment", chart.get("include_in_comment", True)) is False:
            continue
        if target == "page" and chart.get("includeOnPage", chart.get("include_on_page", True)) is False:
            continue
        selected.append(chart)
    return selected[:2]


def _chart_image_block(chart: dict[str, Any]) -> dict[str, Any]:
    caption = _meaningful_chart_text(chart, "caption", "altText", "alt_text", "title")
    return {
        "object": "block",
        "type": "image",
        "image": {
            "type": "file_upload",
            "file_upload": {"id": _chart_file_upload_id(chart)},
            "caption": notion_formatting.markdown_rich_text(caption, max_chars=NOTION_RICH_TEXT_MAX_LENGTH)
            if caption
            else [],
        },
    }


def _chart_detail_blocks(status: dict[str, Any]) -> list[dict[str, Any]]:
    chart_blocks = [
        _chart_image_block(chart) for chart in _selected_charts(status, "page") if _chart_file_upload_id(chart)
    ]
    if not chart_blocks:
        return []
    return [_heading_block("Charts"), *chart_blocks]


def _failure_detail_blocks(error: str) -> list[dict[str, Any]]:
    return [
        _heading_block("Analysis failed"),
        _paragraph_block(
            "SignalPilot created the request record and started the notebook-backed analysis, "
            "but the run did not complete successfully."
        ),
        _heading_block("Error details", level=3),
        *notion_formatting.code_blocks(error),
    ]


def _analysis_detail_blocks(status: dict[str, Any]) -> list[dict[str, Any]]:
    answer = status.get("finalAnswer") or status.get("summary") or "No final answer was returned."
    confidence = status.get("confidenceScore")
    confidence_text = "not provided" if confidence is None else str(confidence)
    gotchas = status.get("gotchas") or ["No caveats were returned."]
    chart_blocks = _chart_detail_blocks(status)

    if re.search(r"(?im)^##\s+(Executive Summary and Explorations|Detailed Research|Confidence Score(?::|\b))", answer):
        blocks = chart_blocks + notion_formatting.markdown_blocks_with_toggles(answer)
        return blocks[: notion_formatting.NOTION_BLOCK_CHILD_LIMIT]

    if re.search(r"(?m)^#{1,6}\s+", answer):
        blocks = notion_formatting.markdown_blocks(answer)
        if not re.search(r"(?im)^#{1,6}\s+confidence score\b", answer):
            blocks.append(
                notion_formatting.toggle_heading_block(
                    f"Confidence Score: {confidence_text}",
                    [notion_formatting.bulleted_list_item_block(str(gotcha)) for gotcha in gotchas],
                )
            )
        blocks = chart_blocks + blocks
        return blocks[: notion_formatting.NOTION_BLOCK_CHILD_LIMIT]

    blocks = [
        *chart_blocks,
        _heading_block("Executive Summary and Explorations"),
        *notion_formatting.markdown_blocks(status.get("summary") or answer),
        notion_formatting.toggle_heading_block(
            "Detailed Research", notion_formatting.markdown_blocks(answer) or [_paragraph_block(answer)]
        ),
        notion_formatting.toggle_heading_block(
            f"Confidence Score: {confidence_text}",
            [notion_formatting.bulleted_list_item_block(str(gotcha)) for gotcha in gotchas],
        ),
    ]
    return blocks[: notion_formatting.NOTION_BLOCK_CHILD_LIMIT]


_INCOMPLETE_ANALYSIS_FALLBACK_FIELDS = (
    "summary",
    "finalAnswer",
    "notionComment",
    "analysisMethod",
)
_INCOMPLETE_ANALYSIS_FALLBACK_MARKERS = (
    "analysis could not be completed",
    "did not emit the required final_statement marker",
    "api error: overloaded",
    "transient overload response",
)


def _incomplete_analysis_fallback_match(
    status: dict[str, Any]
) -> dict[str, str] | None:
    for field in _INCOMPLETE_ANALYSIS_FALLBACK_FIELDS:
        raw = str(status.get(field) or "")
        text = raw.lower()
        for marker in _INCOMPLETE_ANALYSIS_FALLBACK_MARKERS:
            index = text.find(marker)
            if index == -1:
                continue
            return {
                "field": field,
                "marker": marker,
                "snippet": _matched_status_snippet(raw, index),
            }
    return None


def _is_incomplete_analysis_fallback(status: dict[str, Any]) -> bool:
    return _incomplete_analysis_fallback_match(status) is not None


def _log_incomplete_analysis_fallback_skip(
    request_id: str,
    match: dict[str, str],
) -> None:
    logger.info(
        "Skipping Notion HTML deliverable for incomplete analysis fallback: "
        "request_id=%s field=%s marker=%s snippet=%s",
        request_id,
        match["field"],
        match["marker"],
        match["snippet"],
    )


def _matched_status_snippet(value: str, index: int, limit: int = 180) -> str:
    start = max(index - 40, 0)
    end = min(index + limit, len(value))
    return re.sub(r"\s+", " ", value[start:end]).strip()


def _analysis_request_id(source: str, discussion_id: str) -> str:
    normalized_source = re.sub(r"[^a-zA-Z0-9]+", "-", source.strip().lower()).strip("-") or "analysis"
    return f"{normalized_source}-{uuid5(NAMESPACE_URL, discussion_id).hex[:16]}"


def _analysis_branch_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return (slug[:48] or "analysis-request").strip("-")


def _analysis_branch_name(source: str, request_id: str, headline: str) -> str:
    safe_source = re.sub(r"[^a-zA-Z0-9]+", "-", source.strip().lower()).strip("-") or "analysis"
    return f"analysis/{safe_source}/{request_id}-{_analysis_branch_slug(headline)}"


def _analysis_status(value: str | None) -> str:
    if value == "Done":
        return "done"
    if value == "Failed":
        return "failed"
    return "active"


async def resolve_configured_analysis_route(
    db: AsyncSession,
    *,
    org_id: str,
    source: str,
    request_id: str,
    headline: str,
    config: NotionInstallationConfig,
) -> AnalysisRoute:
    return await resolve_analysis_route_for_defaults(
        db,
        org_id=org_id,
        source=source,
        request_id=request_id,
        headline=headline,
        default_project_id=config.default_project_id,
        default_branch=config.default_branch,
        analysis_branch_mode=config.analysis_branch_mode,
    )


async def resolve_analysis_route_for_defaults(
    db: AsyncSession,
    *,
    org_id: str,
    source: str,
    request_id: str,
    headline: str,
    default_project_id: str | None,
    default_branch: str | None = "main",
    analysis_branch_mode: str | None = "per_request",
) -> AnalysisRoute:
    project_id = (default_project_id or "").strip()
    if not project_id:
        raise AnalysisSetupRequiredError(
            f"SignalPilot needs a default dbt project before it can run {source} analysis. "
            "Open the integration settings and choose a default project."
        )

    project = await workspace_projects.get_project(db, org_id=org_id, project_id=project_id)
    if project is None:
        raise AnalysisSetupRequiredError(
            "The default dbt project configured for this integration no longer exists. "
            "Open the integration settings and choose a new default project."
        )

    default_branch = (default_branch or project.default_branch or "main").strip() or "main"
    mode = (analysis_branch_mode or "per_request").strip()
    if mode == "default_branch":
        branch = default_branch
    else:
        branch = _analysis_branch_name(source, request_id, headline)
        ensure_branch_from(project_id, branch, default_branch)

    return AnalysisRoute(
        source=source,
        request_id=request_id,
        project_id=project_id,
        branch=branch,
        default_branch=default_branch,
        analysis_user_id=f"analysis:{source}:{request_id}",
    )


async def upsert_analysis_trail_from_status(
    db: AsyncSession,
    *,
    org_id: str,
    route: AnalysisRoute,
    runtime: NotebookRuntime,
    status: dict[str, Any],
    source_url: str,
    source_thread_id: str,
    source_request_id: str | None = None,
    analysis_user_id: str | None = None,
) -> None:
    await analysis_trails.upsert_trail(
        db,
        org_id=org_id,
        trail=AnalysisTrailUpsert(
            source=route.source,
            request_id=str(status.get("requestId") or route.request_id),
            thread_id=str(status.get("sessionId") or f"session-{route.request_id}"),
            runtime_session_id=runtime.session_id,
            project_id=route.project_id,
            branch=route.branch,
            default_branch=route.default_branch,
            notebook_path=str(status.get("notebookPath") or ""),
            status=_analysis_status(status.get("status")),
            latest_commit_sha=status.get("latestCommitSha") or None,
            source_url=source_url,
            source_thread_id=source_thread_id,
            source_request_id=source_request_id,
            analysis_user_id=analysis_user_id or route.analysis_user_id,
            metadata={"trail_url": status.get("trailUrl")},
        ),
    )


async def update_analysis_trail_from_status(
    db: AsyncSession,
    *,
    org_id: str,
    route: AnalysisRoute,
    status: dict[str, Any],
) -> None:
    await analysis_trails.update_trail(
        db,
        org_id=org_id,
        source=route.source,
        request_id=str(status.get("requestId") or route.request_id),
        update=AnalysisTrailUpdate(
            status=_analysis_status(status.get("status")),
            latest_commit_sha=status.get("latestCommitSha") or None,
            notebook_path=status.get("notebookPath") or None,
            metadata={"trail_url": status.get("trailUrl")} if status.get("trailUrl") else None,
        ),
    )


def _notion_page_url(page_id: str, discussion_id: str) -> str:
    return f"https://www.notion.so/{notion_client.normalize_id(page_id)}?signalpilotDiscussion={discussion_id}"


def _headline_from_prompt(prompt: str) -> str:
    first_line = next((line.strip() for line in prompt.splitlines() if line.strip()), "SignalPilot analysis")
    return first_line[:87] + "..." if len(first_line) > 90 else first_line


def _analysis_notebook_path(source: str, headline: str, request_id: str) -> str:
    source_path = re.sub(r"[^a-zA-Z0-9_-]+", "-", source.strip().lower()).strip("-") or "analysis"
    filename_slug = re.sub(r"[^a-zA-Z0-9]+", "-", headline.strip().lower()).strip("-")[:80] or "analysis-request"
    return f"notebooks/{source_path}/{filename_slug}-{request_id[-6:]}.py"


async def upsert_analysis_trail_seed(
    db: AsyncSession,
    *,
    org_id: str,
    route: AnalysisRoute,
    runtime: NotebookRuntime,
    headline: str,
    source_url: str,
    source_thread_id: str,
    source_request_id: str | None = None,
    analysis_user_id: str | None = None,
) -> None:
    """Create durable trail metadata before the notebook runtime starts work."""
    await analysis_trails.upsert_trail(
        db,
        org_id=org_id,
        trail=AnalysisTrailUpsert(
            source=route.source,
            request_id=route.request_id,
            thread_id=f"session-{route.request_id}",
            runtime_session_id=runtime.session_id,
            project_id=route.project_id,
            branch=route.branch,
            default_branch=route.default_branch,
            notebook_path=_analysis_notebook_path(route.source, headline, route.request_id),
            status="active",
            source_url=source_url,
            source_thread_id=source_thread_id,
            source_request_id=source_request_id,
            analysis_user_id=analysis_user_id or route.analysis_user_id,
        ),
    )


def _request_page_url(page_id: str) -> str:
    return f"https://www.notion.so/{notion_client.normalize_id(page_id)}"


def _compact_bullet_answer(content: str, max_bullets: int = 6) -> str:
    stripped = re.sub(r"^Here's what I found:\s*", "", content.strip(), flags=re.IGNORECASE)
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    bullets: list[str] = []
    for line in lines:
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^[-*•]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        if line:
            bullets.append(line)
    if not bullets and stripped:
        bullets = re.split(r"(?<=[.!?])\s+", stripped)
    unique = [bullet for index, bullet in enumerate(bullets) if bullet and bullets.index(bullet) == index]
    return "\n".join(f"- {bullet}" for bullet in unique[:max_bullets])


def _clip_comment_content(content: str, reserved_chars: int) -> str:
    budget = NOTION_RICH_TEXT_MAX_LENGTH - reserved_chars
    if budget <= 0:
        return ""
    if len(content) <= budget:
        return content
    return content[: max(0, budget - 3)].rstrip() + "..."


def _start_comment_rich_text(request_page_url: str) -> list[dict[str, Any]]:
    return [
        *notion_formatting.plain_rich_text("I'm on it and will post the answer back soon. See your ", max_chars=None),
        *notion_formatting.linked_rich_text("request details", request_page_url),
        *notion_formatting.plain_rich_text(".", max_chars=None),
    ]


def _notion_progress_body(packet: Any) -> str:
    if packet.plan is None:
        return ""
    completed = set(packet.latest_progress.completed_steps if packet.latest_progress else [])
    current = packet.latest_progress.current_step if packet.latest_progress else ""
    lines = []
    for step in packet.plan.steps:
        marker = "x" if step in completed else " "
        suffix = " (current)" if current and step == current and step not in completed else ""
        lines.append(f"- [{marker}] {step}{suffix}")
    lines.append("")
    lines.append(_notion_loading_line(packet))
    return "\n".join(lines).strip()[:1500]


def _notion_loading_line(packet: Any) -> str:
    current = packet.latest_progress.current_step if packet.latest_progress else ""
    if current:
        return f"Working on: {current}."
    status = packet.latest_progress.status if packet.latest_progress else ""
    if status:
        return f"Working on: {status.replace('_', ' ')}."
    return "Working through the analysis."


def _notion_progress_text(packet: Any) -> str:
    body = _notion_progress_body(packet)
    if not body:
        return "I'm on it and will post the answer back soon. See your request details."
    return f"I'm on it and will post the answer back soon. See your request details.\n\n{body}"


def _progress_comment_rich_text(packet: Any, request_page_url: str) -> list[dict[str, Any]]:
    body = _notion_progress_body(packet)
    rich_text = _start_comment_rich_text(request_page_url)
    if body:
        rich_text.extend(notion_formatting.plain_rich_text("\n\n" + body, max_chars=NOTION_RICH_TEXT_MAX_LENGTH))
    return rich_text


async def _create_start_comment(
    token: str,
    *,
    discussion_id: str,
    request_page_url: str,
    event_id: str | None,
    comment_id: str | None,
    request_page_id: str,
) -> str | None:
    logger.info(
        "Posting Notion start comment: event_id=%s comment_id=%s discussion_id=%s request_page_id=%s",
        event_id,
        comment_id,
        discussion_id,
        request_page_id,
    )
    try:
        response = await notion_client.create_comment(
            token,
            discussion_id=discussion_id,
            rich_text=_start_comment_rich_text(request_page_url),
        )
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Could not post Notion start comment: event_id=%s comment_id=%s discussion_id=%s request_page_id=%s error=%s",
            event_id,
            comment_id,
            discussion_id,
            request_page_id,
            notion_client.http_error_summary(exc),
            exc_info=True,
        )
        raise
    created_comment_id = response.get("id") if isinstance(response, dict) else None
    logger.info(
        "Posted Notion start comment: event_id=%s comment_id=%s discussion_id=%s request_page_id=%s",
        event_id,
        created_comment_id or comment_id,
        discussion_id,
        request_page_id,
    )
    return str(created_comment_id) if created_comment_id else None


def _final_comment_rich_text(
    status: dict[str, Any],
    request_page_url: str,
    *,
    include_chart_attachment_note: bool = True,
) -> list[dict[str, Any]]:
    raw_answer = (
        (status.get("notionComment") or "").strip()
        or (status.get("finalAnswer") or "").strip()
        or (status.get("summary") or "").strip()
        or "I finished the analysis, but there was no written answer in the result."
    )
    answer = _compact_bullet_answer(raw_answer) or raw_answer
    chart_lines = (
        [
            f"- {title}"
            for chart in _selected_charts(status, "comment")
            if _chart_file_upload_id(chart) and (title := _chart_comment_title(chart))
        ]
        if include_chart_attachment_note
        else []
    )
    chart_section = "\n\nCharts attached:\n" + "\n".join(chart_lines) if chart_lines else ""
    confidence = _text(status.get("confidenceScore")).strip()
    confidence_section = (
        f"\n\n- Confidence score: {confidence}" if confidence and not _mentions_confidence(answer) else ""
    )
    suffix = confidence_section + "\n\nRequest page: request details" + chart_section
    clipped = _clip_comment_content(answer, len(suffix))
    return [
        *notion_formatting.markdown_rich_text(clipped, max_chars=len(clipped)),
        *notion_formatting.markdown_rich_text(confidence_section, max_chars=None),
        *notion_formatting.plain_rich_text("\n\nRequest page: ", max_chars=None),
        *notion_formatting.linked_rich_text("request details", request_page_url),
        *notion_formatting.markdown_rich_text(chart_section, max_chars=None),
    ]


def _mentions_confidence(text: str) -> bool:
    return bool(re.search(r"(?im)^\s*(?:[-*•]\s*)?(?:\*\*)?confidence(?:\s+score)?\b", text))


def _with_notion_comment_note(status: dict[str, Any], note: str) -> dict[str, Any]:
    next_status = dict(status)
    existing = _text(next_status.get("notionComment")).strip()
    if note in existing:
        return next_status
    next_status["notionComment"] = f"{existing}\n{note}" if existing else note
    return next_status


def _failure_comment_rich_text(error: str, request_page_url: str) -> list[dict[str, Any]]:
    prefix = "I could not complete the analysis. I added the "
    link_label = "failure details"
    suffix = " to the request page.\n\nError: "
    clipped_error = _clip_comment_content(error, len(prefix) + len(link_label) + len(suffix))
    return [
        *notion_formatting.plain_rich_text(prefix, max_chars=None),
        *notion_formatting.linked_rich_text(link_label, request_page_url),
        *notion_formatting.plain_rich_text(suffix, max_chars=None),
        *notion_formatting.inline_rich_text(clipped_error, annotations={"code": True}),
    ]


def _join_base_path(base: str, url: str) -> str:
    return f"{base.rstrip('/')}/{url.lstrip('/')}"


def _public_web_base_url(runtime: NotebookRuntime) -> str:
    parsed = urlparse(runtime.public_base_url)
    if parsed.scheme and parsed.netloc:
        return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")
    return runtime.public_base_url.rstrip("/")


def _is_notebooks_path(path: str) -> bool:
    normalized = f"/{path.lstrip('/')}".rstrip("/") or "/"
    return normalized in {"/notebooks", "/projects"} or normalized.startswith(("/notebooks/", "/projects/"))


def _path_query_fragment(parsed: Any) -> str:
    result = parsed.path or "/"
    normalized = f"/{result.lstrip('/')}"
    normalized_without_trailing = normalized.rstrip("/") or "/"
    if normalized_without_trailing == "/notebooks":
        result = "/projects"
    elif normalized.startswith("/notebooks/"):
        result = f"/projects/{normalized.removeprefix('/notebooks/')}"
    if parsed.query:
        result = f"{result}?{parsed.query}"
    if parsed.fragment:
        result = f"{result}#{parsed.fragment}"
    return result


def _relative_url_for_base(url: str, base: str, *, require_base_path: bool = False) -> str | None:
    parsed = urlparse(url)
    base_parsed = urlparse(base)
    if parsed.scheme and not _same_origin(url, base):
        return None

    path = parsed.path
    base_path = base_parsed.path.rstrip("/")
    if base_path and path.startswith(base_path + "/"):
        path = path[len(base_path) :]
    elif base_path and path == base_path:
        path = "/"
    elif require_base_path:
        return None
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{path}{query}"


def _public_signalpilot_url(url: str, runtime: NotebookRuntime | None = None) -> str:
    if runtime is None:
        return url
    base = runtime.public_base_url
    try:
        parsed = urlparse(url)
        if parsed.scheme:
            if _same_origin(url, runtime.internal_base_url) and _is_notebooks_path(parsed.path):
                return _join_base_path(_public_web_base_url(runtime), _path_query_fragment(parsed))
            for candidate_base in (runtime.internal_base_url, runtime.public_base_url):
                relative = _relative_url_for_base(url, candidate_base, require_base_path=True)
                if relative is not None:
                    return _join_base_path(runtime.public_base_url, relative)
            return url
        if _is_notebooks_path(parsed.path):
            return _join_base_path(_public_web_base_url(runtime), _path_query_fragment(parsed))
        return _join_base_path(base, url)
    except Exception:
        return url


def _same_origin(left: str, right: str) -> bool:
    left_parsed = urlparse(left)
    right_parsed = urlparse(right)
    return (
        left_parsed.scheme == right_parsed.scheme
        and left_parsed.hostname == right_parsed.hostname
        and (left_parsed.port or _default_port(left_parsed.scheme))
        == (right_parsed.port or _default_port(right_parsed.scheme))
    )


def _default_port(scheme: str) -> int | None:
    if scheme == "http":
        return 80
    if scheme == "https":
        return 443
    return None


def _internal_signalpilot_url(url: str, runtime: NotebookRuntime | None = None) -> str:
    if runtime is None:
        return url
    internal_base = runtime.internal_base_url
    public_base = runtime.public_base_url
    try:
        parsed = urlparse(_join_base_path(internal_base, url) if not urlparse(url).scheme else url)
        internal_parsed = urlparse(internal_base)
        public_parsed = urlparse(public_base) if public_base else None
        is_absolute = bool(urlparse(url).scheme)
        is_internal = _same_origin(urlunparse(parsed), internal_base)
        is_public = public_parsed is not None and _same_origin(urlunparse(parsed), public_base)
        if is_absolute and not is_internal and not is_public:
            return url
        if runtime is not None:
            for candidate_base in (runtime.internal_base_url, runtime.public_base_url):
                relative = _relative_url_for_base(urlunparse(parsed), candidate_base)
                if relative is not None:
                    return _join_base_path(runtime.internal_base_url, relative)
        rewritten = parsed._replace(
            scheme=internal_parsed.scheme,
            netloc=internal_parsed.netloc,
        )
        return urlunparse(rewritten)
    except Exception:
        return url


def _with_public_chart_urls(status: dict[str, Any], runtime: NotebookRuntime | None = None) -> dict[str, Any]:
    charts = _status_charts(status)
    if not charts:
        return status
    return {
        **status,
        "notionCharts": [
            {**chart, "url": _public_signalpilot_url(_chart_value(chart, "url"), runtime)}
            if _chart_value(chart, "url")
            else chart
            for chart in charts
        ],
    }


def _status_snapshots(status: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots = status.get("dataSnapshots", status.get("data_snapshots", []))
    if not isinstance(snapshots, list):
        return []
    return [snapshot for snapshot in snapshots if isinstance(snapshot, dict)]


def _snapshot_value(snapshot: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = snapshot.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _with_public_snapshot_urls(status: dict[str, Any], runtime: NotebookRuntime | None = None) -> dict[str, Any]:
    snapshots = _status_snapshots(status)
    if not snapshots:
        return status
    return {
        **status,
        "dataSnapshots": [
            {**snapshot, "url": _public_signalpilot_url(_snapshot_value(snapshot, "url"), runtime)}
            if _snapshot_value(snapshot, "url")
            else snapshot
            for snapshot in snapshots
        ],
    }


def _snapshot_fetcher(runtime: NotebookRuntime | None):
    async def fetch(snapshot: dict[str, Any]) -> Any:
        source_url = _snapshot_value(snapshot, "url")
        if not source_url:
            return snapshot
        fetch_url = _internal_signalpilot_url(source_url, runtime)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(fetch_url)
            response.raise_for_status()
            return response.json()

    return fetch


def _status_notebook_code(status: dict[str, Any]) -> str:
    value = status.get("notebookCode")
    return value if isinstance(value, str) else ""


def _status_notebook_sha256(status: dict[str, Any], notebook_code: str) -> str | None:
    value = status.get("notebookCodeSha256")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if notebook_code:
        return hashlib.sha256(notebook_code.encode("utf-8")).hexdigest()
    return None


async def _bounded_trace_events(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    thread_id: str,
    max_events: int = 80,
    max_chars: int = 64_000,
) -> list[dict[str, Any]]:
    try:
        events = await chat_traces.get_events(
            db,
            org_id=org_id,
            user_id=user_id,
            thread_id=thread_id,
            require_thread=False,
        )
    except Exception:
        logger.info("Could not load chat trace events for deliverable context snapshot", exc_info=True)
        return []
    bounded: list[dict[str, Any]] = []
    total_chars = 0
    for event in events[-max_events:]:
        item = {
            "idx": event.idx,
            "type": event.type,
            "role": event.role,
            "content": event.content,
            "toolName": event.tool_name,
            "isError": event.is_error,
            "turn": event.turn,
            "metadata": event.metadata,
        }
        item_chars = len(str(item))
        if total_chars + item_chars > max_chars:
            break
        bounded.append(item)
        total_chars += item_chars
    return bounded


def _existing_report_payload(report: Any) -> dict[str, Any]:
    return {
        "report_id": report.id,
        "kind": report.kind or "report",
        "title": report.title,
        "html": report.html,
        "data_json": report.data_json,
    }


def _freeze_deliverable_context(context: Any) -> Any:
    return SimpleNamespace(
        project_id=getattr(context, "project_id", None),
        branch=getattr(context, "branch", None),
        base_notebook_code=getattr(context, "base_notebook_code", None),
        base_chat_events=getattr(context, "base_chat_events", None),
        base_final_packet=getattr(context, "base_final_packet", None),
        base_notebook_path=getattr(context, "base_notebook_path", None),
    )


def _packet_from_status(prompt: str, status: dict[str, Any], trail_url: str = "") -> DeliveryPacket:
    return load_delivery_packet_from_events(
        [],
        user_request=prompt,
        status_payload=status,
        trail_url=trail_url,
        thread_status="done" if status.get("status") == "Done" else None,
    )


async def _remember_deliverable_discussion(
    db: AsyncSession,
    *,
    deliverable: Any,
    discussion_id: str,
) -> None:
    deliverable_id = _text(getattr(deliverable, "id", ""))
    if not deliverable_id or not discussion_id:
        return
    if notion_client.normalize_id(_text(getattr(deliverable, "discussion_id", ""))) == notion_client.normalize_id(
        discussion_id
    ):
        return
    try:
        updated = await notion_store.update_deliverable_discussion(
            db,
            deliverable_id=deliverable_id,
            discussion_id=discussion_id,
        )
        if updated is not None:
            deliverable.discussion_id = updated.discussion_id
            deliverable.metadata_json = updated.metadata_json
    except Exception:
        logger.info("Could not persist deliverable follow-up discussion id", exc_info=True)


def _chart_filename_extension(content_type: str) -> str:
    normalized = content_type.lower().split(";", 1)[0].strip()
    if normalized == "image/jpeg":
        return "jpg"
    if normalized == "image/svg+xml":
        return "svg"
    if normalized == "image/gif":
        return "gif"
    if normalized == "image/webp":
        return "webp"
    return "png"


def _chart_filename(chart: dict[str, Any], index: int, content_type: str) -> str:
    title = _chart_title(chart) or _chart_value(chart, "caption") or f"chart-{index + 1}"
    stem = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
    return f"{stem or f'chart-{index + 1}'}.{_chart_filename_extension(content_type)}"


def _chart_upload_candidates(status: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chart in [*_selected_charts(status, "page"), *_selected_charts(status, "comment")]:
        url = _chart_value(chart, "url")
        key = url or _chart_title(chart)
        if not key or key in seen:
            continue
        seen.add(key)
        candidates.append(chart)
    return candidates


async def _fetch_chart_image(chart: dict[str, Any], runtime: NotebookRuntime | None = None) -> tuple[bytes, str]:
    source_url = _chart_value(chart, "url")
    fetch_url = _internal_signalpilot_url(source_url, runtime)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(fetch_url)
        response.raise_for_status()
    content_type = (response.headers.get("content-type") or "image/png").split(";", 1)[0].strip() or "image/png"
    if not content_type.startswith("image/"):
        raise RuntimeError(f"chart response is not an image: {content_type}")
    return response.content, content_type


async def _upload_chart_images_to_notion(
    token: str,
    status: dict[str, Any],
    runtime: NotebookRuntime | None = None,
) -> dict[str, Any]:
    uploads: dict[str, dict[str, str]] = {}
    for index, chart in enumerate(_chart_upload_candidates(status)):
        source_url = _chart_value(chart, "url")
        if not source_url:
            continue
        try:
            if runtime is None:
                content, content_type = await _fetch_chart_image(chart)
            else:
                content, content_type = await _fetch_chart_image(chart, runtime)
            filename = _chart_filename(chart, index, content_type)
            uploaded = await notion_client.upload_file(
                token,
                filename=filename,
                content_type=content_type,
                content=content,
            )
            upload_id = uploaded.get("id")
            if upload_id:
                uploads[source_url] = {"id": str(upload_id), "fileName": filename}
        except Exception as exc:
            logger.warning(
                "Could not upload Notion chart attachment %s from %s: %s",
                _chart_title(chart),
                _internal_signalpilot_url(source_url, runtime),
                exc,
            )

    if not uploads:
        return status
    return {
        **status,
        "notionCharts": [
            {
                **chart,
                "fileUploadId": uploads[_chart_value(chart, "url")]["id"],
                "fileName": uploads[_chart_value(chart, "url")]["fileName"],
            }
            if _chart_value(chart, "url") in uploads
            else chart
            for chart in _status_charts(status)
        ],
    }


async def _insert_html_deliverable(
    *,
    db: AsyncSession,
    token: str,
    routed: RoutedNotionInstallation,
    route: AnalysisRoute,
    page_id: str,
    request_page_id: str,
    discussion_id: str,
    anchor_block_id: str | None,
    packet: Any,
    api_key: str | None,
    runtime: NotebookRuntime | None,
    session_id: str | None,
    status_payload: dict[str, Any] | None = None,
    theme: DeliverableTheme | None = None,
) -> bool:
    resolved_theme = theme or await _org_deliverable_theme(db, routed.installation.org_id)
    html_result = await render_html_deliverable(
        packet,
        api_key=api_key or None,
        fetch_snapshot=_snapshot_fetcher(runtime),
        theme=resolved_theme,
    )
    report = await reports_store.insert_report(
        db,
        org_id=routed.installation.org_id,
        payload=ReportCreate(
            title=html_result.title,
            html=html_result.html,
            scope_ref=route.project_id,
            kind=html_result.kind,
            data_json=html_result.data_json
            if html_result.data_json is not None
            else {"dataSnapshots": packet.data_snapshots},
        ),
        user_id=routed.installation.user_id,
        agent="notion_html_orchestrator",
    )
    inserted = await notion_dashboards.insert_html_deliverable(
        token,
        page_id=page_id,
        anchor_block_id=anchor_block_id,
        title=html_result.title,
        html=html_result.html,
        report_id=report.id,
    )
    deliverable = await notion_store.record_deliverable(
        db,
        org_id=routed.installation.org_id,
        installation_id=routed.installation.id,
        page_id=page_id,
        request_page_id=request_page_id,
        discussion_id=discussion_id,
        request_id=route.request_id,
        report_id=report.id,
        kind=html_result.kind,
        embed_block_id=inserted.block_id,
        file_upload_id=inserted.file_upload_id,
        session_id=session_id,
        metadata={
            "fallback_url": inserted.fallback_url,
            "archived_block_id": inserted.archived_block_id,
        },
    )
    notebook_code = _status_notebook_code(status_payload or {})
    if notebook_code:
        delivery_user_id = routed.installation.user_id or route.analysis_user_id
        thread_id = f"session-{route.request_id}"
        await notion_store.record_deliverable_context_snapshot(
            db,
            deliverable_id=deliverable.id,
            org_id=routed.installation.org_id,
            request_id=route.request_id,
            session_id=session_id or _text(status_payload.get("sessionId") if status_payload else ""),
            base_notebook_code=notebook_code,
            base_chat_events=await _bounded_trace_events(
                db,
                org_id=routed.installation.org_id,
                user_id=delivery_user_id,
                thread_id=thread_id,
            ),
            base_final_packet=packet.to_model_payload() if hasattr(packet, "to_model_payload") else {},
            base_notebook_sha256=_status_notebook_sha256(status_payload or {}, notebook_code),
            base_notebook_path=_text(status_payload.get("notebookPath") if status_payload else ""),
            project_id=route.project_id,
            branch=route.branch,
            source_prompt=packet.user_request if hasattr(packet, "user_request") else None,
            metadata={
                "base_request_id": route.request_id,
                "base_discussion_id": discussion_id,
                "base_request_page_id": request_page_id,
            },
        )
    return True


def _comment_attachments(status: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"type": "file_upload", "file_upload_id": _chart_file_upload_id(chart)}
        for chart in _selected_charts(status, "comment")
        if _chart_file_upload_id(chart)
    ][:3]


async def _create_final_comment(
    token: str,
    discussion_id: str,
    status: dict[str, Any],
    request_page_url: str,
    *,
    comment_id: str | None = None,
) -> None:
    attachments = _comment_attachments(status)
    if comment_id:
        try:
            await notion_client.delete_comment(token, comment_id)
        except Exception:
            logger.warning("Could not delete Notion progress comment before final delivery", exc_info=True)

    try:
        await notion_client.create_comment(
            token,
            discussion_id=discussion_id,
            rich_text=_final_comment_rich_text(status, request_page_url),
            attachments=attachments or None,
        )
    except Exception:
        if not attachments:
            raise
        logger.warning("Could not post final Notion comment with chart attachments; retrying without attachments")
        await notion_client.create_comment(
            token,
            discussion_id=discussion_id,
            rich_text=_final_comment_rich_text(status, request_page_url, include_chart_attachment_note=False),
        )


async def _create_failure_comment(
    token: str,
    discussion_id: str,
    message: str,
    request_page_url: str,
    *,
    comment_id: str | None = None,
) -> None:
    rich_text = _failure_comment_rich_text(message, request_page_url)
    if comment_id:
        try:
            await notion_client.update_comment(token, comment_id, rich_text=rich_text)
            return
        except Exception:
            logger.warning("Could not update Notion failure comment; posting a new failure comment", exc_info=True)
    await notion_client.create_comment(
        token,
        discussion_id=discussion_id,
        rich_text=rich_text,
    )


def mint_internal_notebook_jwt(org_id: str, user_id: str | None, scopes: list[str] | None = None) -> str:
    """Mint the internal JWT used by the notebook API for org-scoped work."""
    secret = (
        os.getenv("SIGNALPILOT_INTERNAL_JWT_SECRET") or os.getenv("SP_INTERNAL_JWT_SECRET") or load_session_jwt_secret()
    )
    now = datetime.now(UTC)
    payload = {
        "iss": "signalpilot-gateway",
        "aud": "signalpilot-notebook",
        "sub": user_id or "notion-webhook",
        "org_id": org_id,
        "scopes": scopes or ["notion:analysis"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


async def _call_notebook(
    runtime: NotebookRuntime,
    path: str,
    org_id: str,
    user_id: str | None,
    init: dict[str, Any] | None = None,
) -> dict:
    base = runtime.internal_base_url.rstrip("/")
    token = mint_internal_notebook_jwt(org_id, user_id, ["notion:analysis:start", "notion:analysis:read"])
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request(
            (init or {}).get("method", "GET"),
            _join_base_path(base, path),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                **((init or {}).get("headers") or {}),
            },
            json=(init or {}).get("json"),
        )
        response.raise_for_status()
        return response.json()


async def _poll_analysis(
    request_id: str,
    runtime: NotebookRuntime,
    org_id: str,
    user_id: str | None,
    route: AnalysisRoute | None = None,
    on_tick: Any | None = None,
) -> dict:
    max_polls = int(os.getenv("SIGNALPILOT_MAX_POLLS", "300"))
    interval_ms = int(os.getenv("SIGNALPILOT_POLL_INTERVAL_MS", "5000"))
    headers = (
        {
            "X-Gateway-Project-Id": route.project_id,
            "X-Gateway-Branch-Id": route.branch,
        }
        if route is not None
        else None
    )
    for _ in range(max_polls):
        status = await _call_notebook(
            runtime,
            f"/api/notion-analysis/status/{request_id}",
            org_id,
            user_id,
            {"headers": headers} if headers else None,
        )
        if status.get("status") in ("Done", "Failed"):
            return status
        if on_tick is not None:
            await on_tick(status)
        await asyncio.sleep(interval_ms / 1000)
    raise TimeoutError(f"SignalPilot analysis timed out: {request_id}")


class _NotionTraceProgressReporter:
    def __init__(
        self,
        *,
        token: str,
        request_page_url: str,
        progress_comment_id: str | None,
        db: AsyncSession,
        org_id: str,
        user_id: str,
        thread_id: str,
        user_request: str,
    ) -> None:
        self.token = token
        self.request_page_url = request_page_url
        self.progress_comment_id = progress_comment_id
        self.db = db
        self.org_id = org_id
        self.user_id = user_id
        self.thread_id = thread_id
        self.user_request = user_request
        self._previous_progress_text = "I'm on it and will post the answer back soon. See your request details."

    async def tick(self, _status: dict[str, Any]) -> None:
        try:
            packet = await load_delivery_packet(
                self.db,
                org_id=self.org_id,
                user_id=self.user_id,
                thread_id=self.thread_id,
                user_request=self.user_request,
            )
        except Exception as exc:
            logger.info("Could not load Notion trace progress: %s", exc, exc_info=True)
            return
        progress_text = _notion_progress_text(packet)
        if progress_text == self._previous_progress_text:
            return
        self._previous_progress_text = progress_text
        if self.progress_comment_id:
            try:
                await notion_client.update_comment(
                    self.token,
                    self.progress_comment_id,
                    rich_text=_progress_comment_rich_text(packet, self.request_page_url),
                )
            except Exception as exc:
                logger.info("Could not update Notion progress comment: %s", exc, exc_info=True)


def _require_requests_data_source_id(config: NotionInstallationConfig) -> str:
    if not config.requests_data_source_id:
        raise RuntimeError("Notion installation is missing requests_data_source_id")
    return config.requests_data_source_id


async def _comment_deliverable_followup(
    token: str,
    discussion_id: str,
    message: str,
) -> None:
    await notion_client.create_comment(
        token,
        discussion_id=discussion_id,
        rich_text=_rich_text(message),
    )


async def _release_db_session(db: AsyncSession) -> None:
    """End an idle transaction before long external work can outlive its DB connection."""
    rollback = getattr(db, "rollback", None)
    if rollback is None:
        return
    try:
        result = rollback()
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.debug("Could not release DB session before external Notion deliverable work", exc_info=True)


async def _mark_deliverable_update_failed_best_effort(
    db: AsyncSession,
    *,
    update_id: str | None,
    deliverable_id: str,
    error: str,
) -> None:
    try:
        await notion_store.mark_deliverable_update_failed(
            db,
            update_id=update_id,
            deliverable_id=deliverable_id,
            error=error,
        )
    except Exception:
        logger.warning("Could not mark Notion deliverable update failed", exc_info=True)
        await _release_db_session(db)


def _followup_refresh_route(context: Any, ephemeral_run_id: str) -> AnalysisRoute:
    project_id = _text(getattr(context, "project_id", None))
    branch = _text(getattr(context, "branch", None)) or "main"
    return AnalysisRoute(
        source="notion-refresh",
        request_id=ephemeral_run_id,
        project_id=project_id,
        branch=branch,
        default_branch="main",
        analysis_user_id=f"analysis:notion-refresh:{ephemeral_run_id}",
    )


async def _load_refresh_delivery_packet(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    thread_id: str,
    prompt: str,
    status: dict[str, Any],
    trail_url: str,
) -> DeliveryPacket:
    try:
        return await load_delivery_packet(
            db,
            org_id=org_id,
            user_id=user_id,
            thread_id=thread_id,
            user_request=prompt,
            status_payload=status,
            trail_url=trail_url,
        )
    except Exception:
        logger.info("Could not load refresh delivery trace; using status fallback", exc_info=True)
        return _packet_from_status(prompt, status, trail_url)


async def _run_ephemeral_deliverable_refresh(
    *,
    db: AsyncSession,
    org_id: str,
    user_id: str | None,
    context: Any,
    deliverable_id: str,
    ephemeral_run_id: str,
    data_instruction: str,
    theme: DeliverableTheme | None = None,
) -> tuple[DeliveryPacket, NotebookRuntime]:
    route = _followup_refresh_route(context, ephemeral_run_id)
    if not route.project_id:
        raise RuntimeError("Refresh context is missing project_id; rebuild the deliverable once before refreshing.")
    runtime = await ensure_analysis_notebook_session(
        db,
        org_id=org_id,
        source=route.source,
        request_id=route.request_id,
        project_id=route.project_id,
        branch=route.branch,
        credential_user_id=user_id,
    )
    await _release_db_session(db)
    start = await _call_notebook(
        runtime,
        "/api/notion-analysis/refresh",
        org_id,
        user_id,
        {
            "method": "POST",
            "json": {
                "ephemeralRunId": ephemeral_run_id,
                "deliverableId": deliverable_id,
                "baseNotebookCode": context.base_notebook_code,
                "baseChatEvents": context.base_chat_events or [],
                "baseFinalPacket": context.base_final_packet or {},
                "baseNotebookPath": context.base_notebook_path,
                "prompt": data_instruction,
                "outputMode": "deliverable",
                "theme": theme_token_map(theme),
            },
            "headers": {
                "X-Gateway-Project-Id": route.project_id,
                "X-Gateway-Branch-Id": route.branch,
            },
        },
    )
    status = await _poll_analysis(
        str(start.get("requestId") or ephemeral_run_id),
        runtime,
        org_id,
        user_id,
        route,
    )
    if status.get("status") != "Done" or status.get("error"):
        raise RuntimeError(str(status.get("error") or "Refresh analysis did not complete"))
    public_status = _with_public_snapshot_urls(_with_public_chart_urls(status, runtime), runtime)
    trail_url = _public_signalpilot_url(public_status.get("trailUrl") or "", runtime)
    packet = await _load_refresh_delivery_packet(
        db,
        org_id=org_id,
        user_id=user_id or route.analysis_user_id,
        thread_id=f"session-{ephemeral_run_id}",
        prompt=data_instruction,
        status=public_status,
        trail_url=trail_url,
    )
    await _release_db_session(db)
    return packet, runtime


async def _process_deliverable_followup(
    *,
    db: AsyncSession,
    token: str,
    routed: RoutedNotionInstallation,
    deliverable: Any,
    discussion_id: str,
    prompt: str,
) -> NotionCommentProcessResult:
    org_id = routed.installation.org_id
    user_id = routed.installation.user_id
    deliverable_id = deliverable.id
    report_id = deliverable.report_id
    embed_block_id = deliverable.embed_block_id
    file_upload_id = getattr(deliverable, "file_upload_id", None)

    try:
        action = (
            await _run_notion_intake(
                db=db,
                routed=routed,
                surface="notion_deliverable_followup",
                prompt=prompt,
                source_thread_id=discussion_id,
                source_url="",
                previous_messages=[],
                available_terminal_actions=(
                    "respond_to_user",
                    "react_or_ignore",
                    "update_notion_deliverable",
                ),
                deliverable_context=_deliverable_intake_context(deliverable),
            )
        ).action
    except NotionIntakeConfigurationError:
        await _comment_deliverable_followup(
            token,
            discussion_id,
            NOTION_MISSING_ANTHROPIC_KEY_TEXT,
        )
        return NotionCommentProcessResult(status="processed")
    except Exception:
        logger.info("Notion deliverable intake failed", exc_info=True)
        await _comment_deliverable_followup(token, discussion_id, NOTION_INTAKE_OPERATIONAL_FAILURE_TEXT)
        return NotionCommentProcessResult(status="processed")

    if action.name == "respond_to_user":
        await _comment_deliverable_followup(token, discussion_id, action.text)
        return NotionCommentProcessResult(status="processed")
    if action.name == "react_or_ignore":
        return NotionCommentProcessResult(status="processed")
    if action.name != "update_notion_deliverable":
        await _comment_deliverable_followup(token, discussion_id, NOTION_INTAKE_OPERATIONAL_FAILURE_TEXT)
        return NotionCommentProcessResult(status="processed")

    mode = action.deliverable_mode
    requires_ephemeral_run = mode == "refresh_data"
    render_instruction = action.render_instruction
    data_instruction = action.data_instruction

    report = await reports_store.get_report(
        db,
        org_id=org_id,
        report_id=report_id,
    )
    if report is None:
        await _comment_deliverable_followup(
            token,
            discussion_id,
            "I found this dashboard/report block, but its saved SignalPilot report is missing.",
        )
        return NotionCommentProcessResult(status="processed")
    if not embed_block_id:
        await _comment_deliverable_followup(
            token,
            discussion_id,
            "I can edit saved reports, but this older deliverable does not have a replaceable Notion embed block.",
        )
        return NotionCommentProcessResult(status="processed")
    if not file_upload_id:
        await _comment_deliverable_followup(
            token,
            discussion_id,
            (
                "I can edit saved reports, but this dashboard/report was delivered as a link "
                "because the HTML exceeded Notion's inline embed limit. Rebuild it as a smaller "
                "inline embed before asking me to edit or refresh it."
            ),
        )
        return NotionCommentProcessResult(status="processed")

    existing_report = _existing_report_payload(report)
    report_data_json = report.data_json
    theme = await _org_deliverable_theme(db, org_id)
    ephemeral_run_id = f"notion-refresh-{uuid4().hex[:16]}" if requires_ephemeral_run else None
    update = await notion_store.create_deliverable_update(
        db,
        deliverable_id=deliverable_id,
        org_id=org_id,
        mode=mode,
        prompt=prompt,
        data_instruction=data_instruction,
        render_instruction=render_instruction,
        old_file_upload_id=file_upload_id,
        ephemeral_run_id=ephemeral_run_id,
    )
    update_id = update.id

    try:
        runtime: NotebookRuntime | None = None
        packet: DeliveryPacket | None = None
        if requires_ephemeral_run:
            context = await notion_store.latest_deliverable_context_snapshot(db, deliverable_id=deliverable_id)
            if context is None or not context.base_notebook_code:
                message = (
                    "I can edit this dashboard/report, but refresh requires a rebuild once with "
                    "captured SignalPilot context. Rebuild it once, then refresh will be available."
                )
                await _mark_deliverable_update_failed_best_effort(
                    db,
                    update_id=update_id,
                    deliverable_id=deliverable_id,
                    error=message,
                )
                await _comment_deliverable_followup(token, discussion_id, message)
                return NotionCommentProcessResult(status="processed")
            context = _freeze_deliverable_context(context)
            await _release_db_session(db)
            packet, runtime = await _run_ephemeral_deliverable_refresh(
                db=db,
                org_id=org_id,
                user_id=user_id,
                context=context,
                deliverable_id=deliverable_id,
                ephemeral_run_id=ephemeral_run_id or f"notion-refresh-{uuid4().hex[:16]}",
                data_instruction=data_instruction or prompt,
                theme=theme,
            )

        await _comment_deliverable_followup(
            token,
            discussion_id,
            "Refreshing and updating this dashboard/report."
            if requires_ephemeral_run
            else "Updating this dashboard/report.",
        )
        delivery_api_key = await delivery_api_key_for_org(
            db,
            org_id=org_id,
        )
        await _release_db_session(db)
        html_result = await render_followup(
            render_instruction,
            existing_report,
            packet,
            "refresh_data" if requires_ephemeral_run else "edit_existing",
            api_key=delivery_api_key or None,
            fetch_snapshot=_snapshot_fetcher(runtime),
            theme=theme,
        )
        replaced = await notion_dashboards.replace_html_deliverable(
            token,
            embed_block_id=embed_block_id,
            title=html_result.title,
            html=html_result.html,
            report_id=report_id,
        )
        await reports_store.update_report_html(
            db,
            org_id=org_id,
            report_id=report_id,
            payload=ReportUpdate(
                title=html_result.title,
                html=html_result.html,
                data_json=html_result.data_json if html_result.data_json is not None else report_data_json,
            ),
        )
        await notion_store.mark_deliverable_update_succeeded(
            db,
            update_id=update_id,
            deliverable_id=deliverable_id,
            new_file_upload_id=replaced.file_upload_id,
            html_bytes=len(html_result.html.encode("utf-8")),
        )
        await _comment_deliverable_followup(
            token,
            discussion_id,
            "Updated this dashboard/report with fresh data."
            if requires_ephemeral_run
            else "Updated this dashboard/report.",
        )
        return NotionCommentProcessResult(status="processed")
    except Exception as exc:
        logger.info("Could not update Notion HTML deliverable follow-up", exc_info=True)
        message = str(exc) or exc.__class__.__name__
        await _release_db_session(db)
        await _mark_deliverable_update_failed_best_effort(
            db,
            update_id=update_id,
            deliverable_id=deliverable_id,
            error=message,
        )
        await _comment_deliverable_followup(
            token,
            discussion_id,
            f"I could not update this dashboard/report: {message}",
        )
        return NotionCommentProcessResult(status="processed")


async def process_routed_comment_event(
    routed: RoutedNotionInstallation,
    payload: dict,
    *,
    db: AsyncSession,
) -> NotionCommentProcessResult:
    """Run the comment-triggered Notion analysis workflow for a routed event."""
    token = routed.access_token
    requests_data_source_id = _require_requests_data_source_id(routed.config)
    comment_id = payload.get("entity", {}).get("id")
    page_id = payload.get("data", {}).get("page_id")
    parent_block_id = payload.get("data", {}).get("parent", {}).get("id")
    if not comment_id or not page_id:
        return _ignored(
            "missing_comment_or_page_id", event_id=payload.get("id"), comment_id=comment_id, page_id=page_id
        )

    block_id = parent_block_id or page_id
    comments = await notion_client.list_comments(token, block_id)
    trigger_comment = next((comment for comment in comments if comment.get("id") == comment_id), None)
    if trigger_comment is None:
        try:
            trigger_comment = await notion_client.retrieve_comment(token, str(comment_id))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return _ignored(
                    "comment_not_found", event_id=payload.get("id"), comment_id=comment_id, block_id=block_id
                )
            raise
    if notion_client.is_bot_comment(trigger_comment):
        return _ignored("bot_comment", event_id=payload.get("id"), comment_id=comment_id)
    discussion_id = trigger_comment.get("discussion_id")
    prompt = notion_client.extract_comment_text(trigger_comment)
    if not discussion_id or not prompt:
        return _ignored(
            "missing_discussion_or_prompt",
            event_id=payload.get("id"),
            comment_id=comment_id,
            discussion_id=discussion_id,
        )

    deliverable = await notion_store.find_deliverable_by_embed_block(
        db,
        org_id=routed.installation.org_id,
        installation_id=routed.installation.id,
        embed_block_id=parent_block_id,
    )
    if deliverable is None and parent_block_id:
        deliverable = await notion_store.find_deliverable_by_discussion(
            db,
            org_id=routed.installation.org_id,
            installation_id=routed.installation.id,
            discussion_id=discussion_id,
        )
    if deliverable is not None:
        await _remember_deliverable_discussion(db, deliverable=deliverable, discussion_id=discussion_id)
        return await _process_deliverable_followup(
            db=db,
            token=token,
            routed=routed,
            deliverable=deliverable,
            discussion_id=discussion_id,
            prompt=prompt,
        )

    previous_messages = [
        notion_client.extract_comment_text(comment)
        for comment in comments
        if comment.get("id") != comment_id
        and comment.get("discussion_id") == discussion_id
        and not notion_client.is_bot_comment(comment)
    ]
    previous_messages = [message for message in previous_messages if message]

    source_url = _notion_page_url(page_id, discussion_id)
    try:
        action = (
            await _run_notion_intake(
                db=db,
                routed=routed,
                surface="notion_comment",
                prompt=prompt,
                source_thread_id=discussion_id,
                source_url=source_url,
                previous_messages=previous_messages,
                available_terminal_actions=(
                    "respond_to_user",
                    "react_or_ignore",
                    "start_notebook_analysis",
                    "update_notebook_analysis",
                ),
            )
        ).action
    except NotionIntakeConfigurationError:
        await notion_client.create_comment(
            token,
            discussion_id=discussion_id,
            rich_text=_rich_text(NOTION_MISSING_ANTHROPIC_KEY_TEXT),
        )
        return NotionCommentProcessResult(status="processed")
    except Exception:
        logger.info("Notion intake failed", exc_info=True)
        await notion_client.create_comment(
            token,
            discussion_id=discussion_id,
            rich_text=_rich_text(NOTION_INTAKE_OPERATIONAL_FAILURE_TEXT),
        )
        return NotionCommentProcessResult(status="processed")

    if action.name == "respond_to_user":
        await notion_client.create_comment(
            token,
            discussion_id=discussion_id,
            rich_text=_rich_text(action.text),
        )
        return NotionCommentProcessResult(status="processed")
    if action.name == "react_or_ignore":
        return NotionCommentProcessResult(status="processed")
    if action.name not in {"start_notebook_analysis", "update_notebook_analysis"}:
        await notion_client.create_comment(
            token,
            discussion_id=discussion_id,
            rich_text=_rich_text(NOTION_INTAKE_OPERATIONAL_FAILURE_TEXT),
        )
        return NotionCommentProcessResult(status="processed")
    if action.name == "update_notebook_analysis":
        update_status = await _notion_notebook_update_status(
            db,
            org_id=routed.installation.org_id,
            discussion_id=discussion_id,
        )
        if update_status == "busy":
            await notion_client.create_comment(token, discussion_id=discussion_id, rich_text=_rich_text(NOTION_BUSY_TEXT))
            return NotionCommentProcessResult(status="processed")
        if update_status == "not_found":
            await notion_client.create_comment(
                token,
                discussion_id=discussion_id,
                rich_text=_rich_text("I could not find an earlier SignalPilot analysis in this thread to update."),
            )
            return NotionCommentProcessResult(status="processed")

    analysis_prompt = action.prompt
    output_mode = action.output_mode
    headline = _headline_from_prompt(analysis_prompt)
    requester_ids = [
        str(author.get("id"))
        for author in payload.get("authors") or []
        if author.get("id") and author.get("type") in ("person", "user")
    ]
    created_at = datetime.now(UTC).isoformat()
    request_page = await notion_client.query_request_page_by_source(token, requests_data_source_id, source_url)
    if request_page is None:
        request_page = await notion_client.create_request_page(
            token,
            requests_data_source_id,
            headline=headline,
            source_url=source_url,
            requester_id=requester_ids[0] if requester_ids else "Unknown",
            prompt=prompt,
            created_at=created_at,
        )
    request_page_id = request_page["id"]
    request_page_url = request_page.get("url") or _request_page_url(request_page_id)
    progress_comment_id: str | None = None

    request_id = _analysis_request_id("notion", discussion_id)
    try:
        route = await resolve_configured_analysis_route(
            db,
            org_id=routed.installation.org_id,
            source="notion",
            request_id=request_id,
            headline=headline,
            config=routed.config,
        )
    except AnalysisSetupRequiredError as exc:
        message = str(exc)
        await notion_client.update_page_properties(
            token,
            request_page_id,
            {"Status": {"rich_text": _rich_text("Failed")}, "Summary": {"rich_text": _rich_text(message)}},
        )
        await notion_client.append_page_blocks(token, request_page_id, _failure_detail_blocks(message))
        await notion_client.create_comment(
            token,
            discussion_id=discussion_id,
            rich_text=_failure_comment_rich_text(message, request_page_url),
        )
        return NotionCommentProcessResult(status="processed")

    await notion_client.update_page_properties(
        token, request_page_id, {"Status": {"rich_text": _rich_text("Analyzing")}}
    )
    progress_comment_id = await _create_start_comment(
        token,
        discussion_id=discussion_id,
        request_page_url=request_page_url,
        event_id=payload.get("id"),
        comment_id=comment_id,
        request_page_id=request_page_id,
    )
    theme = await _org_deliverable_theme(db, routed.installation.org_id)
    try:
        runtime = await ensure_analysis_notebook_session(
            db,
            org_id=routed.installation.org_id,
            source=route.source,
            request_id=route.request_id,
            project_id=route.project_id,
            branch=route.branch,
            credential_user_id=routed.installation.user_id,
        )
        await upsert_analysis_trail_seed(
            db,
            org_id=routed.installation.org_id,
            route=route,
            runtime=runtime,
            headline=headline,
            source_url=source_url,
            source_thread_id=discussion_id,
            source_request_id=request_page_id,
            analysis_user_id=routed.installation.user_id,
        )
        start = await _call_notebook(
            runtime,
            "/api/notion-analysis/start",
            routed.installation.org_id,
            routed.installation.user_id,
            {
                "method": "POST",
                "json": {
                    "source": "notion",
                    "discussionId": discussion_id,
                    "notionRequestPageId": request_page_id,
                    "sourceUrl": source_url,
                    "requester": requester_ids,
                    "headline": headline,
                    "prompt": analysis_prompt,
                    "outputMode": output_mode,
                    "previousMessages": previous_messages,
                    "createdAt": created_at,
                    "theme": theme_token_map(theme),
                },
                "headers": {
                    "X-Gateway-Project-Id": route.project_id,
                    "X-Gateway-Branch-Id": route.branch,
                },
            },
        )
        await upsert_analysis_trail_from_status(
            db,
            org_id=routed.installation.org_id,
            route=route,
            runtime=runtime,
            status=start,
            source_url=source_url,
            source_thread_id=discussion_id,
            source_request_id=request_page_id,
            analysis_user_id=routed.installation.user_id,
        )
    except Exception as exc:
        message = str(exc)
        await notion_client.update_page_properties(
            token,
            request_page_id,
            {"Status": {"rich_text": _rich_text("Failed")}, "Summary": {"rich_text": _rich_text(message)}},
        )
        await notion_client.append_page_blocks(token, request_page_id, _failure_detail_blocks(message))
        await _create_failure_comment(
            token,
            discussion_id,
            message,
            request_page_url,
            comment_id=progress_comment_id,
        )
        raise

    start_trail_url = _public_signalpilot_url(start.get("trailUrl") or "", runtime)
    await notion_client.update_page_properties(token, request_page_id, {"Trail URL": {"url": start_trail_url or None}})

    try:
        trace_thread_id = f"session-{route.request_id}"
        final_status = await _poll_analysis(
            str(start["requestId"]),
            runtime,
            routed.installation.org_id,
            routed.installation.user_id,
            route,
            on_tick=_NotionTraceProgressReporter(
                token=token,
                request_page_url=request_page_url,
                progress_comment_id=progress_comment_id,
                db=db,
                org_id=routed.installation.org_id,
                user_id=routed.installation.user_id or route.analysis_user_id,
                thread_id=trace_thread_id,
                user_request=analysis_prompt,
            ).tick,
        )
        await update_analysis_trail_from_status(
            db,
            org_id=routed.installation.org_id,
            route=route,
            status=final_status,
        )
    except Exception as exc:
        message = str(exc)
        await analysis_trails.update_trail(
            db,
            org_id=routed.installation.org_id,
            source=route.source,
            request_id=route.request_id,
            update=AnalysisTrailUpdate(status="failed"),
        )
        await notion_client.update_page_properties(
            token,
            request_page_id,
            {"Status": {"rich_text": _rich_text("Failed")}, "Summary": {"rich_text": _rich_text(message)}},
        )
        await notion_client.append_page_blocks(token, request_page_id, _failure_detail_blocks(message))
        await _create_failure_comment(
            token,
            discussion_id,
            message,
            request_page_url,
            comment_id=progress_comment_id,
        )
        raise

    if final_status.get("status") == "Done" and not final_status.get("error"):
        public_status = _with_public_snapshot_urls(_with_public_chart_urls(final_status, runtime), runtime)
        public_trail_url = _public_signalpilot_url(public_status.get("trailUrl") or start_trail_url, runtime)
        delivery_user_id = routed.installation.user_id or route.analysis_user_id
        delivery_api_key = await delivery_api_key_for_org(
            db,
            org_id=routed.installation.org_id,
        )
        try:
            packet = await load_delivery_packet(
                db,
                org_id=routed.installation.org_id,
                user_id=delivery_user_id,
                thread_id=f"session-{route.request_id}",
                user_request=analysis_prompt,
                status_payload=public_status,
                trail_url=public_trail_url,
            )
        except Exception as exc:
            logger.info("Could not load Notion delivery trace; using status fallback: %s", exc, exc_info=True)
            packet = load_delivery_packet_from_events(
                [],
                user_request=analysis_prompt,
                status_payload=public_status,
                trail_url=public_trail_url,
                thread_status="done",
            )
        delivery = await render_delivery(packet, api_key=delivery_api_key)
        rendered_status = delivery_result_to_status(delivery, packet, base_status=public_status)
        html_delivery_error: str | None = None
        incomplete_fallback_match = _incomplete_analysis_fallback_match(final_status)
        deliver_html = output_mode == "deliverable"
        if deliver_html and incomplete_fallback_match:
            _log_incomplete_analysis_fallback_skip(
                route.request_id, incomplete_fallback_match
            )
            deliver_html = False
        if deliver_html:
            try:
                delivered = await _insert_html_deliverable(
                    db=db,
                    token=token,
                    routed=routed,
                    route=route,
                    page_id=page_id,
                    request_page_id=request_page_id,
                    discussion_id=discussion_id,
                    anchor_block_id=parent_block_id,
                    packet=packet,
                    api_key=delivery_api_key,
                    runtime=runtime,
                    session_id=str(final_status.get("sessionId") or ""),
                    status_payload=final_status,
                    theme=theme,
                )
            except Exception as exc:
                logger.warning(
                    "Could not deliver Notion HTML artifact for %s; falling back to standard delivery: %s",
                    route.request_id,
                    exc,
                    exc_info=True,
                )
                html_delivery_error = str(exc) or exc.__class__.__name__
                delivered = False
            if delivered:
                final_status_for_notion = _with_public_snapshot_urls(
                    _with_public_chart_urls(rendered_status, runtime),
                    runtime,
                )
                final_status_for_notion = _with_notion_comment_note(
                    final_status_for_notion,
                    _HTML_DELIVERABLE_SUCCESS_NOTE,
                )
                await notion_client.update_page_properties(
                    token,
                    request_page_id,
                    {
                        "Status": {"rich_text": _rich_text("Done")},
                        "Trail URL": {
                            "url": _public_signalpilot_url(
                                final_status_for_notion.get("trailUrl") or start_trail_url,
                                runtime,
                            )
                            or None
                        },
                        "Confidence score": {
                            "rich_text": _rich_text(str(final_status_for_notion.get("confidenceScore") or ""))
                        },
                        "Summary": {
                            "rich_text": _rich_text(
                                final_status_for_notion.get("summary")
                                or final_status_for_notion.get("finalAnswer")
                                or ""
                            )
                        },
                    },
                )
                await _create_final_comment(
                    token,
                    discussion_id,
                    final_status_for_notion,
                    request_page_url,
                    comment_id=progress_comment_id,
                )
                await notion_client.append_page_blocks(
                    token,
                    request_page_id,
                    _analysis_detail_blocks(final_status_for_notion),
                )
                return NotionCommentProcessResult(status="processed")
        uploaded_status = await _upload_chart_images_to_notion(token, rendered_status, runtime)
        final_status_for_notion = _with_public_chart_urls(uploaded_status, runtime)
        if html_delivery_error:
            final_status_for_notion = _with_notion_comment_note(
                final_status_for_notion,
                _HTML_DELIVERABLE_FAILURE_NOTE,
            )
        await notion_client.update_page_properties(
            token,
            request_page_id,
            {
                "Status": {"rich_text": _rich_text("Done")},
                "Trail URL": {
                    "url": _public_signalpilot_url(final_status_for_notion.get("trailUrl") or start_trail_url, runtime)
                    or None
                },
                "Confidence score": {
                    "rich_text": _rich_text(str(final_status_for_notion.get("confidenceScore") or ""))
                },
                "Summary": {
                    "rich_text": _rich_text(
                        final_status_for_notion.get("summary") or final_status_for_notion.get("finalAnswer") or ""
                    )
                },
            },
        )
        await _create_final_comment(
            token,
            discussion_id,
            final_status_for_notion,
            request_page_url,
            comment_id=progress_comment_id,
        )
        await notion_client.append_page_blocks(token, request_page_id, _analysis_detail_blocks(final_status_for_notion))
    else:
        message = final_status.get("error") or "SignalPilot analysis failed."
        await notion_client.update_page_properties(
            token,
            request_page_id,
            {"Status": {"rich_text": _rich_text("Failed")}, "Summary": {"rich_text": _rich_text(message)}},
        )
        await notion_client.append_page_blocks(token, request_page_id, _failure_detail_blocks(str(message)))
        await _create_failure_comment(
            token,
            discussion_id,
            str(message),
            request_page_url,
            comment_id=progress_comment_id,
        )
    return NotionCommentProcessResult(status="processed")
