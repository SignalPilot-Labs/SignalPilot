/**
 * Compose one SVG document for a dashboard: background, title, description,
 * filter summary, then every tile at its layout rect. Chart tiles embed the
 * ECharts server-side SVG; kpi/table tiles are drawn as SVG text.
 *
 * Print-path module: relative imports only, no React, no DOM.
 */
import * as echarts from "echarts";

import { buildChartOption, isOptionChart } from "../charts/options";
import type { DatasetRows } from "../datasets";
import { formatValue } from "../format";
import { gridHeight, placeTiles, rowHeightOf, tileRect, type PixelRect } from "../layout";
import { chartIsFailed, prepareChartRows, type ChartIssue, type FilterState } from "../prepare";
import type { DashboardChart, DashboardFilter, DashboardSpec } from "../schema";
import { themeTokens, type DashboardTheme, type ThemeTokens } from "../theme";
import { escapeXml, kpiBodySvg, svgText, tableBodySvg, truncateText, wrapText } from "./svg-tiles";

const PAGE_PADDING = 24;
const TILE_PADDING = 12;
const TILE_TITLE_HEIGHT = 30;

export type ComposeInput = {
  spec: DashboardSpec;
  datasets: Record<string, DatasetRows>;
  chartIds?: string[] | null;
  width?: number;
  theme?: DashboardTheme;
  filterState?: FilterState;
};

export type FailedTile = { id: string; code: string; message: string };

export type ComposeResult = {
  svg: string;
  width: number;
  height: number;
  rendered: string[];
  failed: FailedTile[];
};

function filterSummary(filters: DashboardFilter[] | undefined): string {
  if (!filters) return "";
  const parts: string[] = [];
  for (const filter of filters) {
    const value = filter.default;
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) {
      if (value.length === 0) continue;
      parts.push(`${filter.label}: ${value.map(String).join(", ")}`);
    } else if (typeof value === "object") {
      const range = value as Record<string, unknown>;
      const from = range.from ?? range.min;
      const to = range.to ?? range.max;
      if (from === undefined && to === undefined) continue;
      parts.push(`${filter.label}: ${from ?? "…"} to ${to ?? "…"}`);
    } else {
      parts.push(`${filter.label}: ${formatValue(value)}`);
    }
  }
  return parts.join("   ·   ");
}

/** Render a chart through ECharts SSR into an SVG fragment of the given size. */
function renderChartSvg(
  chart: DashboardChart,
  rows: DatasetRows,
  tokens: ThemeTokens,
  width: number,
  height: number,
): string {
  if (!isOptionChart(chart)) return "";
  const instance = echarts.init(null, null, {
    renderer: "svg",
    ssr: true,
    width: Math.max(1, Math.round(width)),
    height: Math.max(1, Math.round(height)),
  });
  try {
    instance.setOption(buildChartOption(chart, rows, tokens));
    return instance.renderToSVGString();
  } finally {
    instance.dispose();
  }
}

/** Nest an SVG document string at (x, y) inside a parent SVG. */
export function nestSvg(svg: string, x: number, y: number, width: number, height: number): string {
  const open = svg.indexOf("<svg");
  if (open < 0) return "";
  const body = svg.slice(open).replace(/^<svg\b/, "");
  // Strip absolute sizing so the nested viewport uses ours.
  const attrs = body
    .slice(0, body.indexOf(">"))
    .replace(/\s(width|height|x|y)="[^"]*"/g, "");
  const rest = body.slice(body.indexOf(">"));
  return `<svg x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${width.toFixed(1)}" height="${height.toFixed(1)}"${attrs}${rest}`;
}

function tileFrame(rect: PixelRect, tokens: ThemeTokens): string {
  return `<rect x="${rect.x.toFixed(1)}" y="${rect.y.toFixed(1)}" width="${rect.width.toFixed(1)}" height="${rect.height.toFixed(1)}" rx="8" ry="8" fill="${tokens.surface}" stroke="${tokens.border}" stroke-width="1"/>`;
}

function errorBand(rect: PixelRect, issues: ChartIssue[], tokens: ThemeTokens): string {
  const message = issues.map((issue) => issue.message).join(" ");
  const x = rect.x + TILE_PADDING;
  const width = rect.width - TILE_PADDING * 2;
  const lines = wrapText(message, width, 12, Math.max(1, Math.floor((rect.height - TILE_TITLE_HEIGHT - 16) / 16)));
  const bandHeight = lines.length * 16 + 12;
  const top = rect.y + TILE_TITLE_HEIGHT;
  const band = `<rect x="${x.toFixed(1)}" y="${top.toFixed(1)}" width="${width.toFixed(1)}" height="${bandHeight}" rx="4" fill="${tokens.errorBackground}"/>`;
  const text = lines
    .map((line, index) =>
      svgText(x + 8, top + 18 + index * 16, line, {
        size: 12,
        color: tokens.error,
        family: tokens.fontFamily,
      }),
    )
    .join("");
  return band + text;
}

