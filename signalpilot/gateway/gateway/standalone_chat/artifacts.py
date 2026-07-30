"""Immutable artifact validation and safe download helpers."""

from __future__ import annotations

import csv
import io
import re
from html import escape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from gateway.standalone_chat.chart_theme import (
    apply_signalpilot_chart_theme,
    limit_chart_rows,
)

MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")
_FORMULA_PREFIXES = ("=", "+", "-", "@")
_DROP_CONTENT_TAGS = {"script", "form", "iframe", "object", "embed", "link", "meta"}
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}
_SAFE_TAGS = {
    "a",
    "article",
    "aside",
    "b",
    "blockquote",
    "br",
    "caption",
    "code",
    "col",
    "colgroup",
    "dd",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "i",
    "img",
    "li",
    "main",
    "ol",
    "p",
    "pre",
    "section",
    "small",
    "span",
    "strong",
    "style",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
_GLOBAL_ATTRS = {"class", "id", "role", "title", "aria-label", "aria-hidden"}
_TAG_ATTRS = {
    "a": {"href"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "col": {"span", "width"},
}
MAX_TABLE_ROWS = 1_000


def safe_filename(filename: str, *, fallback: str) -> str:
    normalized = _SAFE_FILENAME_RE.sub("_", filename).strip(" .")
    return (normalized or fallback)[:255]


def protect_csv_cell(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def normalize_table_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Apply the governed row ceiling even when a publisher is adversarial."""
    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        rows = []
    truncated = bool(snapshot.get("truncated")) or len(rows) > MAX_TABLE_ROWS
    return {
        **snapshot,
        "rows": rows[:MAX_TABLE_ROWS],
        "truncated": truncated,
    }


def _sanitize_chart_value(value: Any) -> Any:
    if isinstance(value, list):
        return [cleaned for item in value if (cleaned := _sanitize_chart_value(item)) not in ({}, None)]
    if not isinstance(value, dict):
        return value
    if any(str(key).lower() in {"calculate", "expr", "signal"} for key in value):
        return {}
    if isinstance(value.get("filter"), str):
        return {}
    safe: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).lower()
        if normalized in {"calculate", "data", "datasets", "url", "href", "expr", "signal"}:
            continue
        safe[str(key)] = _sanitize_chart_value(item)
    return safe


def sanitize_chart_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Strip remote-data and executable expression surfaces from chart specs."""
    spec = snapshot.get("spec")
    if not isinstance(spec, dict):
        raise ValueError("Chart artifact requires a Vega-Lite specification")
    supplied_source = snapshot.get("source")
    source_rows = (
        supplied_source.get("rows")
        if isinstance(supplied_source, dict) and isinstance(supplied_source.get("rows"), list)
        else snapshot.get("rows")
    )
    normalized_rows = source_rows if isinstance(source_rows, list) else []
    truncated = bool(snapshot.get("truncated")) or len(normalized_rows) > MAX_TABLE_ROWS
    clean_rows = [row for row in normalized_rows[:MAX_TABLE_ROWS] if isinstance(row, dict)]
    clean_spec = _sanitize_chart_value(spec)
    if not isinstance(clean_spec, dict):
        clean_spec = {}
    display_rows, display = limit_chart_rows(clean_spec, clean_rows)
    themed_spec = apply_signalpilot_chart_theme(clean_spec, display_rows)
    columns = [
        {"name": str(name), "type": "unknown"}
        for name in (clean_rows[0].keys() if clean_rows and isinstance(clean_rows[0], dict) else [])
    ]
    return {
        **snapshot,
        "spec": themed_spec,
        "rows": display_rows,
        "source": {
            "columns": columns,
            "rows": clean_rows,
            "truncated": truncated,
        },
        "display": display,
        "truncated": truncated,
    }


def table_to_csv(snapshot: dict[str, Any]) -> bytes:
    columns = snapshot.get("columns") or []
    names = [str(column.get("name") if isinstance(column, dict) else column) for column in columns]
    rows = snapshot.get("rows") or []
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(names)
    for row in rows:
        if isinstance(row, dict):
            writer.writerow([protect_csv_cell(row.get(name, "")) for name in names])
        elif isinstance(row, list):
            writer.writerow([protect_csv_cell(value) for value in row[: len(names)]])
    if snapshot.get("truncated"):
        writer.writerow([])
        writer.writerow(["Data truncated by the governed query row limit."])
    return output.getvalue().encode("utf-8-sig")


def _safe_url(value: str, *, image: bool = False) -> bool:
    parsed = urlparse(value.strip())
    if image:
        return parsed.scheme == "data" and value.lower().startswith(
            ("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/gif;base64,", "data:image/webp;base64,")
        )
    return not parsed.scheme and value.startswith("#")


def _safe_inline_style(value: str) -> bool:
    normalized = value.lower().replace("\\", "")
    return not any(
        marker in normalized
        for marker in ("url(", "@import", "expression(", "javascript:", "behavior:", "-moz-binding")
    )


class _ReportSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.drop_depth = 0
        self.style_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _DROP_CONTENT_TAGS:
            if tag not in _VOID_TAGS:
                self.drop_depth += 1
            return
        if self.drop_depth or tag not in _SAFE_TAGS:
            return
        if tag == "style":
            self.style_depth += 1
            self.output.append("<style>")
            return
        safe_attrs: list[str] = []
        allowed = _GLOBAL_ATTRS | _TAG_ATTRS.get(tag, set())
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            value = raw_value or ""
            if name.startswith("on") or (name != "style" and name not in allowed):
                continue
            if name == "style" and not _safe_inline_style(value):
                continue
            if name == "href" and not _safe_url(value):
                continue
            if name == "src" and not _safe_url(value, image=True):
                continue
            safe_attrs.append(f' {name}="{escape(value, quote=True)}"')
        self.output.append(f"<{tag}{''.join(safe_attrs)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS and not self.drop_depth:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _DROP_CONTENT_TAGS:
            if tag not in _VOID_TAGS and self.drop_depth:
                self.drop_depth -= 1
            return
        if tag == "style":
            if not self.drop_depth and self.style_depth:
                self.style_depth -= 1
                self.output.append("</style>")
            return
        if not self.drop_depth and tag in _SAFE_TAGS and tag not in _VOID_TAGS:
            self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self.drop_depth:
            return
        if self.style_depth:
            if _safe_inline_style(data):
                self.output.append(data)
            return
        self.output.append(escape(data))

    def handle_entityref(self, name: str) -> None:
        if not self.drop_depth:
            self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.drop_depth:
            self.output.append(f"&#{name};")


def sanitize_report_html(value: str) -> str:
    """Return a self-contained static report with an iframe-oriented CSP."""
    parser = _ReportSanitizer()
    parser.feed(value)
    parser.close()
    body = "".join(parser.output)
    visible_body = re.sub(
        r"<style(?:\s[^>]*)?>.*?</style>",
        "",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()
    if not visible_body:
        raise ValueError("Report contains no renderable static content after sanitization")
    csp = (
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
        "font-src 'none'; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"
    )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">'
        '<meta name="referrer" content="no-referrer">'
        "<style>body{font-family:system-ui,sans-serif;margin:24px;color:#171717}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;text-align:left}"
        "img{max-width:100%;height:auto}pre{white-space:pre-wrap}</style>"
        f"</head><body>{body}</body></html>"
    )


def validate_artifact_size(snapshot: dict[str, Any], binary_data: bytes | None = None) -> None:
    import json

    size = len(json.dumps(snapshot, ensure_ascii=False, default=str).encode("utf-8"))
    size += len(binary_data or b"")
    if size > MAX_ARTIFACT_BYTES:
        raise ValueError("Artifact exceeds the 10 MiB limit")
