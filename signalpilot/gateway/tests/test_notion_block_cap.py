"""Tests for the MAX_TOTAL_BLOCKS cap in _fetch_blocks_recursive."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from gateway.notion.client import MAX_TOTAL_BLOCKS, _fetch_blocks_recursive


def _make_blocks_response(count: int, has_children: bool) -> dict:
    """Build a fake Notion blocks response with paragraph blocks."""
    results = []
    for i in range(count):
        results.append({
            "id": f"block-{i}",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"plain_text": f"line {i}"}],
            },
            "has_children": has_children,
        })
    return {"results": results}


class TestNotionBlockCap:
    @pytest.mark.asyncio
    async def test_fetch_blocks_recursive_caps_at_max_total_blocks(self) -> None:
        """Blocks fetched from a deep/wide tree must not exceed MAX_TOTAL_BLOCKS."""
        call_count = 0

        async def mock_get(url: str, **kwargs) -> MagicMock:
            nonlocal call_count
            call_count += 1
            response = MagicMock(spec=httpx.Response)
            response.raise_for_status = MagicMock()
            # 100 blocks per call, every block has children (creates unbounded tree)
            response.json.return_value = _make_blocks_response(100, has_children=True)
            return response

        client = MagicMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(side_effect=mock_get)
        headers: dict[str, str] = {}

        lines, child_pages = await _fetch_blocks_recursive(client, headers, "root", 0)

        # Lines must be bounded by the block cap
        assert len(lines) <= MAX_TOTAL_BLOCKS
        # API calls should be far fewer than an unbounded traversal would require
        assert call_count < 25

    @pytest.mark.asyncio
    async def test_fetch_blocks_recursive_under_cap_returns_all(self) -> None:
        """When total blocks are below cap, all blocks should be returned."""
        async def mock_get(url: str, **kwargs) -> MagicMock:
            response = MagicMock(spec=httpx.Response)
            response.raise_for_status = MagicMock()
            response.json.return_value = _make_blocks_response(10, has_children=False)
            return response

        client = MagicMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(side_effect=mock_get)
        headers: dict[str, str] = {}

        lines, child_pages = await _fetch_blocks_recursive(client, headers, "root", 0)

        assert len(lines) == 10
        assert child_pages == []
