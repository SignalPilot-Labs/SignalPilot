"""Canonical, enforced chart presentation for standalone data chat."""

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
CHART_FONT = "DM Sans, Segoe UI, sans-serif"
CHART_WIDTH = 640
CHART_HEIGHT = 400
MAX_CHART_CATEGORIES = 24
MAX_CHART_SERIES = len(CHART_COLORS)

_SUPPORTED_MARKS = {"bar", "line", "point"}
_FIELD_DEFINITION_KEYS = {
    "aggregate",
    "bandPosition",
    "bin",
    "field",
    "sort",
    "stack",
    "timeUnit",
    "type",
}


def _clean_title(value: Any, fallback: str | None = None) -> str | None:
    if isinstance(value, str):
        return value[:200]
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        return value["text"][:200]
    return fallback


def _mark_type(spec: dict[str, Any]) -> str:
    mark = spec.get("mark", "bar")
    if isinstance(mark, dict):
        mark = mark.get("type", "bar")
    normalized = str(mark).lower()
    return normalized if normalized in _SUPPORTED_MARKS else "bar"


def _field(channel: Any) -> str | None:
    if not isinstance(channel, dict):
        return None
    field = channel.get("field")
    return str(field) if isinstance(field, str) and field else None


def _stable_key(value: Any) -> tuple[str, str]:
    return type(value).__name__, repr(value)


def _unique_values(rows: list[dict[str, Any]], field: str | None) -> list[Any]:
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


def _is_quantitative(channel: Any, rows: list[dict[str, Any]]) -> bool:
    if not isinstance(channel, dict):
        return False
    declared = str(channel.get("type") or "").lower()
    if declared:
        return declared == "quantitative"
    field = _field(channel)
    values = [row.get(field) for row in rows if field and row.get(field) is not None]
    return bool(values) and all(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
        for value in values[:50]
    )


def _series_channel(encoding: dict[str, Any]) -> dict[str, Any] | None:
    for name in ("color", "fill", "stroke"):
        channel = encoding.get(name)
        if _field(channel):
            return channel
    return None


