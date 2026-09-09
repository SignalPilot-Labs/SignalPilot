/**
 * Heatmap: one cell per (x, y) category pair, colored by a numeric value
 * through a continuous visualMap that spans the data range.
 *
 * Print-path module: relative imports only, no React, no DOM.
 */
import type { EChartsOption } from "echarts";

import type { DatasetRows } from "../datasets";
import { formatValue, toNumber } from "../format";
import type { HeatmapChart } from "../schema";
import type { DashboardTheme, ThemeTokens } from "../theme";
import { buildXAxisModel, categoryLabels, tooltipBase } from "./axes";
import { baseOption, paramsArray, resolveTokens } from "./option-helpers";

/** Cells above this count get no labels unless `show_values` says so. */
const LABEL_CELL_LIMIT = 100;

/** Mix two `#rrggbb` colors: 0 gives `from`, 1 gives `to`. */
export function mixHex(from: string, to: string, amount: number): string {
  const channel = (hex: string, offset: number) => parseInt(hex.slice(offset, offset + 2), 16);
  const parts = [1, 3, 5].map((offset) => {
    const mixed = channel(from, offset) + (channel(to, offset) - channel(from, offset)) * amount;
    return Math.round(mixed).toString(16).padStart(2, "0");
  });
  return `#${parts.join("")}`;
}

/** Sequential range from a faint tint of the first palette hue up to the hue. */
export function heatmapRange(tokens: ThemeTokens): [string, string] {
  const hue = tokens.palette[0];
  return [mixHex(tokens.surface, hue, tokens.name === "dark" ? 0.18 : 0.1), hue];
}

type Cell = {
  value: [number, number, number];
  rowIndex: number;
  /** Per-cell label color: light text on the darker half of the range. */
  label?: { color: string };
};

/** Label text that stays readable on a cell this far along the range. */
function cellLabelColor(ratio: number, tokens: ThemeTokens): string {
  if (tokens.name === "dark") return tokens.text;
  return ratio > 0.55 ? tokens.surface : tokens.text;
}

export function buildHeatmapOption(
  chart: HeatmapChart,
  rows: DatasetRows,
  theme?: DashboardTheme | ThemeTokens,
): EChartsOption {
  const tokens = resolveTokens(theme);
  const xModel = buildXAxisModel(chart.x, rows);
  const yModel = buildXAxisModel({ ...chart.y, type: "category" }, rows);
  const xLabels = categoryLabels(xModel);
  const format = chart.value.format;
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  const data: Cell[] = [];
  rows.forEach((row, rowIndex) => {
    const value = toNumber(row[chart.value.column]);
    if (value === undefined) return;
    min = Math.min(min, value);
    max = Math.max(max, value);
    data.push({ value: [xModel.categoryIndex[rowIndex], yModel.categoryIndex[rowIndex], value], rowIndex });
  });
  if (!Number.isFinite(min)) {
    min = 0;
    max = 0;
  }
  if (min === max) max = min + 1;
  for (const cell of data) {
    cell.label = { color: cellLabelColor((cell.value[2] - min) / (max - min), tokens) };
  }
  const cellCount = xModel.categories.length * yModel.categories.length;
  const showValues = chart.show_values ?? cellCount <= LABEL_CELL_LIMIT;
  const [low, high] = heatmapRange(tokens);
  const axisLabel = { color: tokens.textMuted, fontFamily: tokens.fontFamily, hideOverlap: true };
  const axisBase = {
    type: "category" as const,
    axisLine: { lineStyle: { color: tokens.axisLine } },
    axisTick: { show: false },
    splitArea: { show: false },
    nameLocation: "middle" as const,
    nameTextStyle: { color: tokens.textMuted, fontFamily: tokens.fontFamily },
  };

  return {
    ...baseOption(tokens),
    grid: { top: 12, right: 16, left: 8, bottom: 44 + (chart.x.label ? 18 : 0), containLabel: true },
    tooltip: {
      ...tooltipBase(tokens, "item"),
      formatter: (raw: unknown) => {
        const cell = paramsArray(raw)[0]?.data as Cell | undefined;
        const row = cell ? rows[cell.rowIndex] : undefined;
        if (!cell || !row) return "";
        return [
          `${chart.x.label ?? chart.x.column}: ${xLabels[cell.value[0]] ?? "–"}`,
          `${chart.y.label ?? chart.y.column}: ${yModel.categories[cell.value[1]] ?? "–"}`,
          `${chart.value.label ?? chart.value.column}: ${formatValue(cell.value[2], format)}`,
        ].join("<br/>");
      },
    },
    xAxis: { ...axisBase, data: xLabels, name: chart.x.label, nameGap: 28, axisLabel },
    yAxis: {
      ...axisBase,
      data: yModel.categories,
      inverse: true,
      name: chart.y.label,
      nameGap: 60,
      axisLabel: { ...axisLabel, width: 120, overflow: "truncate" },
    },
    visualMap: {
      type: "continuous",
      min,
      max,
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemWidth: 10,
      itemHeight: 140,
      inRange: { color: [low, high] },
      text: [formatValue(max, format), formatValue(min, format)],
      textStyle: { color: tokens.textMuted, fontFamily: tokens.fontFamily },
      formatter: (value: unknown) => formatValue(value, format),
    },
    series: [
      {
        id: chart.id,
        name: chart.value.label ?? chart.value.column,
        type: "heatmap",
        data,
        label: {
          show: showValues,
          fontFamily: tokens.fontFamily,
          fontSize: 11,
          formatter: (raw: unknown) => {
            const cell = (raw as { data?: Cell }).data;
            return formatValue(cell?.value[2], format);
          },
        },
        itemStyle: { borderColor: tokens.surface, borderWidth: 1 },
        emphasis: { itemStyle: { borderColor: tokens.text, borderWidth: 1 } },
      },
    ],
  };
}
