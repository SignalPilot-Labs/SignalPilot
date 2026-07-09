"""Render static HTML dashboards/reports from governed analysis packets."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from gateway.models.deliverable_theme import DeliverableTheme
from gateway.string_utils import string_value as _string

from .design_system import DESIGN_SYSTEM_STYLE_ID, design_system_style
from .renderer import DEFAULT_DELIVERY_MODEL
from .trace_loader import DeliveryPacket

LOGGER = logging.getLogger(__name__)

_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_TIMEOUT_SECONDS = 240.0
_DEFAULT_MAX_TOKENS = 20_000
_DEFAULT_TOOL_LOOP_LIMIT = 8
_DELIVERABLE_TOOL_NAMES = {"create_dashboard", "create_report", "edit_dashboard", "edit_report"}
_COMPONENT_LAYOUT_GUARD_ID = "sp-component-layout-guard"
_COMPONENT_LAYOUT_GUARD = f"""<style id="{_COMPONENT_LAYOUT_GUARD_ID}">
.sp-dashboard,
.sp-report,
.sp-section,
.sp-card,
.sp-kpi-card,
.sp-chart-card,
.sp-chart,
.sp-table-wrap,
.chart-container,
.chart,
.table-wrap {{
    box-sizing: border-box;
    min-width: 0;
}}
.sp-dashboard *,
.sp-report *,
.sp-section *,
.sp-card *,
.sp-kpi-card *,
.sp-chart-card *,
.sp-chart *,
.sp-table-wrap *,
.chart-container *,
.chart *,
.table-wrap * {{
    box-sizing: border-box;
}}
.sp-dashboard,
.sp-report {{
    width: 100%;
    max-width: 1280px;
    margin: 0 auto;
}}
.sp-grid,
.sp-kpi-grid {{
    display: grid;
    gap: 16px;
    align-items: stretch;
}}
.sp-grid {{
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 430px), 1fr));
}}
.sp-kpi-grid {{
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
}}
.sp-card,
.sp-kpi-card,
.sp-chart-card {{
    overflow: visible;
}}
.sp-chart-card {{
    display: flex;
    flex-direction: column;
    gap: 12px;
}}
.sp-chart-card h3 {{
    line-height: 1.35;
    margin-bottom: 0;
}}
.sp-chart,
.chart,
.chart-container {{
    position: relative;
    width: 100%;
    min-height: 340px;
}}
.sp-chart {{
    height: auto;
}}
.sp-chart > svg,
svg.sp-chart-svg,
.sp-chart svg,
.chart svg,
.chart-container svg {{
    display: block;
    width: 100%;
    height: 100%;
    max-width: 100%;
    overflow: visible;
}}
.sp-chart canvas,
.chart canvas,
.chart-container canvas {{
    display: block;
    width: 100% !important;
    height: 100% !important;
}}
.sp-bar-chart,
.bar-chart,
.sp-line-chart,
.line-chart,
.sp-area-chart,
.area-chart,
.sp-scatter-chart,
.scatter-chart,
.sp-heatmap,
.heatmap {{
    width: 100%;
    min-height: 240px;
}}
.sp-bar-chart,
.bar-chart {{
    display: flex;
    flex-direction: row;
    align-items: stretch;
    gap: 8px;
    height: 340px;
    min-height: 340px;
    padding: 0.5rem 0 0;
}}
.sp-bar-chart > .chart-content,
.bar-chart > .chart-content {{
    display: flex;
    flex-direction: row;
    align-items: stretch;
    gap: 8px;
    width: 100%;
    height: 100%;
    min-height: 0;
}}
.sp-bar-chart .sp-bar-group,
.sp-bar-chart .bar-group,
.bar-chart .sp-bar-group,
.bar-chart .bar-group {{
    display: grid;
    flex: 1 1 0;
    grid-template-rows: 1.4rem minmax(0, 1fr) 3.2rem;
    gap: 0.4rem;
    justify-items: center;
    align-items: end;
    height: 100%;
    min-width: 0;
    min-height: 0;
}}
.sp-bar-chart .sp-bar-value,
.sp-bar-chart .bar-value,
.bar-chart .sp-bar-value,
.bar-chart .bar-value {{
    grid-row: 1;
    align-self: end;
    margin: 0;
    line-height: 1.2;
}}
.sp-bar-chart .bar-track,
.sp-bar-chart .sp-bar-track,
.bar-chart .bar-track,
.bar-chart .sp-bar-track {{
    grid-row: 2;
    align-self: stretch;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    width: min(100%, 72px);
    height: 100%;
    min-height: 0;
}}
.sp-bar-chart .sp-bar,
.sp-bar-chart .bar,
.bar-chart .sp-bar,
.bar-chart .bar {{
    grid-row: 2;
    align-self: end;
    flex: 0 0 auto;
    width: min(100%, 72px);
    min-height: 2px;
    max-height: 100%;
}}
.sp-bar-chart .sp-bar-label,
.sp-bar-chart .bar-label,
.bar-chart .sp-bar-label,
.bar-chart .bar-label {{
    grid-row: 3;
    align-self: start;
    line-height: 1.2;
    margin: 0;
    max-width: 8.5rem;
}}
.sp-horizontal-bar-chart,
.horizontal-bar-chart,
.sp-pipeline-chart,
.pipeline-chart,
.sp-funnel-chart,
.funnel-chart {{
    display: flex;
    flex-direction: column;
    gap: 0.65rem;
    height: auto;
    min-height: 0;
    padding: 0.25rem 0 0;
}}
.sp-horizontal-bar-chart .sp-bar-group,
.sp-horizontal-bar-chart .bar-group,
.horizontal-bar-chart .sp-bar-group,
.horizontal-bar-chart .bar-group,
.sp-pipeline-chart .sp-bar-group,
.sp-pipeline-chart .bar-group,
.pipeline-chart .sp-bar-group,
.pipeline-chart .bar-group,
.sp-funnel-chart .sp-bar-group,
.sp-funnel-chart .bar-group,
.funnel-chart .sp-bar-group,
.funnel-chart .bar-group {{
    display: grid;
    grid-template-columns: minmax(7.5rem, 11rem) minmax(0, 1fr) max-content;
    grid-template-rows: 1fr;
    gap: 0.75rem;
    align-items: center;
    justify-items: stretch;
    height: auto;
    min-height: 2rem;
}}
.sp-horizontal-bar-chart .sp-bar-label,
.sp-horizontal-bar-chart .bar-label,
.horizontal-bar-chart .sp-bar-label,
.horizontal-bar-chart .bar-label,
.sp-pipeline-chart .sp-bar-label,
.sp-pipeline-chart .bar-label,
.pipeline-chart .sp-bar-label,
.pipeline-chart .bar-label,
.sp-funnel-chart .sp-bar-label,
.sp-funnel-chart .bar-label,
.funnel-chart .sp-bar-label,
.funnel-chart .bar-label {{
    grid-row: 1;
    grid-column: 1;
    align-self: center;
    max-width: none;
    text-align: right;
}}
.sp-horizontal-bar-chart .bar-track,
.sp-horizontal-bar-chart .sp-bar-track,
.horizontal-bar-chart .bar-track,
.horizontal-bar-chart .sp-bar-track,
.sp-pipeline-chart .bar-track,
.sp-pipeline-chart .sp-bar-track,
.pipeline-chart .bar-track,
.pipeline-chart .sp-bar-track,
.sp-funnel-chart .bar-track,
.sp-funnel-chart .sp-bar-track,
.funnel-chart .bar-track,
.funnel-chart .sp-bar-track {{
    grid-row: 1;
    grid-column: 2;
    width: 100%;
    min-width: 0;
    min-height: 1.5rem;
}}
.sp-horizontal-bar-chart .sp-bar,
.sp-horizontal-bar-chart .bar,
.horizontal-bar-chart .sp-bar,
.horizontal-bar-chart .bar,
.sp-pipeline-chart .sp-bar,
.sp-pipeline-chart .bar,
.pipeline-chart .sp-bar,
.pipeline-chart .bar,
.sp-funnel-chart .sp-bar,
.sp-funnel-chart .bar,
.funnel-chart .sp-bar,
.funnel-chart .bar {{
    grid-row: auto;
    height: 100%;
    max-height: none;
}}
.sp-horizontal-bar-chart .sp-bar-value,
.sp-horizontal-bar-chart .bar-value,
.horizontal-bar-chart .sp-bar-value,
.horizontal-bar-chart .bar-value,
.sp-pipeline-chart .sp-bar-value,
.sp-pipeline-chart .bar-value,
.pipeline-chart .sp-bar-value,
.pipeline-chart .bar-value,
.sp-funnel-chart .sp-bar-value,
.sp-funnel-chart .bar-value,
.funnel-chart .sp-bar-value,
.funnel-chart .bar-value {{
    grid-row: 1;
    grid-column: 3;
    align-self: center;
    white-space: nowrap;
}}
.sp-bar-chart:has(.bar-track .sp-bar[style*="width"]),
.sp-bar-chart:has(.bar-track .bar[style*="width"]),
.sp-bar-chart:has(.sp-bar-track .sp-bar[style*="width"]),
.sp-bar-chart:has(.sp-bar-track .bar[style*="width"]),
.bar-chart:has(.bar-track .sp-bar[style*="width"]),
.bar-chart:has(.bar-track .bar[style*="width"]),
.bar-chart:has(.sp-bar-track .sp-bar[style*="width"]),
.bar-chart:has(.sp-bar-track .bar[style*="width"]) {{
    flex-direction: column;
    gap: 0.65rem;
    height: auto;
    min-height: 0;
    padding: 0.25rem 0 0;
}}
.sp-bar-chart:has(.bar-track .sp-bar[style*="width"]) .sp-bar-group,
.sp-bar-chart:has(.bar-track .bar[style*="width"]) .sp-bar-group,
.sp-bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .sp-bar-group,
.sp-bar-chart:has(.sp-bar-track .bar[style*="width"]) .sp-bar-group,
.bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-group,
.bar-chart:has(.bar-track .bar[style*="width"]) .bar-group,
.bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-group,
.bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-group {{
    grid-template-columns: minmax(7.5rem, 11rem) minmax(0, 1fr) max-content;
    grid-template-rows: 1fr;
    gap: 0.75rem;
    align-items: center;
    justify-items: stretch;
    height: auto;
    min-height: 2rem;
}}
.sp-bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-label,
.sp-bar-chart:has(.bar-track .bar[style*="width"]) .bar-label,
.sp-bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-label,
.sp-bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-label,
.bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-label,
.bar-chart:has(.bar-track .bar[style*="width"]) .bar-label,
.bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-label,
.bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-label {{
    grid-row: 1;
    grid-column: 1;
    align-self: center;
    max-width: none;
    text-align: right;
}}
.sp-bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-track,
.sp-bar-chart:has(.bar-track .bar[style*="width"]) .bar-track,
.sp-bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .sp-bar-track,
.sp-bar-chart:has(.sp-bar-track .bar[style*="width"]) .sp-bar-track,
.bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-track,
.bar-chart:has(.bar-track .bar[style*="width"]) .bar-track,
.bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .sp-bar-track,
.bar-chart:has(.sp-bar-track .bar[style*="width"]) .sp-bar-track {{
    grid-row: 1;
    grid-column: 2;
    width: 100%;
    min-width: 0;
}}
.sp-bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-value,
.sp-bar-chart:has(.bar-track .bar[style*="width"]) .bar-value,
.sp-bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-value,
.sp-bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-value,
.bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-value,
.bar-chart:has(.bar-track .bar[style*="width"]) .bar-value,
.bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-value,
.bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-value {{
    grid-row: 1;
    grid-column: 3;
    align-self: center;
    white-space: nowrap;
}}
.sp-line-chart,
.line-chart,
.sp-area-chart,
.area-chart,
.sp-scatter-chart,
.scatter-chart {{
    display: block;
    height: 320px;
}}
.sp-pie-chart,
.pie-chart,
.sp-donut-chart,
.donut-chart {{
    width: 100%;
    max-width: none;
    min-height: 300px;
    display: grid;
    grid-template-columns: minmax(190px, 260px) minmax(170px, 1fr);
    gap: 1.25rem;
    align-items: center;
    justify-content: center;
    margin-inline: auto;
}}
.sp-pie-graphic,
.sp-donut-graphic {{
    width: min(100%, 260px) !important;
    height: auto !important;
    aspect-ratio: 1 / 1;
    justify-self: center;
}}
.sp-pie-chart svg,
.pie-chart svg,
.sp-donut-chart svg,
.donut-chart svg {{
    width: min(100%, 260px) !important;
    height: auto !important;
    aspect-ratio: 1 / 1;
    max-height: 260px;
}}
.sp-pie-legend,
.sp-donut-legend {{
    width: 100%;
}}
.sp-pie-legend-item,
.sp-donut-legend-item {{
    min-width: 0;
}}
.sp-table-wrap,
.table-wrap {{
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
}}
.sp-data-table,
.data-table,
.sp-table-wrap table,
.table-wrap table {{
    width: 100%;
    border-collapse: collapse;
    table-layout: auto;
}}
.sp-data-table th,
.data-table th,
.sp-table-wrap th,
.table-wrap th {{
    white-space: nowrap;
}}
.sp-data-table td,
.data-table td,
.sp-table-wrap td,
.table-wrap td {{
    max-width: 24rem;
    overflow-wrap: anywhere;
}}
@media (max-width: 640px) {{
    .sp-grid,
    .sp-kpi-grid {{
        grid-template-columns: 1fr;
    }}
    .sp-chart,
    .chart,
    .chart-container {{
        min-height: 300px;
        height: auto;
    }}
    .sp-horizontal-bar-chart .sp-bar-group,
    .sp-horizontal-bar-chart .bar-group,
    .horizontal-bar-chart .sp-bar-group,
    .horizontal-bar-chart .bar-group,
    .sp-pipeline-chart .sp-bar-group,
    .sp-pipeline-chart .bar-group,
    .pipeline-chart .sp-bar-group,
    .pipeline-chart .bar-group,
    .sp-funnel-chart .sp-bar-group,
    .sp-funnel-chart .bar-group,
    .funnel-chart .sp-bar-group,
    .funnel-chart .bar-group {{
        grid-template-columns: 1fr;
        grid-template-rows: auto 1.8rem auto;
        gap: 0.35rem;
    }}
    .sp-horizontal-bar-chart .sp-bar-label,
    .sp-horizontal-bar-chart .bar-label,
    .horizontal-bar-chart .sp-bar-label,
    .horizontal-bar-chart .bar-label,
    .sp-pipeline-chart .sp-bar-label,
    .sp-pipeline-chart .bar-label,
    .pipeline-chart .sp-bar-label,
    .pipeline-chart .bar-label,
    .sp-funnel-chart .sp-bar-label,
    .sp-funnel-chart .bar-label,
    .funnel-chart .sp-bar-label,
    .funnel-chart .bar-label {{
        grid-row: 1;
        grid-column: 1;
        text-align: left;
    }}
    .sp-horizontal-bar-chart .bar-track,
    .sp-horizontal-bar-chart .sp-bar-track,
    .horizontal-bar-chart .bar-track,
    .horizontal-bar-chart .sp-bar-track,
    .sp-pipeline-chart .bar-track,
    .sp-pipeline-chart .sp-bar-track,
    .pipeline-chart .bar-track,
    .pipeline-chart .sp-bar-track,
    .sp-funnel-chart .bar-track,
    .sp-funnel-chart .sp-bar-track,
    .funnel-chart .bar-track,
    .funnel-chart .sp-bar-track {{
        grid-row: 2;
        grid-column: 1;
    }}
    .sp-horizontal-bar-chart .sp-bar-value,
    .sp-horizontal-bar-chart .bar-value,
    .horizontal-bar-chart .sp-bar-value,
    .horizontal-bar-chart .bar-value,
    .sp-pipeline-chart .sp-bar-value,
    .sp-pipeline-chart .bar-value,
    .pipeline-chart .sp-bar-value,
    .pipeline-chart .bar-value,
    .sp-funnel-chart .sp-bar-value,
    .sp-funnel-chart .bar-value,
    .funnel-chart .sp-bar-value,
    .funnel-chart .bar-value {{
        grid-row: 3;
        grid-column: 1;
    }}
    .sp-bar-chart:has(.bar-track .sp-bar[style*="width"]) .sp-bar-group,
    .sp-bar-chart:has(.bar-track .bar[style*="width"]) .sp-bar-group,
    .sp-bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .sp-bar-group,
    .sp-bar-chart:has(.sp-bar-track .bar[style*="width"]) .sp-bar-group,
    .bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-group,
    .bar-chart:has(.bar-track .bar[style*="width"]) .bar-group,
    .bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-group,
    .bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-group {{
        grid-template-columns: 1fr;
        grid-template-rows: auto 1.8rem auto;
        gap: 0.35rem;
    }}
    .sp-bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-label,
    .sp-bar-chart:has(.bar-track .bar[style*="width"]) .bar-label,
    .sp-bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-label,
    .sp-bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-label,
    .bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-label,
    .bar-chart:has(.bar-track .bar[style*="width"]) .bar-label,
    .bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-label,
    .bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-label {{
        grid-row: 1;
        grid-column: 1;
        text-align: left;
    }}
    .sp-bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-track,
    .sp-bar-chart:has(.bar-track .bar[style*="width"]) .bar-track,
    .sp-bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .sp-bar-track,
    .sp-bar-chart:has(.sp-bar-track .bar[style*="width"]) .sp-bar-track,
    .bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-track,
    .bar-chart:has(.bar-track .bar[style*="width"]) .bar-track,
    .bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .sp-bar-track,
    .bar-chart:has(.sp-bar-track .bar[style*="width"]) .sp-bar-track {{
        grid-row: 2;
        grid-column: 1;
    }}
    .sp-bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-value,
    .sp-bar-chart:has(.bar-track .bar[style*="width"]) .bar-value,
    .sp-bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-value,
    .sp-bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-value,
    .bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-value,
    .bar-chart:has(.bar-track .bar[style*="width"]) .bar-value,
    .bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-value,
    .bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-value {{
        grid-row: 3;
        grid-column: 1;
    }}
    .sp-pie-chart,
    .pie-chart,
    .sp-donut-chart,
    .donut-chart {{
        grid-template-columns: 1fr;
        min-height: 0;
    }}
    .sp-pie-chart svg,
    .pie-chart svg,
    .sp-donut-chart svg,
    .donut-chart svg {{
        max-width: 260px;
        margin-inline: auto;
    }}
}}
</style>"""
_BAR_CHART_LAYOUT_GUARD_ID = "sp-bar-chart-layout-guard"
_BAR_CHART_LAYOUT_GUARD = f"""<style id="{_BAR_CHART_LAYOUT_GUARD_ID}">
.sp-bar-chart,
.bar-chart {{
    display: flex !important;
    flex-direction: row !important;
    align-items: stretch !important;
    gap: 8px;
    height: 340px;
    min-height: 340px;
    padding: 0.5rem 0 0;
}}
.sp-bar-chart > .chart-content,
.bar-chart > .chart-content {{
    display: flex !important;
    flex-direction: row !important;
    align-items: stretch !important;
    gap: 8px;
    width: 100%;
    height: 100%;
    min-height: 0;
}}
.sp-bar-chart .sp-bar-group,
.sp-bar-chart .bar-group,
.bar-chart .sp-bar-group,
.bar-chart .bar-group {{
    display: grid !important;
    grid-template-rows: 1.4rem minmax(0, 1fr) 3.2rem;
    gap: 0.4rem;
    height: 100% !important;
    align-items: end !important;
    justify-items: center;
    min-height: 0;
}}
.sp-bar-chart .sp-bar-value,
.sp-bar-chart .bar-value,
.bar-chart .sp-bar-value,
.bar-chart .bar-value {{
    grid-row: 1;
    align-self: end;
    line-height: 1.2;
    margin: 0;
}}
.sp-bar-chart .bar-track,
.sp-bar-chart .sp-bar-track,
.bar-chart .bar-track,
.bar-chart .sp-bar-track {{
    grid-row: 2;
    align-self: stretch;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    width: min(100%, 72px);
    height: 100%;
    min-height: 0;
}}
.sp-bar-chart .sp-bar,
.sp-bar-chart .bar,
.bar-chart .sp-bar,
.bar-chart .bar {{
    grid-row: 2;
    align-self: end;
    flex: 0 0 auto !important;
    min-height: 2px;
    max-height: 100%;
}}
.sp-bar-chart .sp-bar-label,
.sp-bar-chart .bar-label,
.bar-chart .sp-bar-label,
.bar-chart .bar-label {{
    grid-row: 3;
    align-self: start;
    flex: 0 0 auto;
    line-height: 1.2;
    margin: 0;
}}
.sp-horizontal-bar-chart,
.horizontal-bar-chart,
.sp-pipeline-chart,
.pipeline-chart,
.sp-funnel-chart,
.funnel-chart {{
    display: flex !important;
    flex-direction: column !important;
    gap: 0.65rem !important;
    height: auto !important;
    min-height: 0 !important;
    padding: 0.25rem 0 0 !important;
}}
.sp-horizontal-bar-chart .sp-bar-group,
.sp-horizontal-bar-chart .bar-group,
.horizontal-bar-chart .sp-bar-group,
.horizontal-bar-chart .bar-group,
.sp-pipeline-chart .sp-bar-group,
.sp-pipeline-chart .bar-group,
.pipeline-chart .sp-bar-group,
.pipeline-chart .bar-group,
.sp-funnel-chart .sp-bar-group,
.sp-funnel-chart .bar-group,
.funnel-chart .sp-bar-group,
.funnel-chart .bar-group {{
    display: grid !important;
    grid-template-columns: minmax(7.5rem, 11rem) minmax(0, 1fr) max-content;
    grid-template-rows: 1fr !important;
    gap: 0.75rem;
    align-items: center !important;
    justify-items: stretch;
    height: auto !important;
    min-height: 2rem;
}}
.sp-horizontal-bar-chart .sp-bar-label,
.sp-horizontal-bar-chart .bar-label,
.horizontal-bar-chart .sp-bar-label,
.horizontal-bar-chart .bar-label,
.sp-pipeline-chart .sp-bar-label,
.sp-pipeline-chart .bar-label,
.pipeline-chart .sp-bar-label,
.pipeline-chart .bar-label,
.sp-funnel-chart .sp-bar-label,
.sp-funnel-chart .bar-label,
.funnel-chart .sp-bar-label,
.funnel-chart .bar-label {{
    grid-row: 1 !important;
    grid-column: 1;
    align-self: center;
    max-width: none;
    text-align: right;
}}
.sp-horizontal-bar-chart .bar-track,
.sp-horizontal-bar-chart .sp-bar-track,
.horizontal-bar-chart .bar-track,
.horizontal-bar-chart .sp-bar-track,
.sp-pipeline-chart .bar-track,
.sp-pipeline-chart .sp-bar-track,
.pipeline-chart .bar-track,
.pipeline-chart .sp-bar-track,
.sp-funnel-chart .bar-track,
.sp-funnel-chart .sp-bar-track,
.funnel-chart .bar-track,
.funnel-chart .sp-bar-track {{
    grid-row: 1;
    grid-column: 2;
    width: 100%;
    min-width: 0;
    min-height: 1.5rem;
}}
.sp-horizontal-bar-chart .sp-bar,
.sp-horizontal-bar-chart .bar,
.horizontal-bar-chart .sp-bar,
.horizontal-bar-chart .bar,
.sp-pipeline-chart .sp-bar,
.sp-pipeline-chart .bar,
.pipeline-chart .sp-bar,
.pipeline-chart .bar,
.sp-funnel-chart .sp-bar,
.sp-funnel-chart .bar,
.funnel-chart .sp-bar,
.funnel-chart .bar {{
    grid-row: auto;
    height: 100%;
    max-height: none;
}}
.sp-horizontal-bar-chart .sp-bar-value,
.sp-horizontal-bar-chart .bar-value,
.horizontal-bar-chart .sp-bar-value,
.horizontal-bar-chart .bar-value,
.sp-pipeline-chart .sp-bar-value,
.sp-pipeline-chart .bar-value,
.pipeline-chart .sp-bar-value,
.pipeline-chart .bar-value,
.sp-funnel-chart .sp-bar-value,
.sp-funnel-chart .bar-value,
.funnel-chart .sp-bar-value,
.funnel-chart .bar-value {{
    grid-row: 1 !important;
    grid-column: 3;
    align-self: center;
    white-space: nowrap;
}}
.sp-bar-chart:has(.bar-track .sp-bar[style*="width"]),
.sp-bar-chart:has(.bar-track .bar[style*="width"]),
.sp-bar-chart:has(.sp-bar-track .sp-bar[style*="width"]),
.sp-bar-chart:has(.sp-bar-track .bar[style*="width"]),
.bar-chart:has(.bar-track .sp-bar[style*="width"]),
.bar-chart:has(.bar-track .bar[style*="width"]),
.bar-chart:has(.sp-bar-track .sp-bar[style*="width"]),
.bar-chart:has(.sp-bar-track .bar[style*="width"]) {{
    flex-direction: column !important;
    gap: 0.65rem !important;
    height: auto !important;
    min-height: 0 !important;
    padding: 0.25rem 0 0 !important;
}}
.sp-bar-chart:has(.bar-track .sp-bar[style*="width"]) .sp-bar-group,
.sp-bar-chart:has(.bar-track .bar[style*="width"]) .sp-bar-group,
.sp-bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .sp-bar-group,
.sp-bar-chart:has(.sp-bar-track .bar[style*="width"]) .sp-bar-group,
.bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-group,
.bar-chart:has(.bar-track .bar[style*="width"]) .bar-group,
.bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-group,
.bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-group {{
    grid-template-columns: minmax(7.5rem, 11rem) minmax(0, 1fr) max-content;
    grid-template-rows: 1fr !important;
    gap: 0.75rem;
    align-items: center !important;
    justify-items: stretch;
    height: auto !important;
    min-height: 2rem;
}}
.sp-bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-label,
.sp-bar-chart:has(.bar-track .bar[style*="width"]) .bar-label,
.sp-bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-label,
.sp-bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-label,
.bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-label,
.bar-chart:has(.bar-track .bar[style*="width"]) .bar-label,
.bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-label,
.bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-label {{
    grid-row: 1 !important;
    grid-column: 1;
    align-self: center;
    max-width: none;
    text-align: right;
}}
.sp-bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-track,
.sp-bar-chart:has(.bar-track .bar[style*="width"]) .bar-track,
.sp-bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .sp-bar-track,
.sp-bar-chart:has(.sp-bar-track .bar[style*="width"]) .sp-bar-track,
.bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-track,
.bar-chart:has(.bar-track .bar[style*="width"]) .bar-track,
.bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .sp-bar-track,
.bar-chart:has(.sp-bar-track .bar[style*="width"]) .sp-bar-track {{
    grid-row: 1;
    grid-column: 2;
    width: 100%;
    min-width: 0;
}}
.sp-bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-value,
.sp-bar-chart:has(.bar-track .bar[style*="width"]) .bar-value,
.sp-bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-value,
.sp-bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-value,
.bar-chart:has(.bar-track .sp-bar[style*="width"]) .bar-value,
.bar-chart:has(.bar-track .bar[style*="width"]) .bar-value,
.bar-chart:has(.sp-bar-track .sp-bar[style*="width"]) .bar-value,
.bar-chart:has(.sp-bar-track .bar[style*="width"]) .bar-value {{
    grid-row: 1 !important;
    grid-column: 3;
    align-self: center;
    white-space: nowrap;
}}
</style>"""
_HTML_COMPONENT_CONTRACT = """
Component contract:
- Use canonical component scopes instead of ad hoc layout classes: .sp-dashboard or .sp-report root, .sp-section, .sp-grid, .sp-kpi-grid, .sp-kpi-card, .sp-chart-card, .sp-chart, .sp-table-wrap, and table.sp-data-table.
- A SignalPilot design-system stylesheet is injected server-side. Never define colors, fonts, border radius, or component visual styling in local CSS.
- Never use hex, rgb(), hsl(), or named color literals. Use only these tokens: var(--sp-bg), var(--sp-surface), var(--sp-surface-alt), var(--sp-border), var(--sp-text), var(--sp-muted), var(--sp-accent), var(--sp-positive), var(--sp-warning), var(--sp-negative), var(--sp-chart-grid), var(--sp-chart-axis), and var(--sp-chart-1) through var(--sp-chart-6).
- Inline SVG colors must use CSS styles such as style="fill:var(--sp-chart-1)"; presentation attributes like fill cannot reliably hold var() tokens.
- Chart colors are rank encoding by default, not unrelated series decoration: within each chart, sort numeric marks by value/score and use var(--sp-chart-1) for the greatest value, var(--sp-chart-2) for the next greatest value, continuing toward lighter greens for lower values. Apply this to bar, column, pie, donut, line, area, scatter, radar, heatmap, legend, and SVG marks. Use the same rank color for the mark, its legend swatch, and direct label. Only preserve categorical identity colors when the chart explicitly compares stable categories across multiple charts, and still choose from the green chart tokens.
- Use .sp-chart-rank-1 through .sp-chart-rank-6 or var(--sp-chart-1) through var(--sp-chart-6) for ranked chart marks. Positive and negative deltas use .sp-delta-up and .sp-delta-down. Do not restyle preset sp-* components.
- Every chart must live inside .sp-chart-card and a fixed-size .sp-chart wrapper. The chart wrapper must define explicit height and min-height. Do not use percentage heights unless every parent in that chart scope has an explicit height.
- SVG charts must use a viewBox, preserveAspectRatio, and width/height 100%. Keep axes, labels, legends, and value annotations inside the viewBox so they are not clipped.
- Column charts must use .sp-bar-chart > .sp-bar-group > .sp-bar, with groups at height: 100%, bars anchored to the bottom, a visible minimum height for non-zero values, and separate value/bar/label rows so a 100% bar cannot overlap the chart title or labels. Do not wrap vertical column bars in .bar-track or .sp-bar-track; those track wrappers are reserved for width-based horizontal bars.
- Pipeline, funnel, stage, and ranked-list bar charts must use .sp-horizontal-bar-chart, .sp-pipeline-chart, or .sp-funnel-chart in addition to .sp-bar-chart. Each .sp-bar-group must be one horizontal row with label, width-based bar track, and value in separate columns; do not render pipeline stages as vertical columns.
- Line, area, scatter, and heatmap charts must use SVG inside .sp-line-chart, .sp-area-chart, .sp-scatter-chart, or .sp-heatmap. Compute plot bounds from data, reserve padding for axes and labels, and clamp points/marks inside the plot area.
- Pie and donut charts must use .sp-pie-chart or .sp-donut-chart with a square SVG graphic (.sp-pie-graphic or .sp-donut-graphic), preserveAspectRatio="xMidYMid meet", direct slice labels, a matching legend, and no remote images or canvas dependencies. Slice paths must be mathematically circular: use the same radius for x/y arc radii, close each slice to the center, and keep the SVG width and height equal so the chart cannot render as an ellipse or irregular circle.
- Tables must use .sp-table-wrap > table.sp-data-table. The wrapper owns horizontal overflow, headers stay readable, numeric columns align consistently, and cells wrap instead of forcing a viewport wider than 320px.
- KPI cards must use .sp-kpi-grid and .sp-kpi-card. Keep KPI cards compact and separate from chart scopes.
- Empty, missing, or single-row data states must render an explicit no-data/insufficient-data block inside the component scope instead of leaving a blank chart or table.
"""

HtmlKind = Literal["report", "dashboard"]
FollowupRenderMode = Literal["edit_existing", "refresh_data"]
SnapshotFetcher = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class HtmlDeliverableResult:
    kind: HtmlKind
    title: str
    html: str
    data_json: dict | list | str | int | float | bool | None = None
    report_id: str | None = None


class HtmlOrchestrator:
    def __init__(
        self,
        *,
        provider: str = "anthropic",
        model: str | None = None,
        timeout_seconds: float | None = None,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        fetch_snapshot: SnapshotFetcher | None = None,
    ) -> None:
        self.provider = (provider or "anthropic").strip().lower()
        self.model = (model or os.getenv("SIGNALPILOT_ORCHESTRATOR_MODEL") or DEFAULT_DELIVERY_MODEL).strip()
        self.timeout_seconds = _timeout_seconds(timeout_seconds)
        self.max_tokens = _max_tokens()
        self.tool_loop_limit = _tool_loop_limit()
        self.api_key = api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY")
        self._http_client = http_client
        self._fetch_snapshot = fetch_snapshot

    async def render(self, packet: DeliveryPacket, *, theme: DeliverableTheme | None = None) -> HtmlDeliverableResult:
        if self.provider != "anthropic" or not self.model or not self.api_key:
            raise RuntimeError("HTML orchestrator is not configured")
        return await self._anthropic_render(_html_model_payload(packet), packet, theme)

    async def render_followup(
        self,
        *,
        instruction: str,
        existing: dict[str, Any],
        packet: DeliveryPacket | None,
        mode: FollowupRenderMode,
        theme: DeliverableTheme | None = None,
    ) -> HtmlDeliverableResult:
        if self.provider != "anthropic" or not self.model or not self.api_key:
            raise RuntimeError("HTML orchestrator is not configured")
        return await self._anthropic_render(
            _followup_model_payload(instruction=instruction, existing=existing, packet=packet, mode=mode),
            packet,
            theme,
        )

    async def _anthropic_render(
        self,
        payload: dict[str, Any],
        packet: DeliveryPacket | None,
        theme: DeliverableTheme | None,
    ) -> HtmlDeliverableResult:
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": json.dumps(
                    payload,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
            }
        ]
        fetched_snapshots: dict[str, Any] = {}
        tool_choice = _tool_choice_for_payload(payload)
        for _ in range(self.tool_loop_limit):
            response = await self._anthropic_request(
                messages,
                allow_fetch_snapshot=packet is not None,
                tool_choice=tool_choice,
            )
            content = response.get("content") or []
            result = await self._result_from_content(packet, content, fetched_snapshots, theme)
            if result is not None:
                return result
            tool_results = await self._tool_results(packet, content, fetched_snapshots)
            if not tool_results:
                text = _anthropic_text(response)
                parsed = _parse_json_object(text)
                result = _html_result_from_payload(parsed)
                if result is not None:
                    return _normalize_html_result(result, fetched_snapshots, theme=theme)
                raise ValueError("HTML orchestrator did not return a deliverable")
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": tool_results})
        raise TimeoutError(f"HTML orchestrator exceeded tool loop limit ({self.tool_loop_limit})")

    async def _anthropic_request(
        self,
        messages: list[dict[str, Any]],
        *,
        allow_fetch_snapshot: bool = True,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        request_body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "system": _html_orchestrator_system_prompt(),
            "tools": _html_tools(allow_fetch_snapshot=allow_fetch_snapshot),
            "messages": messages,
        }
        if tool_choice:
            request_body["tool_choice"] = {"type": "tool", "name": tool_choice}
        headers = {
            "x-api-key": self.api_key or "",
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        if self._http_client is not None:
            response = await self._http_client.post(_ANTHROPIC_MESSAGES_URL, headers=headers, json=request_body)
            response.raise_for_status()
            return response.json()
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(_ANTHROPIC_MESSAGES_URL, headers=headers, json=request_body)
            response.raise_for_status()
            return response.json()

    async def _result_from_content(
        self,
        packet: DeliveryPacket | None,
        content: list[Any],
        fetched_snapshots: dict[str, Any],
        theme: DeliverableTheme | None,
    ) -> HtmlDeliverableResult | None:
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            name = _string(item.get("name"))
            args = _tool_args_dict(item)
            if args is None:
                return None
            if name in _DELIVERABLE_TOOL_NAMES:
                result = _html_result_from_tool(name, args)
                return _normalize_html_result(result, fetched_snapshots, theme=theme) if result is not None else None
            if name == "fetch_snapshot":
                continue
        text = "\n".join(
            _string(item.get("text")) for item in content if isinstance(item, dict) and item.get("type") == "text"
        ).strip()
        if not text:
            return None
        try:
            result = _html_result_from_payload(_parse_json_object(text))
            return _normalize_html_result(result, fetched_snapshots, theme=theme) if result is not None else None
        except Exception:
            LOGGER.debug("HTML orchestrator text was not final JSON")
            return None

    async def _tool_results(
        self,
        packet: DeliveryPacket | None,
        content: list[Any],
        fetched_snapshots: dict[str, Any],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            tool_use_id = _string(item.get("id"))
            name = _string(item.get("name"))
            args = _tool_args_dict(item)
            if not tool_use_id or args is None:
                continue
            if name == "fetch_snapshot":
                tool_result = await self._fetch_snapshot_result(packet, args)
                snapshot = _find_snapshot(packet, args) if packet is not None else None
                snapshot_name = _string(snapshot.get("name")) if isinstance(snapshot, dict) else ""
                if snapshot_name and not (isinstance(tool_result, dict) and tool_result.get("error")):
                    fetched_snapshots[snapshot_name] = tool_result
            elif name in _DELIVERABLE_TOOL_NAMES:
                tool_result = {
                    "error": (
                        "The deliverable tool call must include a non-empty title and a complete replacement html "
                        "document. Call the same deliverable tool again with all required fields."
                    )
                }
            else:
                tool_result = {"ok": True}
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": json.dumps(tool_result, ensure_ascii=True),
                }
            )
        return results

    async def _fetch_snapshot_result(
        self,
        packet: DeliveryPacket | None,
        args: dict[str, Any],
    ) -> Any:
        if packet is None:
            return {"error": "no refreshed analysis packet is available for this edit"}
        snapshot = _find_snapshot(packet, args)
        if snapshot is None:
            return {"error": "snapshot not found"}
        if self._fetch_snapshot is None:
            return snapshot
        return await self._fetch_snapshot(snapshot)


async def render_html_deliverable(
    packet: DeliveryPacket,
    *,
    api_key: str | None = None,
    orchestrator: HtmlOrchestrator | None = None,
    fetch_snapshot: SnapshotFetcher | None = None,
    theme: DeliverableTheme | None = None,
) -> HtmlDeliverableResult:
    if orchestrator is not None:
        return await orchestrator.render(packet, theme=theme)
    return await HtmlOrchestrator(api_key=api_key, fetch_snapshot=fetch_snapshot).render(packet, theme=theme)


async def render_followup(
    instruction: str,
    existing: dict[str, Any],
    packet: DeliveryPacket | None,
    mode: FollowupRenderMode,
    *,
    api_key: str | None = None,
    orchestrator: HtmlOrchestrator | None = None,
    fetch_snapshot: SnapshotFetcher | None = None,
    theme: DeliverableTheme | None = None,
) -> HtmlDeliverableResult:
    if orchestrator is not None:
        return await orchestrator.render_followup(
            instruction=instruction,
            existing=existing,
            packet=packet,
            mode=mode,
            theme=theme,
        )
    return await HtmlOrchestrator(api_key=api_key, fetch_snapshot=fetch_snapshot).render_followup(
        instruction=instruction,
        existing=existing,
        packet=packet,
        mode=mode,
        theme=theme,
    )


def _html_model_payload(packet: DeliveryPacket) -> dict[str, Any]:
    outputs = packet.final_notebook_outputs
    statement = packet.final_statement.statement if packet.final_statement else ""
    return {
        "userRequest": packet.user_request,
        "answer": statement
        or _string(outputs.get("finalAnswer") or outputs.get("final_answer"))
        or _string(outputs.get("summary")),
        "summary": _string(outputs.get("summary")),
        "dataSnapshots": packet.data_snapshots,
        "charts": packet.charts,
    }


def _followup_model_payload(
    *,
    instruction: str,
    existing: dict[str, Any],
    packet: DeliveryPacket | None,
    mode: FollowupRenderMode,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task": "update_existing_html_deliverable",
        "mode": mode,
        "instruction": instruction,
        "existing": {
            "reportId": _string(existing.get("report_id") or existing.get("reportId")),
            "kind": _string(existing.get("kind")) or "report",
            "title": _string(existing.get("title")),
            "html": _string(existing.get("html")),
            "dataJson": existing.get("data_json", existing.get("dataJson")),
        },
    }
    if packet is not None:
        payload["freshAnalysis"] = _html_model_payload(packet)
    else:
        payload["freshAnalysis"] = None
    return payload


def _timeout_seconds(value: float | None) -> float:
    if value is not None:
        return max(float(value), 0.1)
    raw = os.getenv("SIGNALPILOT_ORCHESTRATOR_TIMEOUT_SECONDS", "").strip()
    if raw:
        try:
            return max(float(raw), 0.1)
        except ValueError:
            LOGGER.warning("Invalid SIGNALPILOT_ORCHESTRATOR_TIMEOUT_SECONDS=%r; using default", raw)
    return _DEFAULT_TIMEOUT_SECONDS


def _max_tokens() -> int:
    raw = os.getenv("SIGNALPILOT_ORCHESTRATOR_MAX_TOKENS", "").strip()
    if raw:
        try:
            return max(int(raw), 1024)
        except ValueError:
            LOGGER.warning("Invalid SIGNALPILOT_ORCHESTRATOR_MAX_TOKENS=%r; using default", raw)
    return _DEFAULT_MAX_TOKENS


def _tool_loop_limit() -> int:
    raw = os.getenv("SIGNALPILOT_ORCHESTRATOR_TOOL_LOOP_LIMIT", "").strip()
    if raw:
        try:
            return max(int(raw), 2)
        except ValueError:
            LOGGER.warning("Invalid SIGNALPILOT_ORCHESTRATOR_TOOL_LOOP_LIMIT=%r; using default", raw)
    return _DEFAULT_TOOL_LOOP_LIMIT


def _tool_choice_for_payload(payload: dict[str, Any]) -> str | None:
    if payload.get("task") != "update_existing_html_deliverable":
        return None
    existing = payload.get("existing") if isinstance(payload.get("existing"), dict) else {}
    kind = _string(existing.get("kind")).strip().lower()
    return "edit_dashboard" if kind == "dashboard" else "edit_report"


def _html_orchestrator_system_prompt() -> str:
    return (
        "You create one complete self-contained inline HTML document for a SignalPilot "
        "Notion deliverable. Choose dashboard or report from the user's ask and the "
        "available snapshot data. Use only supplied packet facts and snapshot data. "
        "Do not use CDNs, external fonts, external scripts, remote images, or network "
        "requests. Embed the data used by the page inside "
        '<script type="application/json" id="sp-data">...</script>. Return the '
        "deliverable by calling create_dashboard or create_report with title, html, "
        "and data_json. If editing, call edit_dashboard or edit_report. The HTML must "
        "stay below the Notion inline embed limit: target under 3.5 MB and never exceed "
        "4 MB serialized UTF-8 HTML. Saved reports have a 5 MB hard cap. Aggregate or "
        "sample large tables, avoid raw full-table dumps, and do not duplicate bulky "
        "data in both rendered markup and the data island. The page should still be "
        "useful and complete within that size budget. "
        "The HTML must "
        "not include confidence score, caveats, methodology, audit notes, trail links, "
        "handoff notes, source-query commentary, or internal execution language. "
        "For follow-up edits, preserve the existing report_id when one is supplied "
        "and return a full replacement HTML document for the same dashboard/report. "
        "When a follow-up edit uses a forced edit_dashboard or edit_report tool, call "
        "that tool with the full title, html, report_id, and data_json; do not ask for "
        "more data or call placeholder/partial tools. " + _HTML_COMPONENT_CONTRACT
    )


def _html_tools(*, allow_fetch_snapshot: bool = True) -> list[dict[str, Any]]:
    data_json_schema = {
        "type": "object",
        "description": "Structured data embedded in the HTML data island",
        "additionalProperties": True,
    }
    tools = [
        {
            "name": "create_dashboard",
            "description": "Return a complete static HTML dashboard deliverable.",
            "input_schema": _deliverable_tool_schema(data_json_schema, require_data=True),
        },
        {
            "name": "create_report",
            "description": "Return a complete static HTML report deliverable.",
            "input_schema": _deliverable_tool_schema(data_json_schema, require_data=False),
        },
        {
            "name": "edit_dashboard",
            "description": "Return edited complete static HTML dashboard content.",
            "input_schema": _deliverable_tool_schema(data_json_schema, require_data=False, include_id=True),
        },
        {
            "name": "edit_report",
            "description": "Return edited complete static HTML report content.",
            "input_schema": _deliverable_tool_schema(data_json_schema, require_data=False, include_id=True),
        },
    ]
    if allow_fetch_snapshot:
        tools.append(
            {
                "name": "fetch_snapshot",
                "description": "Fetch one saved data snapshot by name or URL before rendering.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
            }
        )
    return tools


def _deliverable_tool_schema(
    data_json_schema: dict[str, Any],
    *,
    require_data: bool,
    include_id: bool = False,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "title": {"type": "string"},
        "html": {"type": "string"},
        "data_json": data_json_schema,
    }
    required = ["title", "html"]
    if require_data:
        required.append("data_json")
    if include_id:
        properties["report_id"] = {"type": "string"}
    return {"type": "object", "properties": properties, "required": required}


def _tool_args_dict(item: dict[str, Any]) -> dict[str, Any] | None:
    args = item.get("input")
    return args if isinstance(args, dict) else None


def _html_result_from_tool(name: str, args: dict[str, Any]) -> HtmlDeliverableResult | None:
    kind: HtmlKind = "dashboard" if "dashboard" in name else "report"
    title = _string(args.get("title")).strip()
    html = _string(args.get("html")).strip()
    if not title or not html:
        return None
    data_json = args.get("data_json", args.get("dataJson"))
    return HtmlDeliverableResult(
        kind=kind,
        title=title,
        html=html,
        data_json=data_json,
        report_id=_string(args.get("report_id") or args.get("reportId")).strip() or None,
    )


def _html_result_from_payload(payload: dict[str, Any]) -> HtmlDeliverableResult | None:
    kind_raw = _string(payload.get("kind")).strip().lower()
    kind: HtmlKind = "dashboard" if kind_raw == "dashboard" else "report"
    title = _string(payload.get("title")).strip()
    html = _string(payload.get("html")).strip()
    if not title or not html:
        return None
    return HtmlDeliverableResult(
        kind=kind,
        title=title,
        html=html,
        data_json=payload.get("dataJson", payload.get("data_json")),
        report_id=_string(payload.get("reportId", payload.get("report_id"))).strip() or None,
    )


def _normalize_html_result(
    result: HtmlDeliverableResult,
    fetched_snapshots: dict[str, Any],
    *,
    theme: DeliverableTheme | None = None,
) -> HtmlDeliverableResult:
    data_json = _merged_data_json(result.data_json, fetched_snapshots)
    html = _inject_data_island(result.html, data_json)
    html = _stabilize_common_chart_layouts(html, theme=theme)
    if html == result.html and data_json is result.data_json:
        return result
    return HtmlDeliverableResult(
        kind=result.kind,
        title=result.title,
        html=html,
        data_json=data_json,
        report_id=result.report_id,
    )


def _merged_data_json(
    data_json: dict | list | str | int | float | bool | None,
    fetched_snapshots: dict[str, Any],
) -> dict | list | str | int | float | bool | None:
    if not fetched_snapshots:
        return data_json
    if isinstance(data_json, dict):
        merged = dict(data_json)
        for name, value in fetched_snapshots.items():
            merged[name] = value
        return merged
    if data_json is None:
        return dict(fetched_snapshots)
    return {"data": data_json, **fetched_snapshots}


def _inject_data_island(
    html: str,
    data_json: dict | list | str | int | float | bool | None,
) -> str:
    if data_json is None:
        return html
    safe_json = _safe_script_json(data_json)
    data_script = f'<script type="application/json" id="sp-data">{safe_json}</script>'
    cleaned = re.sub(
        r"<script\b(?=[^>]*\bid=[\"']sp-data[\"'])[^>]*>.*?</script>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if re.search(r"<body\b[^>]*>", cleaned, flags=re.IGNORECASE):
        return re.sub(
            r"(<body\b[^>]*>)",
            "\\1\n    " + data_script,
            cleaned,
            count=1,
            flags=re.IGNORECASE,
        )
    return data_script + "\n" + cleaned


def _stabilize_common_chart_layouts(html: str, *, theme: DeliverableTheme | None = None) -> str:
    stabilized = _replace_head_style(
        html,
        style_id=DESIGN_SYSTEM_STYLE_ID,
        style=design_system_style(theme),
    )
    if _uses_chart_or_table_components(stabilized):
        stabilized = _inject_head_style(
            stabilized,
            style_id=_COMPONENT_LAYOUT_GUARD_ID,
            style=_COMPONENT_LAYOUT_GUARD,
        )
    if "bar-chart" in stabilized and "bar-group" in stabilized:
        stabilized = _inject_head_style(
            stabilized,
            style_id=_BAR_CHART_LAYOUT_GUARD_ID,
            style=_BAR_CHART_LAYOUT_GUARD,
        )
    return stabilized


def _uses_chart_or_table_components(html: str) -> bool:
    if re.search(r"<(?:svg|canvas|table)\b", html, flags=re.IGNORECASE):
        return True
    return bool(
        re.search(
            r"\b(?:"
            r"sp-dashboard|sp-report|sp-grid|sp-kpi-grid|sp-kpi-card|"
            r"sp-chart-card|sp-chart|sp-table-wrap|sp-data-table|"
            r"chart-container|bar-chart|line-chart|area-chart|scatter-chart|"
            r"pie-chart|donut-chart|heatmap|data-table|table-wrap"
            r")\b",
            html,
            flags=re.IGNORECASE,
        )
    )


def _inject_head_style(html: str, *, style_id: str, style: str) -> str:
    if style_id in html:
        return html
    if re.search(r"</head>", html, flags=re.IGNORECASE):
        return re.sub(
            r"</head>",
            "    " + style + "\n</head>",
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    if re.search(r"<html\b[^>]*>", html, flags=re.IGNORECASE):
        return re.sub(
            r"(<html\b[^>]*>)",
            "\\1\n<head>\n    " + style + "\n</head>",
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    return style + "\n" + html


def _replace_head_style(html: str, *, style_id: str, style: str) -> str:
    cleaned = re.sub(
        rf"<style\b(?=[^>]*\bid=[\"']{re.escape(style_id)}[\"'])[^>]*>.*?</style>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return _inject_head_style(cleaned, style_id=style_id, style=style)


def _safe_script_json(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _find_snapshot(packet: DeliveryPacket, args: dict[str, Any]) -> dict[str, Any] | None:
    name = _string(args.get("name")).strip()
    url = _string(args.get("url")).strip()
    for snapshot in packet.data_snapshots:
        if name and _string(snapshot.get("name")).strip() == name:
            return snapshot
        if url and _string(snapshot.get("url")).strip() == url:
            return snapshot
    return None


def _anthropic_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in data.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(parts).strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    stripped = text.strip()
    if stripped.startswith("{"):
        parsed, _ = decoder.raw_decode(stripped)
        if isinstance(parsed, dict):
            return parsed
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("HTML orchestrator did not return a JSON object")
