"""Server-owned visual tokens and component styles for HTML deliverables."""

from __future__ import annotations

from gateway.models.deliverable_theme import DeliverableTheme, chart_series_from_positive

DESIGN_SYSTEM_STYLE_ID = "sp-design-system"
DEFAULT_THEME = DeliverableTheme()


def _series_tokens(theme: DeliverableTheme) -> list[str]:
    return chart_series_from_positive(theme.colors.positive)


def design_system_style(theme: DeliverableTheme | None = None) -> str:
    resolved = theme or DEFAULT_THEME
    colors = resolved.colors
    series_vars = "\n".join(
        f"    --sp-chart-{index}: {color};" for index, color in enumerate(_series_tokens(resolved), start=1)
    )
    return f"""<style id="{DESIGN_SYSTEM_STYLE_ID}">
:root {{
    --sp-bg: {colors.bg};
    --sp-surface: {colors.surface};
    --sp-surface-alt: {colors.surface_alt};
    --sp-border: {colors.border};
    --sp-text: {colors.text};
    --sp-muted: {colors.muted};
    --sp-accent: {colors.accent};
    --sp-positive: {colors.positive};
    --sp-warning: {colors.warning};
    --sp-negative: {colors.negative};
    --sp-chart-grid: {colors.chart_grid};
    --sp-chart-axis: {colors.chart_axis};
{series_vars}
    --sp-font: {resolved.font_family};
    --sp-font-size: {resolved.font_size_base_px}px;
    --sp-space: {resolved.spacing_unit_px}px;
    --sp-space-2: {resolved.spacing_unit_px * 2}px;
    --sp-space-3: {resolved.spacing_unit_px * 3}px;
    --sp-space-4: {resolved.spacing_unit_px * 4}px;
    --sp-radius: {resolved.radius_px}px;
}}
body {{
    background: var(--sp-bg) !important;
    color: var(--sp-text) !important;
    font-family: var(--sp-font) !important;
    font-size: var(--sp-font-size);
}}
.sp-dashboard,
.sp-report {{
    color: var(--sp-text);
}}
.sp-section {{
    margin-block: var(--sp-space-3);
}}
.sp-section > h1,
.sp-section > h2,
.sp-section > h3,
.sp-dashboard h1,
.sp-dashboard h2,
.sp-dashboard h3,
.sp-report h1,
.sp-report h2,
.sp-report h3 {{
    color: var(--sp-text);
    font-family: var(--sp-font);
}}
.sp-kpi-card,
.sp-chart-card {{
    background: var(--sp-surface);
    border: 1px solid var(--sp-border);
    border-radius: var(--sp-radius);
    padding: var(--sp-space-2);
}}
.sp-kpi-value {{
    color: var(--sp-text);
    font-size: calc(var(--sp-font-size) * 2);
    font-weight: 700;
}}
.sp-kpi-label,
.sp-axis-label,
.sp-legend,
.sp-muted {{
    color: var(--sp-muted);
}}
.sp-delta-up {{
    color: var(--sp-positive);
}}
.sp-delta-down {{
    color: var(--sp-negative);
}}
.sp-badge {{
    display: inline-flex;
    align-items: center;
    border: 1px solid var(--sp-border);
    border-radius: var(--sp-radius);
    background: var(--sp-surface-alt);
    color: var(--sp-muted);
    padding: calc(var(--sp-space) / 2) var(--sp-space);
}}
.sp-data-table {{
    color: var(--sp-text);
}}
.sp-data-table th {{
    background: var(--sp-surface-alt);
    color: var(--sp-muted);
    border-bottom: 1px solid var(--sp-border);
    padding: var(--sp-space);
}}
.sp-data-table td {{
    border-bottom: 1px solid var(--sp-border);
    padding: var(--sp-space);
}}
.sp-bar {{
    background: var(--sp-chart-1);
    border-radius: var(--sp-radius) var(--sp-radius) 0 0;
}}
.sp-bar.sp-series-2 {{ background: var(--sp-chart-2); }}
.sp-bar.sp-series-3 {{ background: var(--sp-chart-3); }}
.sp-bar.sp-series-4 {{ background: var(--sp-chart-4); }}
.sp-bar.sp-series-5 {{ background: var(--sp-chart-5); }}
.sp-bar.sp-series-6 {{ background: var(--sp-chart-6); }}
.sp-chart-rank-1,
.sp-rank-1 {{
    background: var(--sp-chart-1);
    fill: var(--sp-chart-1);
    stroke: var(--sp-chart-1);
}}
.sp-chart-rank-2,
.sp-rank-2 {{
    background: var(--sp-chart-2);
    fill: var(--sp-chart-2);
    stroke: var(--sp-chart-2);
}}
.sp-chart-rank-3,
.sp-rank-3 {{
    background: var(--sp-chart-3);
    fill: var(--sp-chart-3);
    stroke: var(--sp-chart-3);
}}
.sp-chart-rank-4,
.sp-rank-4 {{
    background: var(--sp-chart-4);
    fill: var(--sp-chart-4);
    stroke: var(--sp-chart-4);
}}
.sp-chart-rank-5,
.sp-rank-5 {{
    background: var(--sp-chart-5);
    fill: var(--sp-chart-5);
    stroke: var(--sp-chart-5);
}}
.sp-chart-rank-6,
.sp-rank-6 {{
    background: var(--sp-chart-6);
    fill: var(--sp-chart-6);
    stroke: var(--sp-chart-6);
}}
.sp-legend-swatch {{
    background: var(--sp-chart-1);
    border-radius: 2px;
}}
.sp-pie-slice-label,
.sp-donut-slice-label {{
    font-family: var(--sp-font);
    font-size: 8.5px;
    font-weight: 700;
    fill: var(--sp-bg);
    stroke: rgba(255, 255, 255, 0.78);
    stroke-width: 2px;
    paint-order: stroke;
    stroke-linejoin: round;
    text-anchor: middle;
}}
</style>"""


def theme_token_map(theme: DeliverableTheme | None = None) -> dict:
    resolved = theme or DEFAULT_THEME
    colors = resolved.colors
    return {
        "version": resolved.version,
        "bg": colors.bg,
        "surface": colors.surface,
        "surfaceAlt": colors.surface_alt,
        "border": colors.border,
        "text": colors.text,
        "muted": colors.muted,
        "accent": colors.accent,
        "positive": colors.positive,
        "warning": colors.warning,
        "negative": colors.negative,
        "chartGrid": colors.chart_grid,
        "chartAxis": colors.chart_axis,
        "chartSeries": _series_tokens(resolved),
        "fontFamily": resolved.font_family,
        "fontSizeBasePx": resolved.font_size_base_px,
        "spacingUnitPx": resolved.spacing_unit_px,
        "radiusPx": resolved.radius_px,
    }
