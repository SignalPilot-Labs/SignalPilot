"""Theme tokens for generated SignalPilot HTML deliverables."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
DEFAULT_CHART_SERIES = ["#087a3d", "#0fa45a", "#35c978", "#8eeaa8", "#c8f8d4", "#e7fcec"]
DEFAULT_FONT_FAMILY = '"SF Mono", "Fira Code", "Cascadia Code", ui-monospace, monospace'


def _validate_hex_color(value: str, field_name: str) -> str:
    if not HEX_COLOR_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a #rgb or #rrggbb hex color")
    return value.lower()


class ThemeColors(BaseModel):
    bg: str = "#050505"
    surface: str = "#0a0a0a"
    surface_alt: str = "#0d0d0d"
    border: str = "#222222"
    text: str = "#eeeeee"
    muted: str = "#999999"
    accent: str = "#ffffff"
    positive: str = "#00ff88"
    warning: str = "#ffaa00"
    negative: str = "#ff4444"
    chart_grid: str = "#1f1f1f"
    chart_axis: str = "#999999"

    @field_validator("*")
    @classmethod
    def validate_hex_colors(cls, value: str, info) -> str:
        return _validate_hex_color(value, info.field_name)


class DeliverableTheme(BaseModel):
    version: int = 1
    colors: ThemeColors = Field(default_factory=ThemeColors)
    chart_series: list[str] = Field(default_factory=lambda: DEFAULT_CHART_SERIES.copy(), min_length=3, max_length=8)
    font_family: str = Field(default=DEFAULT_FONT_FAMILY, min_length=1, max_length=240)
    font_size_base_px: int = Field(default=14, ge=10, le=24)
    spacing_unit_px: int = Field(default=8, ge=4, le=24)
    radius_px: int = Field(default=6, ge=0, le=24)

    @field_validator("chart_series")
    @classmethod
    def validate_chart_series(cls, value: list[str]) -> list[str]:
        return [_validate_hex_color(color, "chart_series") for color in value]

    @field_validator("font_family")
    @classmethod
    def validate_font_family(cls, value: str) -> str:
        cleaned = value.strip()
        if any(char in cleaned for char in "{};<>"):
            raise ValueError("font_family contains unsupported CSS control characters")
        return cleaned
