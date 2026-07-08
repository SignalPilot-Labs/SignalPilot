import type { CSSProperties } from "react";
import type { DeliverableTheme } from "./types";

// Keep in sync with gateway/gateway/models/deliverable_theme.py.
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
    positive: "#00ff88",
    warning: "#ffaa00",
    negative: "#ff4444",
    chart_grid: "#1f1f1f",
    chart_axis: "#999999",
  },
  chart_series: ["#087a3d", "#0fa45a", "#35c978", "#8eeaa8", "#c8f8d4", "#e7fcec"],
  font_family: '"SF Mono", "Fira Code", "Cascadia Code", ui-monospace, monospace',
  font_size_base_px: 14,
  spacing_unit_px: 8,
  radius_px: 6,
};

type ThemeCssVars = CSSProperties & Record<`--sp-${string}`, string>;

export function themeToCssVars(theme: DeliverableTheme): ThemeCssVars {
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
  theme.chart_series.forEach((color, index) => {
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
