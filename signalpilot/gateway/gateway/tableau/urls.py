"""Parse the one user-facing Tableau site URL into server + site content URL.

Accepted forms (any trailing path is ignored):

- ``https://10ay.online.tableau.com/#/site/<site>/...``  (Tableau Cloud browser URL)
- ``https://tableau.corp.com/t/<site>/...``              (embed / classic URL)
- ``https://tableau.corp.com``                            (Default site on Server)

Only https is accepted, except ``http://localhost*`` / ``http://127.0.0.1*``
for tests and local servers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

_SITE_RE = re.compile(r"(?:^|/)(?:site|t)/([^/?#]+)")


class TableauSiteUrlError(ValueError):
    """The site URL cannot be used."""


@dataclass(frozen=True)
class TableauSite:
    server_url: str
    site_content_url: str


def _is_local_http(host: str) -> bool:
    return host == "localhost" or host.startswith("localhost") or host == "127.0.0.1"


def parse_site_url(raw: str) -> TableauSite:
    """Return ``server_url`` (scheme + host, no trailing slash) and the site segment."""
    value = (raw or "").strip()
    if not value:
        raise TableauSiteUrlError("Site URL is required")
    parsed = urlparse(value)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if not host or scheme not in ("https", "http"):
        raise TableauSiteUrlError("Site URL must look like https://<host>/#/site/<site>")
    if scheme == "http" and not _is_local_http(host):
        raise TableauSiteUrlError("Site URL must use https")
    netloc = host if parsed.port is None else f"{host}:{parsed.port}"
    site = ""
    # Tableau Cloud puts the site in the fragment (#/site/x), classic URLs in the path (/t/x).
    for part in (parsed.fragment, parsed.path):
        match = _SITE_RE.search(part or "")
        if match:
            site = unquote(match.group(1))
            break
    return TableauSite(server_url=f"{scheme}://{netloc}", site_content_url=site)


def site_browser_url(server_url: str, site_content_url: str) -> str:
    """The browser URL of the site home (``#/site/x`` or ``#/`` for the Default site)."""
    base = server_url.rstrip("/")
    return f"{base}/#/site/{site_content_url}" if site_content_url else f"{base}/#/"


def content_browser_url(server_url: str, site_content_url: str, path: str) -> str:
    """Browser URL of a content page, e.g. ``views/Workbook/Sheet`` or ``workbooks/123``."""
    base = server_url.rstrip("/")
    prefix = f"{base}/#/site/{site_content_url}" if site_content_url else f"{base}/#"
    return f"{prefix}/{path.lstrip('/')}"
