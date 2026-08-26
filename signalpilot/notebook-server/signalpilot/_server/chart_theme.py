"""Theme adapter for server-rendered analysis chart images."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
DEFAULT_SERIES = ("#087a3d", "#0fa45a", "#35c978", "#8eeaa8", "#c8f8d4", "#e7fcec")
DEFAULT_FONT_FAMILY = '"SF Mono", "Fira Code", "Cascadia Code", ui-monospace, monospace'


def _hex(value: Any, fallback: str) -> str:
    if isinstance(value, str) and HEX_COLOR_RE.fullmatch(value.strip()):
        return value.strip().lower()
    return fallback


def _text(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip() and not any(char in value for char in "{};<>"):
        return value.strip()
    return fallback


@dataclass(frozen=True)
class ChartTheme:
    bg: str = "#050505"
    surface: str = "#0a0a0a"
    text: str = "#eeeeee"
    muted: str = "#999999"
    axis: str = "#999999"
    grid: str = "#1f1f1f"
    positive: str = "#00ff88"
    warning: str = "#ffaa00"
    negative: str = "#ff4444"
    series: tuple[str, ...] = DEFAULT_SERIES
    font_family: str = DEFAULT_FONT_FAMILY

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> ChartTheme:
        if not isinstance(payload, dict):
            return DEFAULT_CHART_THEME
        colors = payload.get("colors") if isinstance(payload.get("colors"), dict) else {}
        series_raw = payload.get("chartSeries", payload.get("chart_series"))
        series = tuple(
            _hex(item, DEFAULT_SERIES[index % len(DEFAULT_SERIES)])
            for index, item in enumerate(series_raw if isinstance(series_raw, list) else [])
        )
        if len(series) < 3:
            series = DEFAULT_SERIES
        return cls(
            bg=_hex(payload.get("bg", colors.get("bg")), DEFAULT_CHART_THEME.bg),
            surface=_hex(payload.get("surface", colors.get("surface")), DEFAULT_CHART_THEME.surface),
            text=_hex(payload.get("text", colors.get("text")), DEFAULT_CHART_THEME.text),
            muted=_hex(payload.get("muted", colors.get("muted")), DEFAULT_CHART_THEME.muted),
            axis=_hex(payload.get("chartAxis", payload.get("chart_axis", colors.get("chart_axis"))), DEFAULT_CHART_THEME.axis),
            grid=_hex(payload.get("chartGrid", payload.get("chart_grid", colors.get("chart_grid"))), DEFAULT_CHART_THEME.grid),
            positive=_hex(payload.get("positive", colors.get("positive")), DEFAULT_CHART_THEME.positive),
            warning=_hex(payload.get("warning", colors.get("warning")), DEFAULT_CHART_THEME.warning),
            negative=_hex(payload.get("negative", colors.get("negative")), DEFAULT_CHART_THEME.negative),
            series=series[:8],
            font_family=_text(payload.get("fontFamily", payload.get("font_family")), DEFAULT_CHART_THEME.font_family),
        )


DEFAULT_CHART_THEME = ChartTheme()


def ranked_series_colors(values: list[float], series: tuple[str, ...]) -> list[str]:
    if not values:
        return []
    palette = series or DEFAULT_SERIES
    ranked_indexes = sorted(range(len(values)), key=lambda index: values[index], reverse=True)
    colors = [palette[-1]] * len(values)
    for rank, index in enumerate(ranked_indexes):
        colors[index] = palette[min(rank, len(palette) - 1)]
    return colors


def contrast_text(hex_color: str) -> str:
    color = hex_color.lstrip("#")
    if len(color) == 3:
        color = "".join(char * 2 for char in color)
    try:
        red = int(color[0:2], 16)
        green = int(color[2:4], 16)
        blue = int(color[4:6], 16)
    except ValueError:
        return "#ffffff"
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    return "#050505" if luminance > 0.62 else "#ffffff"
