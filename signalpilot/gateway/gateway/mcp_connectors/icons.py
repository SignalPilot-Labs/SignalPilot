"""Provider icons for remote connectors, fetched server-side.

The web app's CSP only allows images from itself and the gateway, so the
gateway fetches a connector host's icon and serves the bytes. Every request
goes through the SSRF guard (``safe_async_client``): ``https://<host>/favicon.ico``
first, then the first ``<link rel="icon">`` of ``https://<host>/`` when that
page is small. Only ``image/*`` bodies up to 256 KB are accepted. Results are
cached in-process per origin: 24 h for an icon, 1 h for a miss.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from gateway.mcp_connectors.ssrf import PROBE_TIMEOUT_SECONDS, UnsafeUrlError, safe_async_client

logger = logging.getLogger(__name__)

ICON_MAX_BYTES = 256 * 1024
HTML_MAX_BYTES = 256 * 1024
ICON_TTL_SECONDS = 24 * 60 * 60
MISS_TTL_SECONDS = 60 * 60

_LINK_TAG = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_REL_ATTR = re.compile(r"""\brel\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.IGNORECASE)
_HREF_ATTR = re.compile(r"""\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.IGNORECASE)


@dataclass(frozen=True)
class Icon:
    content: bytes
    content_type: str


_cache: dict[str, tuple[float, Icon | None]] = {}
_locks: dict[str, asyncio.Lock] = {}


def make_client() -> httpx.AsyncClient:
    """Guarded client for icon fetches (tests replace this to inject a mock transport)."""
    return safe_async_client(timeout=httpx.Timeout(PROBE_TIMEOUT_SECONDS))


def icon_origin(url: str | None) -> str | None:
    """``https://host[:port]/`` for a remote connector URL; None when there is no host."""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").strip().lower()
    if not host:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    return f"https://{host}:{port}/" if port and port != 443 else f"https://{host}/"


def clear_cache() -> None:
    _cache.clear()


def _attr(pattern: re.Pattern[str], tag: str) -> str | None:
    match = pattern.search(tag)
    if match is None:
        return None
    return next((group for group in match.groups() if group is not None), None)


def find_link_icon(page: str, base_url: str) -> str | None:
    """Absolute URL of the first ``<link rel="... icon ...">`` in ``page``."""
    for match in _LINK_TAG.finditer(page):
        tag = match.group(0)
        rel = _attr(_REL_ATTR, tag)
        href = _attr(_HREF_ATTR, tag)
        if not rel or not href:
            continue
        if "icon" in rel.lower().split():
            return urljoin(base_url, html.unescape(href).strip())
    return None


async def _read_limited(response: httpx.Response, limit: int) -> bytes | None:
    """Body up to ``limit`` bytes; None when the body is larger."""
    length = response.headers.get("content-length")
    if length and length.isdigit() and int(length) > limit:
        return None
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _media_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


async def _fetch_image(client: httpx.AsyncClient, url: str) -> Icon | None:
    try:
        async with client.stream("GET", url, headers={"Accept": "image/*"}) as response:
            if response.status_code != 200:
                return None
            media_type = _media_type(response)
            if not media_type.startswith("image/"):
                return None
            body = await _read_limited(response, ICON_MAX_BYTES)
    except (httpx.HTTPError, UnsafeUrlError, TimeoutError) as exc:
        logger.info("Icon fetch failed for %s: %s", url, type(exc).__name__)
        return None
    if not body:
        return None
    return Icon(content=body, content_type=media_type)


async def _discover_link_icon(client: httpx.AsyncClient, origin: str) -> str | None:
    try:
        async with client.stream("GET", origin, headers={"Accept": "text/html"}) as response:
            if response.status_code != 200 or not _media_type(response).startswith("text/html"):
                return None
            body = await _read_limited(response, HTML_MAX_BYTES)
    except (httpx.HTTPError, UnsafeUrlError, TimeoutError) as exc:
        logger.info("Icon discovery failed for %s: %s", origin, type(exc).__name__)
        return None
    if body is None:
        return None
    return find_link_icon(body.decode("utf-8", "replace"), origin)


async def _fetch_uncached(origin: str) -> Icon | None:
    client = make_client()
    try:
        icon = await _fetch_image(client, urljoin(origin, "favicon.ico"))
        if icon is not None:
            return icon
        link = await _discover_link_icon(client, origin)
        if link is None:
            return None
        return await _fetch_image(client, link)
    finally:
        await client.aclose()


async def fetch_icon(origin: str) -> Icon | None:
    """Icon for ``origin`` (``https://host/``), served from the per-origin cache when fresh."""
    now = time.monotonic()
    cached = _cache.get(origin)
    if cached is not None and cached[0] > now:
        return cached[1]
    lock = _locks.setdefault(origin, asyncio.Lock())
    async with lock:
        cached = _cache.get(origin)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]
        icon = await _fetch_uncached(origin)
        ttl = ICON_TTL_SECONDS if icon is not None else MISS_TTL_SECONDS
        _cache[origin] = (time.monotonic() + ttl, icon)
        return icon
