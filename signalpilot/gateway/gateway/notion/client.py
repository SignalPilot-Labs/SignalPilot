"""Thin Notion API client for search, fetch, and page creation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx

from gateway.notion import formatting as notion_formatting

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_AUTHORIZE_URL = "https://api.notion.com/v1/oauth/authorize"
NOTION_API_VERSION = "2026-03-11"
REQUEST_TIMEOUT = 15
SIGNALPILOT_TRIGGER_PAGE_TITLE = "SignalPilot"
SIGNALPILOT_TRIGGER_PAGE_ICON = {"type": "emoji", "emoji": "\U0001f916"}
SIGNALPILOT_INTEGRATION_PAGE_TITLE = "SignalPilot Integration"
SIGNALPILOT_REQUESTS_DATABASE_TITLE = "SignalPilot Requests"
SIGNALPILOT_INTEGRATION_PAGE_CONTENT = (
    "SignalPilot-created pages for Notion analysis requests. Keep this page shared with the SignalPilot connection."
)

logger = logging.getLogger(__name__)


def _headers(api_key: str) -> dict[str, str]:
    """Build Notion API headers."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


def http_error_summary(exc: httpx.HTTPStatusError) -> str:
    """Return a sanitized Notion API error summary safe for logs/UI."""
    response = exc.response
    request = response.request
    try:
        body = response.json()
    except ValueError:
        body = {}
    if isinstance(body, dict):
        message = str(body.get("message") or body.get("code") or response.text[:500])
    else:
        message = response.text[:500]
    path = request.url.path
    return f"Notion API {response.status_code} {request.method} {path}: {message[:500]}"


def is_comment_read_capability_error(exc: httpx.HTTPStatusError) -> bool:
    request = exc.response.request
    return (
        exc.response.status_code == 403
        and request.method.upper() == "GET"
        and request.url.path.rstrip("/") == "/v1/comments"
    )


def _multipart_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_API_VERSION,
    }


def normalize_id(value: str) -> str:
    return value.replace("-", "")


def _extract_page_title(page: dict) -> str:
    """Extract the title from a Notion page object."""
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            title_parts = prop.get("title", [])
            return "".join(t.get("plain_text", "") for t in title_parts)
    return "(untitled)"


def _normalized_title(value: str) -> str:
    return " ".join(value.split()).casefold()


def _is_signalpilot_integration_page(page: dict) -> bool:
    return _normalized_title(_extract_page_title(page)) == _normalized_title(SIGNALPILOT_INTEGRATION_PAGE_TITLE)


def _plain_text(content: str) -> dict:
    return {"type": "text", "text": {"content": content[:2000]}}


def _title(content: str) -> list[dict]:
    return [_plain_text(content)]


def _rich_text(content: str) -> list[dict]:
    if not content:
        return []
    return notion_formatting.plain_rich_text(content)


def _parent_payload(parent_page_id: str | None) -> dict:
    if parent_page_id:
        return {"type": "page_id", "page_id": parent_page_id}
    return {"type": "workspace", "workspace": True}


REQUEST_DATABASE_PROPERTIES: dict[str, dict] = {
    "Request": {"title": {}},
    "Source": {"url": {}},
    "Trail URL": {"url": {}},
    "Confidence score": {"rich_text": {}},
    "Status": {"rich_text": {}},
    "Created at": {"date": {}},
    "Requester": {"select": {"options": []}},
    "Summary": {"rich_text": {}},
    "Escalated to": {"rich_text": {}},
}


def build_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Build Notion's public integration authorization URL."""
    query = urlencode(
        {
            "owner": "user",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
    )
    return f"{NOTION_AUTHORIZE_URL}?{query}"


async def exchange_oauth_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict:
    """Exchange an OAuth authorization code for Notion tokens."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.post(
            f"{NOTION_API_BASE}/oauth/token",
            auth=httpx.BasicAuth(client_id, client_secret),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Notion-Version": NOTION_API_VERSION,
            },
            json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        response.raise_for_status()
        return response.json()


async def refresh_oauth_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> dict:
    """Refresh a Notion OAuth token."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.post(
            f"{NOTION_API_BASE}/oauth/token",
            auth=httpx.BasicAuth(client_id, client_secret),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Notion-Version": NOTION_API_VERSION,
            },
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        response.raise_for_status()
        return response.json()


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
                client,
                headers,
                block["id"],
                depth + 1,
                counter=counter,
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
            client,
            _headers(api_key),
            page_id,
            depth=0,
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
    """Convert text to structured Notion blocks."""
    return notion_formatting.markdown_blocks(text)


