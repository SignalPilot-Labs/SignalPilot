"""Compact structural summary of a Tableau ``.twb`` workbook file.

Workbooks are 3 to 14 MB of XML, so the tools never return the XML itself.
``summarize_twb`` streams the file once with ``iterparse`` and keeps only the
top-level structure the agent needs to plan an edit: dashboards, worksheets,
data sources (caption, connection class, and the published content URL for
``sqlproxy`` sources), and parameters. The JSON form stays under
``SUMMARY_MAX_CHARS`` by trimming the name lists, never the counts.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

SUMMARY_MAX_CHARS = 4_000
_NAME_CHARS = 60
# List caps tried in order until the JSON form fits SUMMARY_MAX_CHARS.
_LIST_CAPS = (25, 10, 3, 0)

_DATASOURCE_PATH = ("workbook", "datasources", "datasource")
_WORKSHEET_PATH = ("workbook", "worksheets", "worksheet")
_DASHBOARD_PATH = ("workbook", "dashboards", "dashboard")


def _local(tag: str) -> str:
    """Tag name without an XML namespace."""
    return tag.rsplit("}", 1)[-1]


def _short(value: Any) -> str:
    text = str(value or "")
    return (
        text if len(text) <= _NAME_CHARS else text[: _NAME_CHARS - 3] + "..."
    )


def _scan(path: Path) -> dict[str, Any]:
    dashboards: list[str] = []
    worksheets: list[str] = []
    datasources: list[dict[str, Any]] = []
    parameters: list[str] = []
    stack: list[str] = []
    current: dict[str, Any] | None = None
    in_parameters = False

    for event, element in ET.iterparse(str(path), events=("start", "end")):
        tag = _local(element.tag)
        if event == "end":
            stack.pop()
            if tuple(stack) == _DATASOURCE_PATH[:2] and tag == "datasource":
                current = None
                in_parameters = False
            element.clear()
            continue
        stack.append(tag)
        position = tuple(stack)
        attrs = element.attrib
        if position == _WORKSHEET_PATH:
            worksheets.append(str(attrs.get("name") or ""))
        elif position == _DASHBOARD_PATH:
            dashboards.append(str(attrs.get("name") or ""))
        elif position == _DATASOURCE_PATH:
            name = str(attrs.get("name") or "")
            if name == "Parameters":
                in_parameters = True
                current = None
                continue
            current = {
                "name": name,
                "caption": str(attrs.get("caption") or name),
                "connection_class": "",
                "content_url": None,
                "inner_classes": [],
            }
            datasources.append(current)
        elif in_parameters and tag == "column":
            if attrs.get("param-domain-type") is not None:
                parameters.append(
                    str(attrs.get("caption") or attrs.get("name") or "")
                )
        elif current is not None and len(stack) > len(_DATASOURCE_PATH):
            _read_datasource_child(current, stack, tag, attrs)
    return {
        "dashboards": dashboards,
        "worksheets": worksheets,
        "datasources": datasources,
        "parameters": parameters,
    }


def _read_datasource_child(
    current: dict[str, Any], stack: list[str], tag: str, attrs: Any
) -> None:
    depth = len(stack) - len(_DATASOURCE_PATH)
    if tag == "connection":
        klass = str(attrs.get("class") or "")
        if depth == 1:
            current["connection_class"] = klass
            if klass == "sqlproxy" and attrs.get("dbname"):
                current["content_url"] = str(attrs.get("dbname"))
        elif klass and klass not in current["inner_classes"]:
            current["inner_classes"].append(klass)
    elif tag == "repository-location" and depth == 1 and attrs.get("id"):
        current["content_url"] = current["content_url"] or str(attrs["id"])


def _render(scan: dict[str, Any], cap: int) -> dict[str, Any]:
    sources = []
    for source in scan["datasources"][:cap]:
        entry: dict[str, Any] = {
            "caption": _short(source["caption"]),
            "class": source["connection_class"],
        }
        if source["inner_classes"]:
            entry["inner_classes"] = source["inner_classes"][:5]
        if source["content_url"]:
            entry["content_url"] = _short(source["content_url"])
        sources.append(entry)
    rendered: dict[str, Any] = {
        "dashboard_count": len(scan["dashboards"]),
        "worksheet_count": len(scan["worksheets"]),
        "datasource_count": len(scan["datasources"]),
        "parameter_count": len(scan["parameters"]),
        "dashboards": [_short(name) for name in scan["dashboards"][:cap]],
        "worksheets": [_short(name) for name in scan["worksheets"][:cap]],
        "datasources": sources,
        "parameters": [_short(name) for name in scan["parameters"][:cap]],
    }
    total = sum(
        len(scan[key])
        for key in ("dashboards", "worksheets", "datasources", "parameters")
    )
    shown = sum(
        len(rendered[key])
        for key in ("dashboards", "worksheets", "datasources", "parameters")
    )
    if shown < total:
        rendered["lists_truncated"] = True
    return rendered


def summarize_twb(path: Path) -> dict[str, Any]:
    """Structural summary of one ``.twb`` file, at most 4 KB as JSON.

    A file that is not well-formed XML returns ``{"parse_error": ...}`` so
    the download still succeeds and the agent can inspect the file itself.
    """
    try:
        scan = _scan(path)
    except (ET.ParseError, OSError) as exc:
        return {"parse_error": str(exc)[:300]}
    for cap in _LIST_CAPS:
        rendered = _render(scan, cap)
        if len(json.dumps(rendered)) <= SUMMARY_MAX_CHARS:
            return rendered
    return _render(scan, 0)
