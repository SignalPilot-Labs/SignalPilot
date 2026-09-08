/**
 * Theme tokens shared by the React tiles, the ECharts option builder and the
 * SVG print path. Categorical hues are assigned in fixed order.
 *
 * Print-path module: relative imports only, no React, no DOM.
 */
export type DashboardTheme = "light" | "dark";

export type ThemeTokens = {
  name: DashboardTheme;
  fontFamily: string;
  background: string;
  surface: string;
  border: string;
  text: string;
  textSecondary: string;
  textMuted: string;
  gridLine: string;
  axisLine: string;
  tooltipBackground: string;
  tooltipBorder: string;
  tooltipText: string;
  error: string;
  errorBackground: string;
  palette: readonly string[];
};

// Unquoted on purpose: ECharts SSR writes the family into an SVG `style`
// attribute verbatim, and embedded double quotes break the XML.
const FONT_FAMILY = "DM Sans, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif";

export const LIGHT_THEME: ThemeTokens = {
  name: "light",
  fontFamily: FONT_FAMILY,
  background: "#f9f9f7",
  surface: "#fcfcfb",
  border: "#e1e0d9",
  text: "#0b0b0b",
  textSecondary: "#52514e",
  textMuted: "#898781",
  gridLine: "#e1e0d9",
  axisLine: "#c3c2b7",
  tooltipBackground: "#ffffff",
  tooltipBorder: "#e1e0d9",
  tooltipText: "#0b0b0b",
  error: "#b42318",
  errorBackground: "#fdecea",
  palette: [
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4",
    "#008300", "#4a3aa7", "#e34948", "#0e8a9e", "#8a6d3b",
  ],
};

const DARK_THEME: ThemeTokens = {
  name: "dark",
  fontFamily: FONT_FAMILY,
  background: "#0d0d0d",
  surface: "#1a1a19",
  border: "#2c2c2a",
  text: "#ffffff",
  textSecondary: "#c3c2b7",
  textMuted: "#898781",
  gridLine: "#2c2c2a",
  axisLine: "#383835",
  tooltipBackground: "#202024",
  tooltipBorder: "#3b3b42",
  tooltipText: "#ededed",
  error: "#f97066",
  errorBackground: "#3a1d1a",
  palette: [
    "#3987e5", "#d95926", "#199e70", "#c98500", "#d55181",
    "#4fb84f", "#9085e9", "#e66767", "#3bb3c7", "#c2a06a",
  ],
};

export function themeTokens(theme: DashboardTheme | undefined): ThemeTokens {
  return theme === "dark" ? DARK_THEME : LIGHT_THEME;
}
