/**
 * Small pieces shared by every ECharts option builder: theme resolution,
 * tooltip parameter shapes, the common option header and series data aligned
 * to an x-axis model.
 *
 * Print-path module: relative imports only, no React, no DOM.
 */
import type { EChartsOption } from "echarts";

import type { DatasetRows } from "../datasets";
import { toNumber } from "../format";
import type { DashboardFormat } from "../schema";
import type { DashboardTheme, ThemeTokens } from "../theme";
import { themeTokens } from "../theme";
import type { XAxisModel } from "./axes";

export type TooltipParam = {
  seriesName?: string;
  dataIndex?: number;
  data?: unknown;
  value?: unknown;
};

export function paramsArray(raw: unknown): TooltipParam[] {
  return (Array.isArray(raw) ? raw : [raw]) as TooltipParam[];
}

export function resolveTokens(theme: DashboardTheme | ThemeTokens | undefined): ThemeTokens {
  return typeof theme === "object" ? theme : themeTokens(theme);
}

/** Option keys every chart starts from: no animation, theme colors and font. */
export function baseOption(tokens: ThemeTokens): EChartsOption {
  return {
    animation: false,
    aria: { enabled: true },
    backgroundColor: "transparent",
    color: [...tokens.palette],
    textStyle: { fontFamily: tokens.fontFamily },
  };
}

export type SeriesSpec = {
  name: string;
  column: string;
  format?: DashboardFormat;
  /** Row indexes that belong to this series. */
  rowIndexes: number[];
};

export type Point = { value: unknown; rowIndex: number };

/** Series data aligned to the x model: category -> one slot per category. */
export function seriesData(
  spec: SeriesSpec,
  rows: DatasetRows,
  model: XAxisModel,
  horizontal: boolean,
): Point[] {
  if (model.kind === "category") {
    const slots: Point[] = model.categories.map(() => ({ value: null, rowIndex: -1 }));
    for (const rowIndex of spec.rowIndexes) {
      const y = toNumber(rows[rowIndex][spec.column]) ?? null;
      slots[model.categoryIndex[rowIndex]] = { value: y, rowIndex };
    }
    return slots;
  }
  const points: Point[] = [];
  for (const rowIndex of spec.rowIndexes) {
    const x = model.numeric[rowIndex];
    if (x === undefined) continue;
    const y = toNumber(rows[rowIndex][spec.column]) ?? null;
    points.push({ value: horizontal ? [y, x] : [x, y], rowIndex });
  }
  return points;
}