def limit_chart_rows(
    spec: dict[str, Any],
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Bound visual density while preserving the full source snapshot separately."""
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
    if _field(x) and not _is_quantitative(x, rows):
        category_field = _field(x)
    elif _field(y) and not _is_quantitative(y, rows):
        category_field = _field(y)
    series_field = _field(_series_channel(encoding))
    categories = _unique_values(rows, category_field)[:MAX_CHART_CATEGORIES]
    series = _unique_values(rows, series_field)[:MAX_CHART_SERIES]
    category_keys = {_stable_key(value) for value in categories}
    series_keys = {_stable_key(value) for value in series}
    limited_rows = [
        row
        for row in rows
        if (
            not category_field
            or row.get(category_field) is None
            or _stable_key(row.get(category_field)) in category_keys
        )
        and (not series_field or row.get(series_field) is None or _stable_key(row.get(series_field)) in series_keys)
    ]
    return limited_rows, {
        "category_limit": MAX_CHART_CATEGORIES,
        "legend_limit": MAX_CHART_SERIES,
        "limited": len(limited_rows) < len(rows),
        "omitted_rows": len(rows) - len(limited_rows),
    }


def _axis(
    channel: dict[str, Any],
    *,
    quantitative: bool,
    rotate_labels: bool,
    category_count: int,
) -> dict[str, Any]:
    supplied_axis = channel.get("axis")
    supplied_title = supplied_axis.get("title") if isinstance(supplied_axis, dict) else channel.get("title")
    axis: dict[str, Any] = {
        "title": _clean_title(supplied_title, _field(channel)),
        "labelAngle": -45 if rotate_labels else 0,
        "labelLimit": 140 if rotate_labels else 180,
        "labelOverlap": (False if rotate_labels and category_count <= 8 else "greedy"),
        "labelFlush": False,
    }
    if quantitative:
        axis["format"] = ".3~s"
        axis["labelAngle"] = 0
    return axis


def _field_definition(channel: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in channel.items() if key in _FIELD_DEFINITION_KEYS}


def _theme_encoding(
    encoding: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    mark: str,
) -> dict[str, Any]:
    themed: dict[str, Any] = {}
    series = _series_channel(encoding)
    series_field = _field(series)
    for name in ("x", "y"):
        channel = encoding.get(name)
        if not isinstance(channel, dict) or not _field(channel):
            continue
        definition = _field_definition(channel)
        quantitative = _is_quantitative(channel, rows)
        values = _unique_values(rows, _field(channel))
        category_count = len(values)
        max_label_length = max(
            (len(str(value)) for value in values),
            default=0,
        )
        definition["axis"] = _axis(
            channel,
            quantitative=quantitative,
            rotate_labels=name == "x" and not quantitative and (category_count > 8 or max_label_length > 12),
            category_count=category_count,
        )
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
        themed[name] = definition

    if series_field and isinstance(series, dict):
        series_values = _unique_values(rows, series_field)[:MAX_CHART_SERIES]
        color = _field_definition(series)
        color["scale"] = {
            "domain": series_values,
            "range": list(CHART_COLORS[: len(series_values)]),
        }
        color["legend"] = {
            "title": _clean_title(
                series.get("legend", {}).get("title")
                if isinstance(series.get("legend"), dict)
                else series.get("title"),
                series_field,
            ),
            "symbolLimit": MAX_CHART_SERIES,
        }
        themed["color"] = color
        if mark == "bar":
            category_channel = "x" if "x" in themed and not _is_quantitative(encoding.get("x"), rows) else "y"
            offset_channel = "xOffset" if category_channel == "x" else "yOffset"
            themed[offset_channel] = {
                "field": series_field,
                "type": color.get("type", "nominal"),
                "scale": {"domain": series_values},
            }

    tooltip = encoding.get("tooltip")
    if isinstance(tooltip, list):
        themed["tooltip"] = [_field_definition(item) for item in tooltip if isinstance(item, dict) and _field(item)][
            :12
        ]
    elif isinstance(tooltip, dict) and _field(tooltip):
        themed["tooltip"] = _field_definition(tooltip)

    size = encoding.get("size")
    if mark == "point" and isinstance(size, dict) and _field(size):
        themed["size"] = {
            **_field_definition(size),
            "scale": {"range": [48, 180]},
            "legend": None,
        }
    return themed


def _canonical_mark(mark: str) -> dict[str, Any]:
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
    return {
        "type": "bar",
        "cornerRadiusEnd": 3,
        "invalid": "filter",
    }


def _theme_compositions(value: Any, rows: list[dict[str, Any]]) -> Any:
    if isinstance(value, list):
        return [_theme_unit(item, rows) if isinstance(item, dict) else item for item in value]
    if isinstance(value, dict):
        return _theme_unit(value, rows)
    return value


def _theme_unit(spec: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    themed = deepcopy(spec)
    for key in ("background", "config", "width", "height", "autosize", "padding"):
        themed.pop(key, None)
    for key in ("layer", "hconcat", "vconcat", "concat"):
        if key in themed:
            themed[key] = _theme_compositions(themed[key], rows)
    if isinstance(themed.get("spec"), dict):
        themed["spec"] = _theme_unit(themed["spec"], rows)
    if isinstance(themed.get("encoding"), dict) or "mark" in themed:
        mark = _mark_type(themed)
        themed["mark"] = _canonical_mark(mark)
        themed["encoding"] = _theme_encoding(
            themed.get("encoding") if isinstance(themed.get("encoding"), dict) else {},
            rows,
            mark=mark,
        )
    if "title" in themed:
        themed["title"] = _clean_title(themed["title"])
    return themed


def apply_signalpilot_chart_theme(
    spec: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply the non-overridable SignalPilot theme to a sanitized Vega-Lite spec."""
    themed = _theme_unit(spec, rows)
    themed.update(
        {
            "background": CHART_BACKGROUND,
            "width": CHART_WIDTH,
            "height": CHART_HEIGHT,
            "autosize": {"type": "fit", "contains": "padding", "resize": True},
            "padding": {"left": 8, "right": 16, "top": 8, "bottom": 8},
            "config": {
                "font": CHART_FONT,
                "numberFormat": ".3~s",
                "view": {"fill": CHART_BACKGROUND, "stroke": CHART_BORDER},
                "axis": {
                    "domainColor": CHART_BORDER,
                    "domainWidth": 1,
                    "grid": True,
                    "gridColor": CHART_GRID,
                    "gridOpacity": 1,
                    "labelColor": CHART_TEXT,
                    "labelFont": CHART_FONT,
                    "labelFontSize": 12,
                    "labelLimit": 180,
                    "labelPadding": 8,
                    "tickColor": CHART_BORDER,
                    "tickSize": 4,
                    "titleColor": CHART_TEXT,
                    "titleFont": CHART_FONT,
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
                    "labelFont": CHART_FONT,
                    "labelFontSize": 12,
                    "labelLimit": 160,
                    "orient": "bottom",
                    "rowPadding": 5,
                    "symbolLimit": MAX_CHART_SERIES,
                    "titleColor": CHART_TEXT,
                    "titleFont": CHART_FONT,
                    "titleFontSize": 13,
                    "titleFontWeight": 500,
                },
                "title": {
                    "anchor": "start",
                    "color": CHART_TEXT,
                    "font": CHART_FONT,
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
    return themed
