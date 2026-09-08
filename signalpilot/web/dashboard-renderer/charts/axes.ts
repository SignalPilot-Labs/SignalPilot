/**
 * Axis, legend, tooltip and grid fragments shared by the option builders.
 * Axis formatting is adapted from the Lightdash extraction in
 * `dashboard/lightdash/LightdashCartesianChart.tsx` (see ../UPSTREAM.md and
 * ../LICENSE.lightdash).
 *
 * Print-path module: relative imports only, no React, no DOM.
 */
import type { DatasetRows } from "../datasets";
import {
  allFirstOfMonth,
  formatAxisDate,
  formatAxisNumber,
  formatValue,
  parseIsoDate,
  toNumber,
} from "../format";
import type { DashboardAxis, DashboardFormat } from "../schema";
import type { ThemeTokens } from "../theme";

export type AxisKind = "category" | "time" | "value";

export type XAxisModel = {
  kind: AxisKind;
  /** Distinct category labels in first-seen order (category axis only). */
  categories: string[];
  /** Index of each row's category (category axis only). */
  categoryIndex: number[];
  /** Numeric x per row (time: epoch ms, value: number, else undefined). */
  numeric: (number | undefined)[];
  monthly: boolean;
};

export function xAxisKind(axis: DashboardAxis): AxisKind {
  if (axis.type === "date") return "time";
  if (axis.type === "number") return "value";
  return "category";
}

export function buildXAxisModel(axis: DashboardAxis, rows: DatasetRows): XAxisModel {
  const kind = xAxisKind(axis);
  const values = rows.map((row) => row[axis.column]);
  const categories: string[] = [];
  const index = new Map<string, number>();
  const categoryIndex: number[] = [];
  const numeric: (number | undefined)[] = [];
  for (const value of values) {
    const label = value === null || value === undefined ? "–" : String(value);
    let position = index.get(label);
    if (position === undefined) {
      position = categories.length;
      index.set(label, position);
      categories.push(label);
    }
    categoryIndex.push(position);
    numeric.push(
      kind === "time" ? parseIsoDate(value) : kind === "value" ? toNumber(value) : undefined,
    );
  }
  return {
    kind,
    categories,
    categoryIndex,
    numeric,
    monthly: kind === "time" && allFirstOfMonth(values),
  };
}

type AxisOption = Record<string, unknown>;

export function xAxisOption(
  axis: DashboardAxis,
  model: XAxisModel,
  tokens: ThemeTokens,
  options: { horizontal?: boolean; truncateLabels?: boolean } = {},
): AxisOption {
  const base: AxisOption = {
    name: axis.label,
    nameLocation: "middle",
    nameGap: options.horizontal ? 60 : 28,
    nameTextStyle: { color: tokens.textMuted, fontFamily: tokens.fontFamily },
    axisLine: { lineStyle: { color: tokens.axisLine } },
    axisTick: { show: false },
    axisLabel: {
      color: tokens.textMuted,
      fontFamily: tokens.fontFamily,
      hideOverlap: true,
      margin: 10,
      ...(options.truncateLabels ? { width: 120, overflow: "truncate" } : {}),
    },
    splitLine: { show: false },
  };
  if (model.kind === "category") {
    return { ...base, type: "category", data: model.categories };
  }
  if (model.kind === "time") {
    const monthly = model.monthly;
    return {
      ...base,
      type: "time",
      axisLabel: {
        ...(base.axisLabel as object),
        formatter: (value: number) => formatAxisDate(value, monthly),
      },
    };
  }
  return {
    ...base,
    type: "value",
    scale: true,
    axisLabel: {
      ...(base.axisLabel as object),
      formatter: (value: number) => formatAxisNumber(value),
    },
    splitLine: { lineStyle: { color: tokens.gridLine } },
  };
}

/** Value axis. No axis name: the tile title names the measure. */
export function valueAxisOption(tokens: ThemeTokens, format?: DashboardFormat): AxisOption {
  return {
    type: "value",
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: tokens.textMuted,
      fontFamily: tokens.fontFamily,
      formatter: (value: number) => formatAxisNumber(value, format),
    },
    splitLine: { lineStyle: { color: tokens.gridLine } },
  };
}

/** Items up to this count use a plain legend that wraps onto more rows. */
export const LEGEND_SCROLL_THRESHOLD = 8;

export function legendOption(tokens: ThemeTokens, show: boolean, itemCount = 0): AxisOption {
  return show
    ? {
        show: true,
        bottom: 0,
        left: "center",
        orient: "horizontal",
        type: itemCount > LEGEND_SCROLL_THRESHOLD ? "scroll" : "plain",
        itemGap: 10,
        icon: "roundRect",
        itemWidth: 12,
        itemHeight: 8,
        textStyle: { color: tokens.textSecondary, fontFamily: tokens.fontFamily },
        pageTextStyle: { color: tokens.textMuted },
      }
    : { show: false };
}

export function gridOption(hasLegend: boolean, hasXName: boolean): AxisOption {
  return {
    top: 12,
    right: 16,
    left: 8,
    bottom: (hasLegend ? 32 : 4) + (hasXName ? 18 : 0),
    containLabel: true,
  };
}

export function tooltipBase(tokens: ThemeTokens, trigger: "axis" | "item"): AxisOption {
  return {
    trigger,
    renderMode: "html",
    appendTo: "body",
    confine: false,
    backgroundColor: tokens.tooltipBackground,
    borderColor: tokens.tooltipBorder,
    textStyle: { color: tokens.tooltipText, fontFamily: tokens.fontFamily },
    extraCssText:
      "max-width:min(320px,calc(100vw - 24px));white-space:normal;overflow-wrap:anywhere;z-index:1000;",
  };
}

/** Heading text for a tooltip over one x position. */
export function formatXValue(model: XAxisModel, rowIndex: number, raw: unknown): string {
  if (model.kind === "time") {
    const timestamp = model.numeric[rowIndex];
    return timestamp === undefined ? String(raw ?? "–") : formatAxisDate(timestamp, model.monthly);
  }
  if (model.kind === "value") return formatValue(raw);
  return model.categories[model.categoryIndex[rowIndex]] ?? "–";
}
