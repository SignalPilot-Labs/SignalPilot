/**
 * 12-column tile layout. Tiles with `grid` are placed exactly; the rest flow
 * after the placed tiles with per-type default sizes, packing left to right
 * and wrapping at 12 columns.
 *
 * Print-path module: relative imports only, no React, no DOM.
 */
import type { DashboardChart, DashboardSpec } from "./schema";

export const GRID_COLUMNS = 12;
export const GRID_GAP = 12;
const DEFAULT_ROW_HEIGHT = 72;

export type PlacedTile = { chartId: string; x: number; y: number; w: number; h: number };

export type PixelRect = { x: number; y: number; width: number; height: number };

function defaultTileSize(chart: DashboardChart): { w: number; h: number } {
  if (chart.type === "table") return { w: 12, h: 5 };
  if (chart.type === "kpi") return { w: 3, h: 2 };
  return { w: 6, h: 4 };
}

export function rowHeightOf(spec: DashboardSpec): number {
  return spec.layout?.rowHeight ?? DEFAULT_ROW_HEIGHT;
}

/**
 * Responsive layout mode. `full` honors explicit grids; `compact` (< 720 px)
 * and `narrow` (< 420 px) ignore them and auto-flow with wide tiles.
 */
export type LayoutMode = "full" | "compact" | "narrow";

const COMPACT_MAX_WIDTH = 720;
const NARROW_MAX_WIDTH = 420;

export function layoutModeForWidth(width: number): LayoutMode {
  if (width < NARROW_MAX_WIDTH) return "narrow";
  if (width < COMPACT_MAX_WIDTH) return "compact";
  return "full";
}

/** Tile size for a mode: heights never change, widths widen as space shrinks. */
function tileSizeForMode(chart: DashboardChart, mode: LayoutMode): { w: number; h: number } {
  const base = defaultTileSize(chart);
  if (mode === "full") return base;
  if (chart.type === "kpi") return { w: mode === "narrow" ? 12 : 6, h: base.h };
  return { w: 12, h: base.h };
}

type PlaceOptions = {
  /** Render only these charts (in spec order). */
  chartIds?: string[] | null;
  /** Ignore every `grid` and auto-flow all tiles (CLI with chart_ids). */
  ignoreGrid?: boolean;
  /** Responsive mode; anything but `full` implies `ignoreGrid`. Default `full`. */
  mode?: LayoutMode;
};

export function placeTiles(spec: DashboardSpec, options: PlaceOptions = {}): PlacedTile[] {
  const mode = options.mode ?? "full";
  const ignoreGrid = options.ignoreGrid || mode !== "full";
  const wanted = options.chartIds ? new Set(options.chartIds) : null;
  const charts = spec.charts.filter((chart) => !wanted || wanted.has(chart.id));
  const placed: PlacedTile[] = [];
  const flowing: DashboardChart[] = [];
  for (const chart of charts) {
    const grid = ignoreGrid ? undefined : chart.grid;
    if (grid) {
      const w = Math.min(grid.w, GRID_COLUMNS - grid.x);
      placed.push({ chartId: chart.id, x: grid.x, y: grid.y, w: Math.max(1, w), h: grid.h });
    } else {
      flowing.push(chart);
    }
  }
  let cursorX = 0;
  let cursorY = placed.reduce((max, tile) => Math.max(max, tile.y + tile.h), 0);
  let rowMaxH = 0;
  const flowed: PlacedTile[] = [];
  for (const chart of flowing) {
    const { w, h } = tileSizeForMode(chart, mode);
    if (cursorX + w > GRID_COLUMNS) {
      cursorX = 0;
      cursorY += rowMaxH;
      rowMaxH = 0;
    }
    flowed.push({ chartId: chart.id, x: cursorX, y: cursorY, w, h });
    cursorX += w;
    rowMaxH = Math.max(rowMaxH, h);
  }
  // Keep spec order so the DOM/SVG order matches the chart list.
  const byId = new Map<string, PlacedTile>();
  for (const tile of [...placed, ...flowed]) byId.set(tile.chartId, tile);
  return charts.map((chart) => byId.get(chart.id) as PlacedTile);
}

export function tileRect(
  tile: PlacedTile,
  canvasWidth: number,
  rowHeight: number,
  gap = GRID_GAP,
): PixelRect {
  const columnWidth = (canvasWidth - gap * (GRID_COLUMNS - 1)) / GRID_COLUMNS;
  return {
    x: tile.x * (columnWidth + gap),
    y: tile.y * (rowHeight + gap),
    width: tile.w * columnWidth + (tile.w - 1) * gap,
    height: tile.h * rowHeight + (tile.h - 1) * gap,
  };
}

export function gridHeight(tiles: PlacedTile[], rowHeight: number, gap = GRID_GAP): number {
  const rows = tiles.reduce((max, tile) => Math.max(max, tile.y + tile.h), 0);
  return rows === 0 ? 0 : rows * rowHeight + (rows - 1) * gap;
}
