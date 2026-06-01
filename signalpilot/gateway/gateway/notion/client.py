"""Thin Notion API client for search, fetch, and page creation."""

from __future__ import annotations

import logging

import httpx

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_API_VERSION = "2022-06-28"
REQUEST_TIMEOUT = 15

logger = logging.getLogger(__name__)


def _headers(api_key: str) -> dict[str, str]:
    """Build Notion API headers."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }



def _extract_page_title(page: dict) -> str:
    """Extract the title from a Notion page object."""
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            title_parts = prop.get("title", [])
            return "".join(t.get("plain_text", "") for t in title_parts)
    return "(untitled)"


async def test_connection(api_key: str) -> tuple[bool, str]:
    """Test that the API key is valid by fetching the current user."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            r = await client.get(f"{NOTION_API_BASE}/users/me", headers=_headers(api_key))
            if r.status_code == 200:
                return True, "ok"
            return False, f"Notion API returned {r.status_code}: {r.text[:200]}"
        except httpx.HTTPError as e:
            return False, f"Connection failed: {e}"


async def search_pages(
    api_key: str,
    query: str,
) -> list[dict[str, str]]:
    """Search Notion pages visible to the integration.

    Args:
        api_key: Notion internal integration token.
        query: Search query string.

    Returns:
        List of dicts with keys: id, title, url.
    """
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        r = await client.post(
            f"{NOTION_API_BASE}/search",
            headers=_headers(api_key),
            json={
                "query": query,
                "filter": {"value": "page", "property": "object"},
                "page_size": 20,
            },
        )
        r.raise_for_status()
        results = r.json().get("results", [])

    # Notion search is already scoped to pages shared with the integration.
    # No additional filtering needed — the integration token only sees
    # what the user explicitly shared in Notion.
    return [
        {
            "id": page.get("id", ""),
            "title": _extract_page_title(page),
            "url": page.get("url", ""),
        }
        for page in results
    ]


MAX_DEPTH = 4
MAX_CONTENT_CHARS = 8000
MAX_TOTAL_BLOCKS = 2000


async def _fetch_blocks_recursive(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    block_id: str,
    depth: int,
    counter: list[int] | None = None,
) -> tuple[list[str], list[dict[str, str]]]:
    """Recursively fetch all text and child pages from a block tree."""
    if counter is None:
        counter = [0]

    if depth > MAX_DEPTH:
        return [], []

    r = await client.get(
        f"{NOTION_API_BASE}/blocks/{block_id}/children",
        headers=headers,
        params={"page_size": 100},
    )
    r.raise_for_status()
    blocks = r.json().get("results", [])

    lines: list[str] = []
    child_pages: list[dict[str, str]] = []

    for block in blocks:
        if counter[0] >= MAX_TOTAL_BLOCKS:
            break

        counter[0] += 1

        block_type = block.get("type", "")

        if block_type == "child_page":
            child_title = block.get("child_page", {}).get("title", "(untitled)")
            child_pages.append({"id": block.get("id", ""), "title": child_title})
            continue

        type_data = block.get(block_type, {})
        for rt in type_data.get("rich_text", []):
            text = rt.get("plain_text", "").strip()
            if text:
                lines.append(text)

        if block.get("has_children", False):
            sub_lines, sub_children = await _fetch_blocks_recursive(
                client, headers, block["id"], depth + 1, counter=counter,
            )
            lines.extend(sub_lines)
            child_pages.extend(sub_children)

    return lines, child_pages


async def fetch_page(api_key: str, page_id: str) -> dict[str, str | list[dict[str, str]]]:
    """Fetch a Notion page's title, text content, and child pages.

    Recursively fetches nested blocks (transcriptions, toggles, etc.)
    up to MAX_DEPTH levels deep.

    Args:
        api_key: Notion internal integration token.
        page_id: The page ID to fetch.

    Returns:
        Dict with keys: id, title, content, url, child_pages.
    """
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        page_r = await client.get(
            f"{NOTION_API_BASE}/pages/{page_id}",
            headers=_headers(api_key),
        )
        page_r.raise_for_status()
        page_data = page_r.json()
        title = _extract_page_title(page_data)

        lines, child_pages = await _fetch_blocks_recursive(
            client, _headers(api_key), page_id, depth=0,
        )
        content = "\n".join(lines)[:MAX_CONTENT_CHARS]

    return {
        "id": page_id,
        "title": title,
        "content": content,
        "url": page_data.get("url", ""),
        "child_pages": child_pages,
    }


def _text_to_blocks(text: str) -> list[dict]:
    """Convert plain text to Notion paragraph blocks.

    Splits on double newlines for paragraphs, single newlines within
    a paragraph become part of the same block.
    """
    paragraphs = text.split("\n\n")
    blocks: list[dict] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": para[:2000]}}],
            },
        })
    return blocks


async def create_page(
    api_key: str,
    parent_page_id: str,
    title: str,
    content: str,
) -> dict[str, str]:
    """Create a child page under the configured report parent.

    Args:
        api_key: Notion internal integration token.
        parent_page_id: The parent page ID (report destination).
        title: Page title.
        content: Plain text content for the page body.

    Returns:
        Dict with keys: id, title, url.
    """
    blocks = _text_to_blocks(content)

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        r = await client.post(
            f"{NOTION_API_BASE}/pages",
            headers=_headers(api_key),
            json={
                "parent": {"page_id": parent_page_id},
                "properties": {
                    "title": {
                        "title": [{"type": "text", "text": {"content": title}}],
                    },
                },
                "children": blocks[:100],  # Notion limit: 100 blocks per request
            },
        )
        r.raise_for_status()
        data = r.json()

    return {
        "id": data.get("id", ""),
        "title": title,
        "url": data.get("url", ""),
    }
