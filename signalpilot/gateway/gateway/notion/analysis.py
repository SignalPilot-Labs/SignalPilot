"""Notion comment-to-notebook orchestration for OAuth installations."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.auth.jwt_secret import load_session_jwt_secret
from gateway.db.models import NotionInstallationConfig
from gateway.notebooks.session_service import NotebookRuntime, ensure_notion_notebook_session
from gateway.notion import client as notion_client
from gateway.notion import formatting as notion_formatting
from gateway.notion.webhooks import RoutedNotionInstallation

NOTION_RICH_TEXT_MAX_LENGTH = notion_formatting.NOTION_RICH_TEXT_MAX_LENGTH
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotionCommentProcessResult:
    status: str
    reason: str | None = None


def _ignored(reason: str, **context: Any) -> NotionCommentProcessResult:
    details = " ".join(f"{key}={value}" for key, value in context.items() if value is not None)
    logger.info("Ignoring Notion comment event: %s%s", reason, f" ({details})" if details else "")
    return NotionCommentProcessResult(status="ignored", reason=reason)


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
    title = _chart_title(chart)
    caption = _chart_value(chart, "caption") or _chart_value(chart, "altText", "alt_text") or title
    return {
        "object": "block",
        "type": "image",
        "image": {
            "type": "file_upload",
            "file_upload": {"id": _chart_file_upload_id(chart)},
            "caption": notion_formatting.markdown_rich_text(caption, max_chars=NOTION_RICH_TEXT_MAX_LENGTH),
        },
    }


def _chart_detail_blocks(status: dict[str, Any]) -> list[dict[str, Any]]:
    chart_blocks = [_chart_image_block(chart) for chart in _selected_charts(status, "page") if _chart_file_upload_id(chart)]
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
        notion_formatting.toggle_heading_block("Detailed Research", notion_formatting.markdown_blocks(answer) or [_paragraph_block(answer)]),
        notion_formatting.toggle_heading_block(
            f"Confidence Score: {confidence_text}",
            [notion_formatting.bulleted_list_item_block(str(gotcha)) for gotcha in gotchas],
        ),
    ]
    return blocks[: notion_formatting.NOTION_BLOCK_CHILD_LIMIT]


def _notion_page_url(page_id: str, discussion_id: str) -> str:
    return f"https://www.notion.so/{notion_client.normalize_id(page_id)}?signalpilotDiscussion={discussion_id}"


def _headline_from_prompt(prompt: str) -> str:
    first_line = next((line.strip() for line in prompt.splitlines() if line.strip()), "SignalPilot analysis")
    return first_line[:87] + "..." if len(first_line) > 90 else first_line


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


async def _create_start_comment(
    token: str,
    *,
    discussion_id: str,
    request_page_url: str,
    event_id: str | None,
    comment_id: str | None,
    request_page_id: str,
) -> None:
    logger.info(
        "Posting Notion start comment: event_id=%s comment_id=%s discussion_id=%s request_page_id=%s",
        event_id,
        comment_id,
        discussion_id,
        request_page_id,
    )
    try:
        await notion_client.create_comment(
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
    logger.info(
        "Posted Notion start comment: event_id=%s comment_id=%s discussion_id=%s request_page_id=%s",
        event_id,
        comment_id,
        discussion_id,
        request_page_id,
    )


def _final_comment_rich_text(status: dict[str, Any], request_page_url: str) -> list[dict[str, Any]]:
    raw_answer = (
        (status.get("notionComment") or "").strip()
        or (status.get("finalAnswer") or "").strip()
        or (status.get("summary") or "").strip()
        or "I finished the analysis, but there was no written answer in the result."
    )
    answer = _compact_bullet_answer(raw_answer) or raw_answer
    chart_lines = [
        f"- {_chart_title(chart)}"
        for chart in _selected_charts(status, "comment")
        if _chart_file_upload_id(chart)
    ]
    chart_section = "\n\nCharts attached:\n" + "\n".join(chart_lines) if chart_lines else ""
    suffix = "\n\nRequest page: request details" + chart_section
    clipped = _clip_comment_content(answer, len(suffix))
    return [
        *notion_formatting.markdown_rich_text(clipped, max_chars=len(clipped)),
        *notion_formatting.plain_rich_text("\n\nRequest page: ", max_chars=None),
        *notion_formatting.linked_rich_text("request details", request_page_url),
        *notion_formatting.markdown_rich_text(chart_section, max_chars=None),
    ]


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
            {**chart, "fileUploadId": uploads[_chart_value(chart, "url")]["id"], "fileName": uploads[_chart_value(chart, "url")]["fileName"]}
            if _chart_value(chart, "url") in uploads
            else chart
            for chart in _status_charts(status)
        ],
    }


def _comment_attachments(status: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"type": "file_upload", "file_upload_id": _chart_file_upload_id(chart)}
        for chart in _selected_charts(status, "comment")
        if _chart_file_upload_id(chart)
    ][:3]


async def _create_final_comment(token: str, discussion_id: str, status: dict[str, Any], request_page_url: str) -> None:
    attachments = _comment_attachments(status)
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
            rich_text=_final_comment_rich_text(status, request_page_url),
        )


def mint_internal_notebook_jwt(org_id: str, user_id: str | None, scopes: list[str] | None = None) -> str:
    """Mint the internal JWT used by the notebook API for org-scoped work."""
    secret = os.getenv("SIGNALPILOT_INTERNAL_JWT_SECRET") or os.getenv("SP_INTERNAL_JWT_SECRET") or load_session_jwt_secret()
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


async def _poll_analysis(request_id: str, runtime: NotebookRuntime, org_id: str, user_id: str | None) -> dict:
    max_polls = int(os.getenv("SIGNALPILOT_MAX_POLLS", "300"))
    interval_ms = int(os.getenv("SIGNALPILOT_POLL_INTERVAL_MS", "5000"))
    for _ in range(max_polls):
        status = await _call_notebook(runtime, f"/api/notion-analysis/status/{request_id}", org_id, user_id)
        if status.get("status") in ("Done", "Failed"):
            return status
        await asyncio.sleep(interval_ms / 1000)
    raise TimeoutError(f"SignalPilot analysis timed out: {request_id}")


def _require_config(config: NotionInstallationConfig) -> tuple[str, str]:
    if not config.trigger_page_id:
        raise RuntimeError("Notion installation is missing trigger_page_id")
    if not config.requests_data_source_id:
        raise RuntimeError("Notion installation is missing requests_data_source_id")
    return config.trigger_page_id, config.requests_data_source_id


async def process_routed_comment_event(
    routed: RoutedNotionInstallation,
    payload: dict,
    *,
    db: AsyncSession,
) -> NotionCommentProcessResult:
    """Run the comment-triggered Notion analysis workflow for a routed event."""
    token = routed.access_token
    trigger_page_id, requests_data_source_id = _require_config(routed.config)
    comment_id = payload.get("entity", {}).get("id")
    page_id = payload.get("data", {}).get("page_id")
    parent_block_id = payload.get("data", {}).get("parent", {}).get("id")
    if not comment_id or not page_id:
        return _ignored("missing_comment_or_page_id", event_id=payload.get("id"), comment_id=comment_id, page_id=page_id)

    block_id = parent_block_id or page_id
    comments = await notion_client.list_comments(token, block_id)
    trigger_comment = next((comment for comment in comments if comment.get("id") == comment_id), None)
    if trigger_comment is None:
        try:
            trigger_comment = await notion_client.retrieve_comment(token, str(comment_id))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return _ignored("comment_not_found", event_id=payload.get("id"), comment_id=comment_id, block_id=block_id)
            raise
    if notion_client.is_bot_comment(trigger_comment):
        return _ignored("bot_comment", event_id=payload.get("id"), comment_id=comment_id)
    if not notion_client.comment_has_page_mention(trigger_comment, trigger_page_id):
        return _ignored(
            "trigger_page_not_mentioned",
            event_id=payload.get("id"),
            comment_id=comment_id,
            trigger_page_id=trigger_page_id,
        )

    discussion_id = trigger_comment.get("discussion_id")
    prompt = notion_client.extract_comment_text(trigger_comment)
    if not discussion_id or not prompt:
        return _ignored(
            "missing_discussion_or_prompt",
            event_id=payload.get("id"),
            comment_id=comment_id,
            discussion_id=discussion_id,
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
    headline = _headline_from_prompt(prompt)
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

    await notion_client.update_page_properties(token, request_page_id, {"Status": {"rich_text": _rich_text("Analyzing")}})
    await _create_start_comment(
        token,
        discussion_id=discussion_id,
        request_page_url=request_page_url,
        event_id=payload.get("id"),
        comment_id=comment_id,
        request_page_id=request_page_id,
    )
    try:
        runtime = await ensure_notion_notebook_session(
            db,
            routed.installation.org_id,
            routed.installation.user_id,
        )
        start = await _call_notebook(
            runtime,
            "/api/notion-analysis/start",
            routed.installation.org_id,
            routed.installation.user_id,
            {
                "method": "POST",
                "json": {
                    "discussionId": discussion_id,
                    "notionRequestPageId": request_page_id,
                    "sourceUrl": source_url,
                    "requester": requester_ids,
                    "headline": headline,
                    "prompt": prompt,
                    "previousMessages": previous_messages,
                    "createdAt": created_at,
                },
            },
        )
    except Exception as exc:
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
        raise

    start_trail_url = _public_signalpilot_url(start.get("trailUrl") or "", runtime)
    await notion_client.update_page_properties(token, request_page_id, {"Trail URL": {"url": start_trail_url or None}})

    try:
        final_status = await _poll_analysis(
            str(start["requestId"]),
            runtime,
            routed.installation.org_id,
            routed.installation.user_id,
        )
    except Exception as exc:
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
        raise

    if final_status.get("status") == "Done" and not final_status.get("error"):
        uploaded_status = await _upload_chart_images_to_notion(token, final_status, runtime)
        final_status_for_notion = _with_public_chart_urls(uploaded_status, runtime)
        await notion_client.update_page_properties(
            token,
            request_page_id,
            {
                "Status": {"rich_text": _rich_text("Done")},
                "Trail URL": {"url": _public_signalpilot_url(final_status_for_notion.get("trailUrl") or start_trail_url, runtime) or None},
                "Confidence score": {"number": final_status_for_notion.get("confidenceScore")},
                "Summary": {"rich_text": _rich_text(final_status_for_notion.get("summary") or final_status_for_notion.get("finalAnswer") or "")},
            },
        )
        await _create_final_comment(token, discussion_id, final_status_for_notion, request_page_url)
        await notion_client.append_page_blocks(token, request_page_id, _analysis_detail_blocks(final_status_for_notion))
    else:
        message = final_status.get("error") or "SignalPilot analysis failed."
        await notion_client.update_page_properties(
            token,
            request_page_id,
            {"Status": {"rich_text": _rich_text("Failed")}, "Summary": {"rich_text": _rich_text(message)}},
        )
        await notion_client.append_page_blocks(token, request_page_id, _failure_detail_blocks(str(message)))
        await notion_client.create_comment(
            token,
            discussion_id=discussion_id,
            rich_text=_failure_comment_rich_text(str(message), request_page_url),
        )
    return NotionCommentProcessResult(status="processed")