function tileSvg(
  chart: DashboardChart,
  rect: PixelRect,
  rows: DatasetRows,
  issues: ChartIssue[],
  tokens: ThemeTokens,
): string {
  const parts = [tileFrame(rect, tokens)];
  const innerX = rect.x + TILE_PADDING;
  const innerWidth = rect.width - TILE_PADDING * 2;
  parts.push(
    svgText(innerX, rect.y + 20, truncateText(chart.title, innerWidth, 13), {
      size: 13,
      weight: 600,
      color: tokens.text,
      family: tokens.fontFamily,
    }),
  );
  const bodyY = rect.y + TILE_TITLE_HEIGHT;
  const bodyHeight = rect.height - TILE_TITLE_HEIGHT - TILE_PADDING;
  if (chartIsFailed(issues)) {
    parts.push(errorBand(rect, issues, tokens));
  } else if (chart.type === "kpi") {
    parts.push(
      `<g transform="translate(${innerX.toFixed(1)} ${bodyY.toFixed(1)})">${kpiBodySvg(chart, rows, tokens, innerWidth, bodyHeight)}</g>`,
    );
  } else if (chart.type === "table") {
    parts.push(
      `<g transform="translate(${innerX.toFixed(1)} ${bodyY.toFixed(1)})">${tableBodySvg(chart, rows, tokens, innerWidth, bodyHeight)}</g>`,
    );
  } else {
    const svg = renderChartSvg(chart, rows, tokens, innerWidth, bodyHeight);
    parts.push(nestSvg(svg, innerX, bodyY, innerWidth, bodyHeight));
  }
  return `<g data-chart-id="${escapeXml(chart.id)}" data-chart-type="${chart.type}">${parts.join("")}</g>`;
}

export function composeDashboardSvg(input: ComposeInput): ComposeResult {
  const { spec, datasets } = input;
  const width = Math.max(320, Math.round(input.width ?? 1280));
  const tokens = themeTokens(input.theme);
  const rendered: string[] = [];
  const failed: FailedTile[] = [];
  const parts: string[] = [];

  const contentWidth = width - PAGE_PADDING * 2;
  let cursorY = PAGE_PADDING;
  const titleLines = wrapText(spec.title, contentWidth, 18, 2);
  for (const line of titleLines) {
    cursorY += 20;
    parts.push(
      svgText(PAGE_PADDING, cursorY, line, {
        size: 18,
        weight: 600,
        color: tokens.text,
        family: tokens.fontFamily,
      }),
    );
  }
  if (spec.description) {
    for (const line of wrapText(spec.description, contentWidth, 13, 3)) {
      cursorY += 18;
      parts.push(
        svgText(PAGE_PADDING, cursorY, line, {
          size: 13,
          color: tokens.textSecondary,
          family: tokens.fontFamily,
        }),
      );
    }
  }
  const summary = filterSummary(spec.filters);
  if (summary) {
    cursorY += 18;
    parts.push(
      svgText(PAGE_PADDING, cursorY, truncateText(summary, contentWidth, 12), {
        size: 12,
        color: tokens.textMuted,
        family: tokens.fontFamily,
      }),
    );
  }
  cursorY += 16;

  const chartIds = input.chartIds ?? null;
  const tiles = placeTiles(spec, { chartIds, ignoreGrid: chartIds !== null });
  const rowHeight = rowHeightOf(spec);
  const chartsById = new Map(spec.charts.map((chart) => [chart.id, chart]));
  for (const tile of tiles) {
    const chart = chartsById.get(tile.chartId);
    if (!chart) continue;
    const rect = tileRect(tile, contentWidth, rowHeight);
    rect.x += PAGE_PADDING;
    rect.y += cursorY;
    const { rows, issues } = prepareChartRows(chart, spec, datasets, input.filterState);
    let svg: string;
    try {
      svg = tileSvg(chart, rect, rows, issues, tokens);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const issue: ChartIssue = { code: "render_error", message: `Chart "${chart.id}" failed to render: ${message}` };
      svg = tileSvg(chart, rect, [], [issue], tokens);
      failed.push({ id: chart.id, ...issue });
      parts.push(svg);
      continue;
    }
    parts.push(svg);
    if (chartIsFailed(issues)) {
      const first = issues.find((issue) => chartIsFailed([issue])) ?? issues[0];
      failed.push({ id: chart.id, code: first.code, message: first.message });
    } else {
      rendered.push(chart.id);
    }
  }
  const height = Math.round(cursorY + gridHeight(tiles, rowHeight) + PAGE_PADDING);
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" font-family="${escapeXml(tokens.fontFamily)}">` +
    `<rect x="0" y="0" width="${width}" height="${height}" fill="${tokens.background}"/>` +
    parts.join("") +
    "</svg>";
  return { svg, width, height, rendered, failed };
}
