"""Notion placement helpers for SignalPilot HTML dashboards and reports."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from gateway.notion import client as notion_client
from gateway.notion import formatting as notion_formatting

DEFAULT_DASHBOARD_MAX_BYTES = 4 * 1024 * 1024
_DEFAULT_WEB_URL = "http://localhost:3200"


@dataclass(frozen=True)
class DeliverablePlacement:
    parent_block_id: str
    after_block_id: str | None = None
    archive_block_id: str | None = None


@dataclass(frozen=True)
class DeliverableInsertResult:
    block_id: str | None
    file_upload_id: str | None
    fallback_url: str | None
    archived_block_id: str | None = None


@dataclass(frozen=True)
class DeliverableReplaceResult:
    block_id: str
    file_upload_id: str


def dashboard_max_bytes() -> int:
    raw_value = os.getenv("NOTION_DASHBOARD_MAX_BYTES")
    if raw_value is None:
        return DEFAULT_DASHBOARD_MAX_BYTES
    try:
        return max(1024, int(raw_value))
    except ValueError:
        return DEFAULT_DASHBOARD_MAX_BYTES


def web_report_url(report_id: str) -> str:
    base_url = (os.getenv("SP_WEB_URL") or os.getenv("SIGNALPILOT_WEB_URL") or _DEFAULT_WEB_URL).rstrip("/")
    return f"{base_url}/reports?report={report_id}"


def html_embed_block(file_upload_id: str) -> dict[str, Any]:
    return notion_client.html_embed_block(file_upload_id)


def fallback_link_block(report_url: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                *notion_formatting.plain_rich_text("Open the SignalPilot report: ", max_chars=None),
                *notion_formatting.linked_rich_text("View report", report_url),
            ]
        },
    }


async def resolve_placement(
    token: str,
    *,
    page_id: str,
    anchor_block_id: str | None,
) -> DeliverablePlacement:
    if not anchor_block_id or notion_client.normalize_id(anchor_block_id) == notion_client.normalize_id(page_id):
        return DeliverablePlacement(parent_block_id=page_id)

    block = await notion_client.retrieve_block(token, anchor_block_id)
    parent = block.get("parent") if isinstance(block.get("parent"), dict) else {}
    parent_id = str(parent.get("page_id") or parent.get("block_id") or page_id)
    archive_block_id = anchor_block_id if notion_client.is_empty_placeholder_block(block) else None
    return DeliverablePlacement(
        parent_block_id=parent_id,
        after_block_id=anchor_block_id,
        archive_block_id=archive_block_id,
    )


async def insert_html_deliverable(
    token: str,
    *,
    page_id: str,
    anchor_block_id: str | None,
    title: str,
    html: str,
    report_id: str,
) -> DeliverableInsertResult:
    placement = await resolve_placement(token, page_id=page_id, anchor_block_id=anchor_block_id)
    html_bytes = html.encode("utf-8")
    if len(html_bytes) > dashboard_max_bytes():
        fallback_url = web_report_url(report_id)
        response = await notion_client.append_block_children(
            token,
            placement.parent_block_id,
            [fallback_link_block(fallback_url)],
            after_block_id=placement.after_block_id,
        )
        block_id = _first_result_id(response)
        archived = await _archive_placeholder(token, placement.archive_block_id)
        return DeliverableInsertResult(
            block_id=block_id,
            file_upload_id=None,
            fallback_url=fallback_url,
            archived_block_id=archived,
        )

    upload = await notion_client.upload_file(
        token,
        filename=_html_filename(title, report_id),
        content_type="text/html",
        content=html_bytes,
    )
    file_upload_id = str(upload.get("id") or "")
    if not file_upload_id:
        raise RuntimeError("Notion did not return a file upload id for HTML deliverable")
    response = await notion_client.append_block_children(
        token,
        placement.parent_block_id,
        [html_embed_block(file_upload_id)],
        after_block_id=placement.after_block_id,
    )
    block_id = _first_result_id(response)
    archived = await _archive_placeholder(token, placement.archive_block_id)
    return DeliverableInsertResult(
        block_id=block_id,
        file_upload_id=file_upload_id,
        fallback_url=None,
        archived_block_id=archived,
    )


async def replace_html_deliverable(
    token: str,
    *,
    embed_block_id: str,
    title: str,
    html: str,
    report_id: str,
) -> DeliverableReplaceResult:
    html_bytes = html.encode("utf-8")
    if len(html_bytes) > dashboard_max_bytes():
        raise ValueError("Updated Notion HTML deliverable exceeds the Notion embed size limit")

    upload = await notion_client.upload_file(
        token,
        filename=_html_filename(title, report_id),
        content_type="text/html",
        content=html_bytes,
    )
    file_upload_id = str(upload.get("id") or "")
    if not file_upload_id:
        raise RuntimeError("Notion did not return a file upload id for updated HTML deliverable")

    await notion_client.update_block(
        token,
        embed_block_id,
        {"embed": {"file_upload": {"id": file_upload_id}}},
    )
    return DeliverableReplaceResult(block_id=embed_block_id, file_upload_id=file_upload_id)


async def _archive_placeholder(token: str, block_id: str | None) -> str | None:
    if not block_id:
        return None
    try:
        await notion_client.archive_block(token, block_id)
    except Exception:
        return None
    return block_id


def _html_filename(title: str, report_id: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
    return f"{stem or 'signalpilot-report'}-{report_id[:8]}.html"


def _first_result_id(response: dict[str, Any]) -> str | None:
    results = response.get("results")
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    return str(first.get("id")) if isinstance(first, dict) and first.get("id") else None
