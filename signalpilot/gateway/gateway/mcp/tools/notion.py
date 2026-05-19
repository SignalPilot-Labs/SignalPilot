"""Notion integration tools: notion_search, notion_fetch_page, notion_create_page."""

from __future__ import annotations

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.notion.client import create_page, fetch_page, search_pages


class _ResolvedIntegration:
    """Resolved Notion integration with decrypted API key."""

    def __init__(self, api_key: str, search_page_ids: list[str], report_parent_page_id: str | None) -> None:
        self.api_key = api_key
        self.search_page_ids = search_page_ids
        self.report_parent_page_id = report_parent_page_id


async def _resolve_integration(store: object, integration_name: str) -> _ResolvedIntegration | str:
    """Resolve a Notion integration. Returns error string on failure."""
    info = await store.get_notion_integration(integration_name)  # type: ignore[union-attr]
    if not info:
        available = [i.name for i in await store.list_notion_integrations()]  # type: ignore[union-attr]
        return f"Error: Notion integration '{integration_name}' not found. Available: {available}"
    api_key = await store.get_notion_api_key(integration_name)  # type: ignore[union-attr]
    if not api_key:
        return f"Error: No API key stored for integration '{integration_name}'"
    return _ResolvedIntegration(api_key, info.search_page_ids, info.report_parent_page_id)


@audited_tool(mcp)
async def notion_search(integration_name: str, query: str) -> str:
    """
    Search Notion pages within the configured search scope.

    Searches pages under the root pages configured for this integration.
    Use list_database_connections to see available Notion integrations.

    Args:
        integration_name: Name of a configured Notion integration
        query: Search query (keywords, terms, phrases)

    Returns:
        Matching page titles, IDs, and URLs as formatted text.
    """
    if not query or not query.strip():
        return "Error: query cannot be empty."

    async with _store_session() as store:
        resolved = await _resolve_integration(store, integration_name)
        if isinstance(resolved, str):
            return resolved

    try:
        results = await search_pages(resolved.api_key, query.strip())
    except Exception as e:
        return f"Error: Notion search failed: {e}"

    if not results:
        return f"No pages found matching '{query}' within the configured search scope."

    lines = [f"Found {len(results)} page(s) matching '{query}':\n"]
    for page in results:
        lines.append(f"- {page['title']}")
        lines.append(f"  ID: {page['id']}")
        lines.append(f"  URL: {page['url']}")
    return "\n".join(lines)


@audited_tool(mcp)
async def notion_fetch_page(integration_name: str, page_id: str) -> str:
    """
    Fetch the full content of a Notion page.

    Returns the page title and text content. Use notion_search first to
    find relevant page IDs.

    Args:
        integration_name: Name of a configured Notion integration
        page_id: The Notion page ID to fetch

    Returns:
        Page title and content as formatted text.
    """
    if not page_id or not page_id.strip():
        return "Error: page_id cannot be empty."

    async with _store_session() as store:
        resolved = await _resolve_integration(store, integration_name)
        if isinstance(resolved, str):
            return resolved

    try:
        page = await fetch_page(resolved.api_key, page_id.strip())
    except Exception as e:
        return f"Error: Failed to fetch page: {e}"

    lines = [
        f"Title: {page['title']}",
        f"URL: {page['url']}",
        "",
    ]
    if page["content"]:
        lines.append(page["content"])
    child_pages = page.get("child_pages", [])
    if child_pages:
        lines.append("")
        lines.append(f"Child pages ({len(child_pages)}):")
        for child in child_pages:
            lines.append(f"  - {child['title']}  (ID: {child['id']})")
    if not page["content"] and not child_pages:
        lines.append("(empty page)")
    return "\n".join(lines)


@audited_tool(mcp)
async def notion_create_page(integration_name: str, title: str, content: str) -> str:
    """
    Create a page under the configured report destination.

    The page is created as a child of the report parent page configured
    for this integration. The AI cannot choose where to write — only the
    pre-configured destination is allowed.

    Args:
        integration_name: Name of a configured Notion integration
        title: Page title
        content: Plain text content for the page body

    Returns:
        Created page title, ID, and URL as formatted text.
    """
    if not title or not title.strip():
        return "Error: title cannot be empty."
    if not content or not content.strip():
        return "Error: content cannot be empty."

    async with _store_session() as store:
        resolved = await _resolve_integration(store, integration_name)
        if isinstance(resolved, str):
            return resolved

    if not resolved.report_parent_page_id:
        return "Error: No report destination configured. Set report_parent_page_id on this integration."

    try:
        page = await create_page(resolved.api_key, resolved.report_parent_page_id, title.strip(), content.strip())
    except Exception as e:
        return f"Error: Failed to create page: {e}"

    lines = [
        "Page created successfully:",
        f"  Title: {page['title']}",
        f"  ID: {page['id']}",
        f"  URL: {page['url']}",
    ]
    return "\n".join(lines)
