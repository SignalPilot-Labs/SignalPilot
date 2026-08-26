"""SignalPilot chart-theme adapter used by standalone-chat publication."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

SIGNALPILOT_CHART_THEME = "signalpilot-dark-v1"
CHART_BACKGROUND = "#141416"
CHART_TEXT = "#EDEDED"
CHART_MUTED_TEXT = "#B9B9B2"
CHART_GRID = "#333338"
CHART_BORDER = "#55555C"
CHART_COLORS = (
    "#56B4E9",
    "#E69F00",
    "#009E73",
    "#F0E442",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
    "#B3B3B3",
)
CHART_WIDTH = 640
CHART_HEIGHT = 400
MAX_CHART_CATEGORIES = 24
MAX_CHART_SERIES = len(CHART_COLORS)

_SEMANTIC_KEYS = {
    "aggregate",
    "bandPosition",
    "bin",
    "field",
    "sort",
    "stack",
    "timeUnit",
    "type",
}
_SUPPORTED_MARKS = {"bar", "line", "point"}


def chart_mark_type(spec: dict[str, Any]) -> str:
    mark = spec.get("mark", "bar")
    if isinstance(mark, dict):
        mark = mark.get("type", "bar")
    normalized = str(mark).lower()
    return normalized if normalized in _SUPPORTED_MARKS else "bar"


def chart_field(channel: Any) -> str | None:
    if not isinstance(channel, dict):
        return None
    field = channel.get("field")
    return str(field) if isinstance(field, str) and field else None


def _sanitize(value: Any) -> Any:
    if isinstance(value, list):
        return [
            cleaned
            for item in value
            if (cleaned := _sanitize(item)) not in ({}, None)
        ]
    if not isinstance(value, dict):
        return value
    if any(
        str(key).lower() in {"calculate", "expr", "signal"} for key in value
    ):
        return {}
    if isinstance(value.get("filter"), str):
        return {}
    safe: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).lower()
        if normalized in {
            "calculate",
            "data",
            "datasets",
            "url",
            "href",
            "expr",
            "signal",
        }:
            continue
        safe[str(key)] = _sanitize(item)
    return safe


def _stable_key(value: Any) -> tuple[str, str]:
    return type(value).__name__, repr(value)


def _unique(rows: list[dict[str, Any]], field: str | None) -> list[Any]:
    if not field:
        return []
    values: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        value = row.get(field)
        if value is None:
            continue
        key = _stable_key(value)
        if key not in seen:
            seen.add(key)
            values.append(value)
    return values


def _quantitative(channel: Any, rows: list[dict[str, Any]]) -> bool:
    if not isinstance(channel, dict):
        return False
    declared = str(channel.get("type") or "").lower()
    if declared:
        return declared == "quantitative"
    field = chart_field(channel)
    values = [
        row.get(field) for row in rows if field and row.get(field) is not None
    ]
    return bool(values) and all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        for value in values[:50]
    )


def _series_channel(encoding: dict[str, Any]) -> dict[str, Any] | None:
    for name in ("color", "fill", "stroke"):
        channel = encoding.get(name)
        if chart_field(channel):
            return channel
    return None


def _title(value: Any, fallback: str | None = None) -> str | None:
    if isinstance(value, str):
        return value[:200]
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        return value["text"][:200]
    return fallback


def _definition(channel: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in channel.items()
        if key in _SEMANTIC_KEYS
    }


def _limit_rows(
    spec: dict[str, Any],
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    encoding = spec.get("encoding")
    if not isinstance(encoding, dict):
        return rows, {
            "category_limit": MAX_CHART_CATEGORIES,
            "legend_limit": MAX_CHART_SERIES,
            "limited": False,
            "omitted_rows": 0,
        }
    x = encoding.get("x")
    y = encoding.get("y")
    category_field = None
    if chart_field(x) and not _quantitative(x, rows):
        category_field = chart_field(x)
    elif chart_field(y) and not _quantitative(y, rows):
        category_field = chart_field(y)
    series_field = chart_field(_series_channel(encoding))
    category_keys = {
        _stable_key(value)
        for value in _unique(rows, category_field)[:MAX_CHART_CATEGORIES]
    }
    series_keys = {
        _stable_key(value)
        for value in _unique(rows, series_field)[:MAX_CHART_SERIES]
    }
    limited = [
        row
        for row in rows
        if (
            not category_field
            or row.get(category_field) is None
            or _stable_key(row.get(category_field)) in category_keys
        )
        and (
            not series_field
            or row.get(series_field) is None
            or _stable_key(row.get(series_field)) in series_keys
        )
    ]
    return limited, {
        "category_limit": MAX_CHART_CATEGORIES,
        "legend_limit": MAX_CHART_SERIES,
        "limited": len(limited) < len(rows),
        "omitted_rows": len(rows) - len(limited),
    }


def _mark(mark: str) -> dict[str, Any]:
    if mark == "line":
        return {
            "type": "line",
            "strokeWidth": 2.5,
            "point": {"filled": True, "size": 58, "stroke": CHART_BACKGROUND},
            "invalid": "break-paths-filter-domains",
        }
    if mark == "point":
        return {
            "type": "point",
            "filled": True,
            "size": 78,
            "stroke": CHART_BACKGROUND,
            "strokeWidth": 1,
            "invalid": "filter",
        }
    return {"type": "bar", "cornerRadiusEnd": 3, "invalid": "filter"}


def _theme_spec(
    spec: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    mark = chart_mark_type(spec)
    encoding = (
        spec.get("encoding") if isinstance(spec.get("encoding"), dict) else {}
    )
    themed_encoding: dict[str, Any] = {}
    for name in ("x", "y"):
        channel = encoding.get(name)
        if not isinstance(channel, dict) or not chart_field(channel):
            continue
        definition = _definition(channel)
        quantitative = _quantitative(channel, rows)
        values = _unique(rows, chart_field(channel))
        supplied_axis = channel.get("axis")
        supplied_title = (
            supplied_axis.get("title")
            if isinstance(supplied_axis, dict)
            else channel.get("title")
        )
        definition["axis"] = {
            "title": _title(supplied_title, chart_field(channel)),
            "format": ".3~s" if quantitative else None,
            "labelAngle": (
                -45
                if name == "x"
                and not quantitative
                and (
                    len(values) > 8
                    or max((len(str(value)) for value in values), default=0)
                    > 12
                )
                else 0
            ),
            "labelLimit": (
                140
                if name == "x"
                and not quantitative
                and (
                    len(values) > 8
                    or max((len(str(value)) for value in values), default=0)
                    > 12
                )
                else 180
            ),
            "labelOverlap": (
                False
                if name == "x"
                and not quantitative
                and len(values) <= 8
                and max((len(str(value)) for value in values), default=0) > 12
                else "greedy"
            ),
            "labelFlush": False,
        }
        definition["axis"] = {
            key: value
            for key, value in definition["axis"].items()
            if value is not None
        }
        definition["scale"] = (
            {"type": "linear", "nice": True, "zero": True}
            if quantitative
            else (
                {
                    "type": "band",
                    "domain": values[:MAX_CHART_CATEGORIES],
                    "paddingInner": 0.2,
                    "paddingOuter": 0.12,
                }
                if mark == "bar"
                else {
                    "type": "point",
                    "domain": values[:MAX_CHART_CATEGORIES],
                    "padding": 0.5,
                }
            )
        )
        themed_encoding[name] = definition

    series = _series_channel(encoding)
    series_field = chart_field(series)
    if series_field and isinstance(series, dict):
        values = _unique(rows, series_field)[:MAX_CHART_SERIES]
        color = _definition(series)
        color["scale"] = {
            "domain": values,
            "range": list(CHART_COLORS[: len(values)]),
        }
        supplied_legend = series.get("legend")
        color["legend"] = {
            "title": _title(
                supplied_legend.get("title")
                if isinstance(supplied_legend, dict)
                else series.get("title"),
                series_field,
            ),
            "symbolLimit": MAX_CHART_SERIES,
        }
        themed_encoding["color"] = color
        if mark == "bar":
            category_channel = (
                "x"
                if "x" in themed_encoding
                and not _quantitative(encoding.get("x"), rows)
                else "y"
            )
            themed_encoding[
                "xOffset" if category_channel == "x" else "yOffset"
            ] = {
                "field": series_field,
                "type": color.get("type", "nominal"),
                "scale": {"domain": values},
            }

    tooltip = encoding.get("tooltip")
    if isinstance(tooltip, list):
        themed_encoding["tooltip"] = [
            _definition(item)
            for item in tooltip
            if isinstance(item, dict) and chart_field(item)
        ][:12]
    elif isinstance(tooltip, dict) and chart_field(tooltip):
        themed_encoding["tooltip"] = _definition(tooltip)

    themed = {
        key: deepcopy(value)
        for key, value in spec.items()
        if key
        not in {
            "autosize",
            "background",
            "config",
            "data",
            "datasets",
            "encoding",
            "height",
            "mark",
            "padding",
            "usermeta",
            "width",
        }
    }
    themed.update(
        {
            "mark": _mark(mark),
            "encoding": themed_encoding,
            "background": CHART_BACKGROUND,
            "width": CHART_WIDTH,
            "height": CHART_HEIGHT,
            "autosize": {"type": "fit", "contains": "padding", "resize": True},
            "padding": {"left": 8, "right": 16, "top": 8, "bottom": 8},
            "config": {
                "font": "DM Sans, Segoe UI, sans-serif",
                "numberFormat": ".3~s",
                "view": {"fill": CHART_BACKGROUND, "stroke": CHART_BORDER},
                "axis": {
                    "domainColor": CHART_BORDER,
                    "domainWidth": 1,
                    "grid": True,
                    "gridColor": CHART_GRID,
                    "gridOpacity": 1,
                    "labelColor": CHART_TEXT,
                    "labelFont": "DM Sans, Segoe UI, sans-serif",
                    "labelFontSize": 12,
                    "labelLimit": 180,
                    "labelPadding": 8,
                    "tickColor": CHART_BORDER,
                    "tickSize": 4,
                    "titleColor": CHART_TEXT,
                    "titleFont": "DM Sans, Segoe UI, sans-serif",
                    "titleFontSize": 13,
                    "titleFontWeight": 500,
                    "titleLimit": 240,
                    "titlePadding": 12,
                },
                "legend": {
                    "columns": 4,
                    "columnPadding": 14,
                    "direction": "horizontal",
                    "labelColor": CHART_TEXT,
                    "labelFont": "DM Sans, Segoe UI, sans-serif",
                    "labelFontSize": 12,
                    "labelLimit": 160,
                    "orient": "bottom",
                    "rowPadding": 5,
                    "symbolLimit": MAX_CHART_SERIES,
                    "titleColor": CHART_TEXT,
                    "titleFont": "DM Sans, Segoe UI, sans-serif",
                    "titleFontSize": 13,
                    "titleFontWeight": 500,
                },
                "title": {
                    "anchor": "start",
                    "color": CHART_TEXT,
                    "font": "DM Sans, Segoe UI, sans-serif",
                    "fontSize": 16,
                    "fontWeight": 600,
                    "offset": 18,
                },
                "range": {"category": list(CHART_COLORS)},
                "bar": {"color": CHART_COLORS[0]},
                "line": {"color": CHART_COLORS[0]},
                "point": {"color": CHART_COLORS[0]},
            },
            "usermeta": {
                "signalpilotChartTheme": SIGNALPILOT_CHART_THEME,
                "categoryLimit": MAX_CHART_CATEGORIES,
                "legendLimit": MAX_CHART_SERIES,
            },
        }
    )
    if "title" in themed:
        themed["title"] = _title(themed["title"])
    return themed


def prepare_signalpilot_chart(
    spec: dict[str, Any],
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Sanitize, density-limit, and theme an agent-produced chart."""
    safe = _sanitize(spec)
    if not isinstance(safe, dict):
        safe = {}
    clean_rows = [row for row in rows if isinstance(row, dict)]
    display_rows, display = _limit_rows(safe, clean_rows)
    return _theme_spec(safe, display_rows), display_rows, display