async def create_page(
    api_key: str,
    parent_page_id: str | None,
    title: str,
    content: str,
    icon: dict[str, str] | None = None,
) -> dict[str, str]:
    """Create a page under a parent page, or privately at workspace level.

    Args:
        api_key: Notion internal integration token.
        parent_page_id: The parent page ID, or None for workspace-private content.
        title: Page title.
        content: Plain text content for the page body.
        icon: Optional Notion page icon object.

    Returns:
        Dict with keys: id, title, url.
    """
    blocks = _text_to_blocks(content)
    body = {
        "parent": _parent_payload(parent_page_id),
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}],
            },
        },
        "children": blocks[:100],  # Notion limit: 100 blocks per request
    }
    if icon:
        body["icon"] = icon

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        r = await client.post(
            f"{NOTION_API_BASE}/pages",
            headers=_headers(api_key),
            json=body,
        )
        r.raise_for_status()
        data = r.json()

    return {
        "id": data.get("id", ""),
        "title": title,
        "url": data.get("url", ""),
    }


def _page_parent_page_id(page: dict) -> str | None:
    parent = page.get("parent")
    if not isinstance(parent, dict) or parent.get("type") != "page_id":
        return None
    value = parent.get("page_id")
    return str(value) if value else None


async def notion_json(
    api_key: str,
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    params: dict | None = None,
) -> dict:
    """Perform a Notion API request and return JSON."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.request(
            method,
            f"{NOTION_API_BASE}{path}",
            headers=_headers(api_key),
            json=json_body,
            params=params,
        )
        response.raise_for_status()
        return response.json()


async def list_parent_pages(api_key: str, query: str | None = None) -> list[dict[str, str]]:
    """List pages visible to an OAuth installation for setup."""
    pages = await search_visible_page_objects(api_key, query=query)
    return [
        {
            "id": page.get("id", ""),
            "title": _extract_page_title(page),
            "url": page.get("url", ""),
        }
        for page in pages
        if page.get("id")
    ]


async def search_visible_page_objects(api_key: str, query: str | None = None, page_size: int = 50) -> list[dict]:
    """Return raw page objects visible to an OAuth installation."""
    payload: dict = {
        "filter": {"value": "page", "property": "object"},
        "page_size": page_size,
    }
    if query:
        payload["query"] = query
    data = await notion_json(api_key, "POST", "/search", json_body=payload)
    pages = data.get("results", [])
    return [page for page in pages if isinstance(page, dict) and page.get("id")]


async def list_block_children(api_key: str, block_id: str) -> list[dict]:
    """List all direct block children with pagination."""
    children: list[dict] = []
    cursor: str | None = None
    while True:
        params: dict[str, str | int] = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        data = await notion_json(api_key, "GET", f"/blocks/{block_id}/children", params=params)
        children.extend(data.get("results", []))
        if not data.get("has_more"):
            return children
        cursor = data.get("next_cursor")
        if not cursor:
            return children


async def update_page_icon(api_key: str, page_id: str, icon: dict[str, str]) -> None:
    """Set the icon on an existing Notion page."""
    await notion_json(api_key, "PATCH", f"/pages/{page_id}", json_body={"icon": icon})


async def ensure_child_page(
    api_key: str,
    parent_page_id: str | None,
    title: str = SIGNALPILOT_TRIGGER_PAGE_TITLE,
    content: str = "Mention this page in a Notion comment to start SignalPilot analysis.",
    icon: dict[str, str] | None = None,
) -> dict[str, str]:
    """Find or create the mentionable SignalPilot trigger page."""
    if parent_page_id is None:
        return await create_page(
            api_key,
            None,
            title,
            content,
            icon=icon,
        )

    for block in await list_block_children(api_key, parent_page_id):
        if block.get("type") == "child_page" and block.get("child_page", {}).get("title") == title:
            page_id = block.get("id", "")
            if icon and page_id:
                await update_page_icon(api_key, page_id, icon)
            return {
                "id": page_id,
                "title": title,
                "url": f"https://www.notion.so/{normalize_id(page_id)}",
            }

    return await create_page(
        api_key,
        parent_page_id,
        title,
        content,
        icon=icon,
    )


async def retrieve_database(api_key: str, database_id: str) -> dict:
    return await notion_json(api_key, "GET", f"/databases/{database_id}")


def _database_data_source_id(database: dict) -> str | None:
    data_sources = database.get("data_sources")
    if isinstance(data_sources, list) and data_sources:
        first = data_sources[0]
        if isinstance(first, dict) and first.get("id"):
            return str(first["id"])
    initial = database.get("initial_data_source")
    if isinstance(initial, dict) and initial.get("id"):
        return str(initial["id"])
    return None


async def create_requests_database(
    api_key: str,
    parent_page_id: str | None,
    title: str = SIGNALPILOT_REQUESTS_DATABASE_TITLE,
) -> tuple[str, str]:
    """Create the worker-compatible SignalPilot Requests database."""
    body = {
        "parent": _parent_payload(parent_page_id),
        "title": _title(title),
        "initial_data_source": {
            "properties": REQUEST_DATABASE_PROPERTIES,
        },
    }
    if parent_page_id:
        body["is_inline"] = True
    data = await notion_json(
        api_key,
        "POST",
        "/databases",
        json_body=body,
    )
    database_id = data.get("id", "")
    data_source_id = _database_data_source_id(data)
    if not data_source_id and database_id:
        data_source_id = _database_data_source_id(await retrieve_database(api_key, database_id))
    if not database_id or not data_source_id:
        raise ValueError("Notion did not return a database_id and data_source_id for SignalPilot Requests")
    return database_id, data_source_id


async def ensure_requests_database(
    api_key: str,
    parent_page_id: str | None,
    title: str = SIGNALPILOT_REQUESTS_DATABASE_TITLE,
) -> tuple[str, str]:
    """Find or create the SignalPilot Requests database and return database/data-source IDs."""
    if parent_page_id is None:
        return await create_requests_database(api_key, None, title)

    for block in await list_block_children(api_key, parent_page_id):
        if block.get("type") == "child_database" and block.get("child_database", {}).get("title") == title:
            database_id = block.get("id", "")
            database = await retrieve_database(api_key, database_id)
            data_source_id = _database_data_source_id(database)
            if not data_source_id:
                raise ValueError(f"Existing Notion database {database_id} has no data source")
            return database_id, data_source_id
    return await create_requests_database(api_key, parent_page_id, title)


async def provision_signalpilot_resources(api_key: str, parent_page_id: str | None = None) -> dict[str, str | None]:
    """Create/fetch all Notion resources needed by SignalPilot analysis."""
    if not parent_page_id:
        raise ValueError(
            "Notion parent_page_id is required; workspace-level provisioning creates resources in Private."
        )
    trigger_page = await ensure_child_page(api_key, parent_page_id, icon=SIGNALPILOT_TRIGGER_PAGE_ICON)
    database_id, data_source_id = await ensure_requests_database(api_key, parent_page_id)
    return {
        "parent_page_id": parent_page_id,
        "trigger_page_id": trigger_page["id"],
        "requests_database_page_id": database_id,
        "requests_data_source_id": data_source_id,
    }


async def provision_signalpilot_resources_auto(api_key: str) -> dict[str, str | None]:
    """Create/fetch SignalPilot resources using pages exposed by the Notion install."""
    integration_pages = await search_visible_page_objects(
        api_key,
        query=SIGNALPILOT_INTEGRATION_PAGE_TITLE,
        page_size=10,
    )
    for page in integration_pages:
        if _is_signalpilot_integration_page(page):
            return await provision_signalpilot_resources(api_key, str(page["id"]))

    pages = await search_visible_page_objects(api_key, page_size=50)
    for page in pages:
        parent_page_id = _page_parent_page_id(page)
        if parent_page_id:
            container_page = await ensure_child_page(
                api_key,
                parent_page_id,
                SIGNALPILOT_INTEGRATION_PAGE_TITLE,
                SIGNALPILOT_INTEGRATION_PAGE_CONTENT,
            )
            return await provision_signalpilot_resources(api_key, container_page["id"])

    raise ValueError(
        f"Create a Notion page named {SIGNALPILOT_INTEGRATION_PAGE_TITLE!r} in the workspace or teamspace "
        "shared with SignalPilot, make sure it is shared with the SignalPilot connection, then run provisioning again."
    )


async def provision_signalpilot_resources_for_sibling(api_key: str, sibling_page_id: str) -> dict[str, str | None]:
    """Create/fetch the integration container beside a selected page."""
    if not sibling_page_id:
        raise ValueError("Notion sibling_page_id is required")
    sibling_page = await retrieve_page(api_key, sibling_page_id)
    parent_page_id = _page_parent_page_id(sibling_page)
    if not parent_page_id:
        if _extract_page_title(sibling_page).casefold() == SIGNALPILOT_INTEGRATION_PAGE_TITLE.casefold():
            return await provision_signalpilot_resources(api_key, sibling_page_id)
        raise ValueError(
            "Selected Notion page does not expose a page parent. "
            f"Choose a page whose parent is visible to the SignalPilot connection, or choose "
            f"the existing {SIGNALPILOT_INTEGRATION_PAGE_TITLE!r} page."
        )
    container_page = await ensure_child_page(
        api_key,
        parent_page_id,
        SIGNALPILOT_INTEGRATION_PAGE_TITLE,
        SIGNALPILOT_INTEGRATION_PAGE_CONTENT,
    )
    return await provision_signalpilot_resources(api_key, container_page["id"])


async def retrieve_page(api_key: str, page_id: str) -> dict:
    return await notion_json(api_key, "GET", f"/pages/{page_id}")


async def retrieve_block(api_key: str, block_id: str) -> dict:
    return await notion_json(api_key, "GET", f"/blocks/{block_id}")


async def query_request_page_by_source(
    api_key: str,
    data_source_id: str,
    source_url: str,
) -> dict[str, str] | None:
    data = await notion_json(
        api_key,
        "POST",
        f"/data_sources/{data_source_id}/query",
        json_body={
            "filter": {
                "property": "Source",
                "url": {"equals": source_url},
            },
            "page_size": 1,
        },
    )
    results = data.get("results", [])
    if not results:
        return None
    first = results[0]
    return {
        "id": first.get("id", ""),
        "url": first.get("url") or f"https://www.notion.so/{normalize_id(first.get('id', ''))}",
    }


async def create_request_page(
    api_key: str,
    data_source_id: str,
    *,
    headline: str,
    source_url: str,
    requester_id: str,
    prompt: str,
    created_at: str,
) -> dict[str, str]:
    body = {
        "parent": {"type": "data_source_id", "data_source_id": data_source_id},
        "properties": _request_page_properties(
            headline=headline,
            source_url=source_url,
            requester_id=requester_id,
            prompt=prompt,
            created_at=created_at,
            use_date_created_at=True,
        ),
    }
    try:
        data = await notion_json(
            api_key,
            "POST",
            "/pages",
            json_body=body,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 400:
            raise
        body["properties"] = _request_page_properties(
            headline=headline,
            source_url=source_url,
            requester_id=requester_id,
            prompt=prompt,
            created_at=created_at,
            use_date_created_at=False,
        )
        data = await notion_json(
            api_key,
            "POST",
            "/pages",
            json_body=body,
        )
    return {
        "id": data.get("id", ""),
        "url": data.get("url") or f"https://www.notion.so/{normalize_id(data.get('id', ''))}",
    }


def _request_page_properties(
    *,
    headline: str,
    source_url: str,
    requester_id: str,
    prompt: str,
    created_at: str,
    use_date_created_at: bool,
) -> dict:
    created_at_property = (
        {"date": {"start": created_at}}
        if use_date_created_at
        else {"rich_text": _rich_text(_created_at_display(created_at))}
    )
    return {
        "Request": {"title": _title(headline)},
        "Source": {"url": source_url},
        "Trail URL": {"url": None},
        "Confidence score": {"rich_text": []},
        "Status": {"rich_text": _rich_text("New")},
        "Created at": created_at_property,
        "Requester": {"select": {"name": requester_id[:100] or "Unknown"}},
        "Summary": {"rich_text": _rich_text(prompt)},
        "Escalated to": {"rich_text": []},
    }


def _created_at_display(created_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return created_at
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC)
        zone = " UTC"
    else:
        zone = ""
    return f"{parsed:%b} {parsed.day}, {parsed:%Y %H:%M}{zone}"


async def update_page_properties(api_key: str, page_id: str, properties: dict) -> dict:
    return await notion_json(api_key, "PATCH", f"/pages/{page_id}", json_body={"properties": properties})


async def append_page_blocks(api_key: str, page_id: str, children: list[dict]) -> dict:
    if not children:
        return {"results": []}
    return await notion_json(api_key, "PATCH", f"/blocks/{page_id}/children", json_body={"children": children[:100]})


async def list_comments(api_key: str, block_id: str) -> list[dict]:
    data = await notion_json(api_key, "GET", "/comments", params={"block_id": block_id, "page_size": 100})
    return data.get("results", [])


async def retrieve_comment(api_key: str, comment_id: str) -> dict:
    return await notion_json(api_key, "GET", f"/comments/{comment_id}")


async def upload_file(api_key: str, *, filename: str, content_type: str, content: bytes) -> dict:
    created = await notion_json(
        api_key,
        "POST",
        "/file_uploads",
        json_body={
            "mode": "single_part",
            "filename": filename,
            "content_type": content_type,
        },
    )
    upload_id = created.get("id")
    if not upload_id:
        raise RuntimeError("Notion did not return a file upload id")

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.post(
            f"{NOTION_API_BASE}/file_uploads/{upload_id}/send",
            headers=_multipart_headers(api_key),
            files={"file": (filename, content, content_type)},
        )
        response.raise_for_status()
        sent = response.json()
    return sent or created


async def create_comment(
    api_key: str,
    *,
    discussion_id: str,
    rich_text: list[dict],
    attachments: list[dict] | None = None,
) -> dict:
    body: dict = {
        "discussion_id": discussion_id,
        "rich_text": rich_text,
    }
    if attachments:
        body["attachments"] = attachments[:3]
    return await notion_json(
        api_key,
        "POST",
        "/comments",
        json_body=body,
    )


async def update_comment(
    api_key: str,
    comment_id: str,
    *,
    rich_text: list[dict],
) -> dict:
    return await notion_json(
        api_key,
        "PATCH",
        f"/comments/{comment_id}",
        json_body={"rich_text": rich_text},
    )


async def delete_comment(api_key: str, comment_id: str) -> dict:
    return await notion_json(
        api_key,
        "DELETE",
        f"/comments/{comment_id}",
    )


def comment_has_page_mention(comment: dict, page_id: str) -> bool:
    for item in comment.get("rich_text") or []:
        mention = item.get("mention") if item.get("type") == "mention" else None
        page = mention.get("page") if isinstance(mention, dict) and mention.get("type") == "page" else None
        if isinstance(page, dict) and normalize_id(str(page.get("id", ""))) == normalize_id(page_id):
            return True
    return False


def extract_comment_text(comment: dict) -> str:
    parts = []
    for item in comment.get("rich_text") or []:
        if item.get("type") == "mention":
            continue
        parts.append(item.get("plain_text") or "")
    return "".join(parts).strip()


def is_bot_comment(comment: dict) -> bool:
    return comment.get("created_by", {}).get("type") == "bot"


async def page_belongs_to_scope(
    api_key: str,
    page_id: str,
    *,
    parent_page_id: str | None,
    trigger_page_id: str | None,
    requests_data_source_id: str | None,
    requests_database_page_id: str | None,
    max_depth: int = 8,
) -> bool:
    """Best-effort ancestry check used to route webhook events to one install."""
    if parent_page_id is None:
        return True

    target_pages = {normalize_id(p) for p in (parent_page_id, trigger_page_id, requests_database_page_id) if p}
    target_data_sources = {normalize_id(p) for p in (requests_data_source_id,) if p}
    current_id = page_id
    for _ in range(max_depth):
        if normalize_id(current_id) in target_pages:
            return True
        try:
            page = await retrieve_page(api_key, current_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
        parent = page.get("parent") or {}
        parent_type = parent.get("type")
        if parent_type == "data_source_id":
            return normalize_id(str(parent.get("data_source_id", ""))) in target_data_sources
        if parent_type == "database_id":
            return normalize_id(str(parent.get("database_id", ""))) in target_pages
        if parent_type == "page_id":
            current_id = str(parent.get("page_id", ""))
            continue
        if parent_type == "block_id":
            current_id = str(parent.get("block_id", ""))
            if normalize_id(current_id) in target_pages:
                return True
            try:
                block = await retrieve_block(api_key, current_id)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return False
                raise
            block_parent = block.get("parent") or {}
            if block_parent.get("type") == "page_id":
                current_id = str(block_parent.get("page_id", ""))
                continue
        return False
    return False


async def with_token_refresh(
    operation: Callable[[str], Awaitable[dict | list[dict] | None]],
    access_token: str,
    refresh: Callable[[], Awaitable[str | None]] | None,
) -> dict | list[dict] | None:
    """Run a Notion operation and refresh once on 401 if a refresh callback exists."""
    try:
        return await operation(access_token)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 401 or refresh is None:
            raise
        refreshed = await refresh()
        if not refreshed:
            raise
        return await operation(refreshed)
