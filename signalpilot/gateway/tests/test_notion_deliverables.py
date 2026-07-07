from __future__ import annotations

import pytest

from gateway.notion import client as notion_client
from gateway.notion import dashboards


def test_html_embed_block_uses_file_upload_shape() -> None:
    assert dashboards.html_embed_block("upload-1") == {
        "object": "block",
        "type": "embed",
        "embed": {
            "type": "file_upload",
            "file_upload": {"id": "upload-1"},
        },
    }


@pytest.mark.asyncio
async def test_empty_anchor_inserts_after_then_archives(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def retrieve_block(_token, block_id):
        assert block_id == "anchor-1"
        return {
            "id": "anchor-1",
            "type": "paragraph",
            "paragraph": {"rich_text": []},
            "has_children": False,
            "parent": {"type": "page_id", "page_id": "page-1"},
        }

    async def upload_file(_token, *, filename, content_type, content):
        calls.append(("upload", filename, content_type, content))
        return {"id": "upload-1"}

    async def append_block_children(_token, block_id, children, *, after_block_id=None):
        calls.append(("append", block_id, children, after_block_id))
        return {"results": [{"id": "embed-1"}]}

    async def archive_block(_token, block_id):
        calls.append(("archive", block_id))
        return {"id": block_id}

    monkeypatch.setattr(notion_client, "retrieve_block", retrieve_block)
    monkeypatch.setattr(notion_client, "upload_file", upload_file)
    monkeypatch.setattr(notion_client, "append_block_children", append_block_children)
    monkeypatch.setattr(notion_client, "archive_block", archive_block)

    result = await dashboards.insert_html_deliverable(
        "token",
        page_id="page-1",
        anchor_block_id="anchor-1",
        title="Revenue Dashboard",
        html="<html></html>",
        report_id="report-1",
    )

    assert result.block_id == "embed-1"
    assert result.file_upload_id == "upload-1"
    assert calls[1][0] == "append"
    assert calls[1][3] == "anchor-1"
    assert calls[2] == ("archive", "anchor-1")


@pytest.mark.asyncio
async def test_oversize_html_inserts_report_link_without_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    async def retrieve_block(_token, _block_id):
        return {
            "id": "anchor-1",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"plain_text": "Prompt"}]},
            "has_children": False,
            "parent": {"type": "page_id", "page_id": "page-1"},
        }

    async def upload_file(*_args, **_kwargs):
        raise AssertionError("oversize fallback should not upload HTML")

    async def append_block_children(_token, block_id, children, *, after_block_id=None):
        calls.append((block_id, children, after_block_id))
        return {"results": [{"id": "fallback-1"}]}

    monkeypatch.setenv("NOTION_DASHBOARD_MAX_BYTES", "1000")
    monkeypatch.setenv("SP_WEB_URL", "https://app.test")
    monkeypatch.setattr(notion_client, "retrieve_block", retrieve_block)
    monkeypatch.setattr(notion_client, "upload_file", upload_file)
    monkeypatch.setattr(notion_client, "append_block_children", append_block_children)

    result = await dashboards.insert_html_deliverable(
        "token",
        page_id="page-1",
        anchor_block_id="anchor-1",
        title="Large Dashboard",
        html="x" * 2000,
        report_id="report-1",
    )

    assert result.block_id == "fallback-1"
    assert result.file_upload_id is None
    assert result.fallback_url == "https://app.test/reports?report=report-1"
    assert calls[0][0] == "page-1"
    assert calls[0][2] == "anchor-1"
    assert calls[0][1][0]["type"] == "paragraph"
