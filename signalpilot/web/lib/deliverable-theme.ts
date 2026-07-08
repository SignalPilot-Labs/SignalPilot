import type { CSSProperties } from "react";
import type { DeliverableTheme } from "./types";

// Keep in sync with gateway/gateway/models/deliverable_theme.py.
export const DEFAULT_POSITIVE_COLOR = "#00ff88";
export const DEFAULT_CHART_SERIES = ["#087a3d", "#0fa45a", "#35c978", "#8eeaa8", "#c8f8d4", "#e7fcec"];

export const DEFAULT_DELIVERABLE_THEME: DeliverableTheme = {
  version: 1,
  colors: {
    bg: "#050505",
    surface: "#0a0a0a",
    surface_alt: "#0d0d0d",
    border: "#222222",
    text: "#eeeeee",
    muted: "#999999",
    accent: "#ffffff",
    positive: DEFAULT_POSITIVE_COLOR,
    warning: "#ffaa00",
    negative: "#ff4444",
    chart_grid: "#1f1f1f",
    chart_axis: "#999999",
  },
  chart_series: DEFAULT_CHART_SERIES,
  font_family: '"SF Mono", "Fira Code", "Cascadia Code", ui-monospace, monospace',
  font_size_base_px: 14,
  spacing_unit_px: 8,
  radius_px: 6,
};

type ThemeCssVars = CSSProperties & Record<`--sp-${string}`, string>;

const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

function expandHex(value: string): string {
  if (/^#[0-9a-fA-F]{3}$/.test(value)) {
    return `#${value[1]}${value[1]}${value[2]}${value[2]}${value[3]}${value[3]}`.toLowerCase();
  }
  return value.toLowerCase();
}

function mixChannel(channel: number, target: number, amount: number): number {
  return Math.round(channel + (target - channel) * amount);
}

function mixRgb(rgb: [number, number, number], target: [number, number, number], amount: number): string {
  return `#${rgb
    .map((channel, index) => mixChannel(channel, target[index], amount).toString(16).padStart(2, "0"))
    .join("")}`;
}

export function chartSeriesFromPositive(positive: string): string[] {
  if (!HEX_RE.test(positive)) return [...DEFAULT_CHART_SERIES];
  const normalized = expandHex(positive);
  if (normalized === DEFAULT_POSITIVE_COLOR) return [...DEFAULT_CHART_SERIES];

  const rgb: [number, number, number] = [
    Number.parseInt(normalized.slice(1, 3), 16),
    Number.parseInt(normalized.slice(3, 5), 16),
    Number.parseInt(normalized.slice(5, 7), 16),
  ];
  const black: [number, number, number] = [0, 0, 0];
  const white: [number, number, number] = [255, 255, 255];
  return [
    mixRgb(rgb, black, 0.35),
    mixRgb(rgb, black, 0.18),
    normalized,
    mixRgb(rgb, white, 0.32),
    mixRgb(rgb, white, 0.58),
    mixRgb(rgb, white, 0.78),
  ];
}

export function themeWithGeneratedChartSeries(theme: DeliverableTheme): DeliverableTheme {
  return {
    ...theme,
    colors: { ...theme.colors },
    chart_series: chartSeriesFromPositive(theme.colors.positive),
  };
}

export function themeToCssVars(theme: DeliverableTheme): ThemeCssVars {
  const chartSeries = chartSeriesFromPositive(theme.colors.positive);
  const vars: ThemeCssVars = {
    "--sp-bg": theme.colors.bg,
    "--sp-surface": theme.colors.surface,
    "--sp-surface-alt": theme.colors.surface_alt,
    "--sp-border": theme.colors.border,
    "--sp-text": theme.colors.text,
    "--sp-muted": theme.colors.muted,
    "--sp-accent": theme.colors.accent,
    "--sp-positive": theme.colors.positive,
    "--sp-warning": theme.colors.warning,
    "--sp-negative": theme.colors.negative,
    "--sp-chart-grid": theme.colors.chart_grid,
    "--sp-chart-axis": theme.colors.chart_axis,
    "--sp-font": theme.font_family,
    "--sp-font-size": `${theme.font_size_base_px}px`,
    "--sp-space": `${theme.spacing_unit_px}px`,
    "--sp-space-2": `${theme.spacing_unit_px * 2}px`,
    "--sp-space-3": `${theme.spacing_unit_px * 3}px`,
    "--sp-space-4": `${theme.spacing_unit_px * 4}px`,
    "--sp-radius": `${theme.radius_px}px`,
  };
  chartSeries.forEach((color, index) => {
    vars[`--sp-chart-${index + 1}`] = color;
  });
  return vars;
}

export function cloneTheme(theme: DeliverableTheme): DeliverableTheme {
  return {
    ...theme,
    colors: { ...theme.colors },
    chart_series: [...theme.chart_series],
  };
}
