"""Point a workbook's published-datasource references at the org's own site.

A workbook can only use published datasources on the site it is published
to. Workbooks downloaded from another site (or pod) still name that site in
their ``sqlproxy`` connections, ``repository-location`` tags, and
``derived-from`` URLs, so the gateway rewrites them before publishing.

Text edits only (regex on the raw XML): files reach 15 MB and an XML
round-trip would reformat them.
"""

from __future__ import annotations

import io
import re
import zipfile
from urllib.parse import urlparse
from xml.sax.saxutils import escape

_CONNECTION_TAG = re.compile(r"<connection\s[^>]*>")
_REPO_TAG = re.compile(r"<repository-location\s[^>]*?/>|<repository-location\s[^>]*>\s*</repository-location>")
_WORKBOOK_TAG = re.compile(r"<workbook\s[^>]*>")
# derived-from is absolute (https://pod/t/site/datasources/x?rev=) or relative (/t/site/datasources/x?rev=).
_DERIVED_FROM = re.compile(r"(\sderived-from=)(['\"])((?:https?://[^'\"/]+)?(?:/t/[^/'\"]+)?/datasources/[^'\"]*)\2")


def _attr(tag: str, name: str) -> str | None:
    match = re.search(rf"\s{re.escape(name)}=(?:'([^']*)'|\"([^\"]*)\")", tag)
    if not match:
        return None
    return match.group(1) if match.group(1) is not None else match.group(2)


def _quote(value: str) -> str:
    """Single-quoted attribute value, the way Tableau writes its XML."""
    return "'" + escape(value, {"'": "&apos;", '"': "&quot;"}) + "'"


def _set_attr(tag: str, name: str, value: str) -> str:
    """Set (or add) one attribute on a start tag, keeping everything else byte-identical."""
    pattern = re.compile(rf"(\s{re.escape(name)}=)('[^']*'|\"[^\"]*\")")
    if pattern.search(tag):
        return pattern.sub(lambda m: m.group(1) + _quote(value), tag, count=1)
    head = re.match(r"<[\w:-]+", tag)
    assert head is not None
    return f"{head.group(0)} {name}={_quote(value)}{tag[head.end() :]}"


def _drop_attr(tag: str, name: str) -> str:
    return re.sub(rf"\s{re.escape(name)}=(?:'[^']*'|\"[^\"]*\")", "", tag, count=1)


def normalize_site_references(xml: str, server_url: str, site_content_url: str) -> tuple[str, int]:
    """Rewrite published-datasource site references; return (xml, number of changed items)."""
    parsed = urlparse(server_url)
    scheme = parsed.scheme or "https"
    pod = parsed.netloc
    site = site_content_url or ""
    datasources_path = f"/t/{site}/datasources" if site else "/datasources"
    changes = 0

    def fix_connection(match: re.Match[str]) -> str:
        nonlocal changes
        tag = match.group(0)
        if _attr(tag, "class") != "sqlproxy" or _attr(tag, "server") in (None, pod):
            return tag
        changes += 1
        return _set_attr(tag, "server", pod)

    def fix_repository(match: re.Match[str]) -> str:
        nonlocal changes
        tag = match.group(0)
        path = (_attr(tag, "path") or "").rstrip("/")
        if path.endswith("/workbooks"):
            # The workbook-level location pins the old site's workbook path. Sheet and
            # dashboard locations (path ``.../workbooks/<Book>``) are left alone.
            changes += 1
            return ""
        if "/datasources" not in path:
            return tag
        new = _set_attr(tag, "path", datasources_path)
        new = _set_attr(new, "site", site) if site else _drop_attr(new, "site")
        if new != tag:
            changes += 1
        return new

    def fix_derived(match: re.Match[str]) -> str:
        nonlocal changes
        url = match.group(3)
        tail = url.split("/datasources/", 1)[1]
        origin = f"{scheme}://{pod}" if url.startswith(("http://", "https://")) else ""
        new_url = f"{origin}{datasources_path}/{tail}"
        if new_url == url:
            return match.group(0)
        changes += 1
        return f"{match.group(1)}{match.group(2)}{new_url}{match.group(2)}"

    def fix_workbook(match: re.Match[str]) -> str:
        nonlocal changes
        tag = match.group(0)
        base = _attr(tag, "xml:base")
        if base is None or base.rstrip("/") == server_url.rstrip("/"):
            return tag
        changes += 1
        return _set_attr(tag, "xml:base", server_url.rstrip("/"))

    xml = _CONNECTION_TAG.sub(fix_connection, xml)
    xml = _REPO_TAG.sub(fix_repository, xml)
    xml = _DERIVED_FROM.sub(fix_derived, xml)
    xml = _WORKBOOK_TAG.sub(fix_workbook, xml, count=1)
    return xml, changes


def normalize_workbook_bytes(data: bytes, server_url: str, site_content_url: str) -> tuple[bytes, int]:
    """Apply ``normalize_site_references`` to a .twb, or to the .twb inside a .twbx."""
    if not data.startswith(b"PK"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return data, 0
        new, count = normalize_site_references(text, server_url, site_content_url)
        return (new.encode("utf-8") if count else data), count
    try:
        source = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return data, 0
    total = 0
    out = io.BytesIO()
    with source, zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename.lower().endswith(".twb"):
                try:
                    text = content.decode("utf-8")
                except UnicodeDecodeError:
                    text = None
                if text is not None:
                    new, count = normalize_site_references(text, server_url, site_content_url)
                    if count:
                        content = new.encode("utf-8")
                        total += count
            target.writestr(info, content)
    return (out.getvalue() if total else data), total
