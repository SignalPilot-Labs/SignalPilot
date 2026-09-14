/**
 * Pure ECharts option builders for bar | line | area | pie | scatter, and the
 * dispatcher that also routes combo and heatmap to their own builders.
 * No React, no DOM, no window: the same function feeds the browser tile and
 * the server-side SVG print path.
 *
 * Bar/line option structure adapted from the Lightdash extraction formerly
 * vendored in this repo (removed 2026-09-08). See ../UPSTREAM.md and
 * ../LICENSE.lightdash.
 */
import type { EChartsOption } from "echarts";

import type { DatasetRows } from "../datasets";
import { formatValue, toNumber } from "../format";
import type {
  CartesianChart,
  ComboChart,
  DashboardChart,
  HeatmapChart,
  PieChart,
  ScatterChart,
} from "../schema";
import type { DashboardTheme, ThemeTokens } from "../theme";
import {
  buildXAxisModel,
  formatXValue,
  gridOption,
  legendOption,
  tooltipBase,
  valueAxisOption,
  xAxisOption,
} from "./axes";
import { buildComboOption } from "./combo";
import { buildHeatmapOption } from "./heatmap";
import {
  baseOption,
  paramsArray,
  resolveTokens,
  seriesData,
  type SeriesSpec,
  type TooltipParam,
} from "./option-helpers";

export type ChartOptionChart =
  | CartesianChart
  | ComboChart
  | HeatmapChart
  | PieChart
  | ScatterChart;

function seriesSpecs(chart: CartesianChart, rows: DatasetRows): SeriesSpec[] {
  if (chart.series && chart.y.length === 1) {
    const y = chart.y[0];
    const groups = new Map<string, number[]>();
    rows.forEach((row, index) => {
      const key = String(row[chart.series!.column] ?? "–");
      const list = groups.get(key);
      if (list) list.push(index);
      else groups.set(key, [index]);
    });
    return [...groups.entries()].map(([name, rowIndexes]) => ({
      name,
      column: y.column,
      format: y.format,
      rowIndexes,
    }));
  }
  const all = rows.map((_, index) => index);
  return chart.y.map((y) => ({
    name: y.label ?? y.column,
    column: y.column,
    format: y.format,
    rowIndexes: all,
  }));
}

function buildCartesianOption(
  chart: CartesianChart,
  rows: DatasetRows,
  theme?: DashboardTheme | ThemeTokens,
): EChartsOption {
  const tokens = resolveTokens(theme);
  const model = buildXAxisModel(chart.x, rows);
  const horizontal = chart.type === "bar" && chart.horizontal === true;
  const specs = seriesSpecs(chart, rows);
  const stacked = chart.series ? chart.series.stack === true : chart.stack === true;
  const multiple = specs.length > 1;
  const yFormat = chart.y[0]?.format;

  const categoryAxis = xAxisOption(chart.x, model, tokens, {
    horizontal,
    truncateLabels: horizontal,
  });
  const valueAxis = valueAxisOption(tokens, yFormat);
  const formatByColumn = new Map(chart.y.map((y) => [y.column, y.format]));

  const series = specs.map((spec, index) => {
    const data = seriesData(spec, rows, model, horizontal);
    const isBar = chart.type === "bar";
    return {
      id: `${chart.id}:${index}`,
      name: spec.name,
      type: isBar ? ("bar" as const) : ("line" as const),
      color: tokens.palette[index % tokens.palette.length],
      ...(stacked ? { stack: "total" } : {}),
      ...(isBar
        ? {
            barMaxWidth: horizontal ? 24 : 42,
            barGap: "12%",
            itemStyle: {
              borderRadius: stacked ? 0 : horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0],
            },
          }
        : {
            showSymbol: data.length <= 1,
            symbolSize: 8,
            lineStyle: { width: 2 },
            emphasis: { focus: "series" as const },
            connectNulls: false,
          }),
      ...(chart.type === "area" ? { areaStyle: { opacity: 0.16 } } : {}),
      data: data.map((point) => ({
        value: point.value,
        rowIndex: point.rowIndex,
        column: spec.column,
      })),
    };
  });

  const option: EChartsOption = {
    ...baseOption(tokens),
    grid: gridOption(multiple, Boolean(chart.x.label)),
    legend: legendOption(tokens, multiple, specs.length),
    tooltip: {
      ...tooltipBase(tokens, "axis"),
      axisPointer: { type: chart.type === "bar" ? "shadow" : "line" },
      formatter: (raw: unknown) => {
        const params = paramsArray(raw);
        const first = params[0];
        const firstData = first?.data as { rowIndex?: number } | undefined;
        const rowIndex = firstData?.rowIndex ?? -1;
        const heading =
          rowIndex >= 0 ? formatXValue(model, rowIndex, rows[rowIndex]?.[chart.x.column]) : "";
        const lines = params.map((param) => {
          const data = param.data as { value?: unknown; column?: string } | undefined;
          const value = Array.isArray(data?.value)
            ? data?.value[horizontal ? 0 : 1]
            : data?.value;
          const format = data?.column ? formatByColumn.get(data.column) : yFormat;
          return `${param.seriesName ?? ""}: ${formatValue(value, format)}`;
        });
        return [heading, ...lines].filter(Boolean).join("<br/>");
      },
    },
    xAxis: horizontal ? valueAxis : categoryAxis,
    yAxis: horizontal ? { ...categoryAxis, inverse: true } : valueAxis,
    series: series as EChartsOption["series"],
  };
  return option;
}

function buildPieOption(
  chart: PieChart,
  rows: DatasetRows,
  theme?: DashboardTheme | ThemeTokens,
): EChartsOption {
  const tokens = resolveTokens(theme);
  const data = rows.map((row, rowIndex) => ({
    name: String(row[chart.label] ?? "–"),
    value: toNumber(row[chart.value.column]) ?? 0,
    rowIndex,
  }));
  const format = chart.value.format;
  const showLabels = data.length <= 8;
  const showLegend = data.length > 1 && data.length <= 12;
  return {
    ...baseOption(tokens),
    legend: legendOption(tokens, showLegend, data.length),
    tooltip: {
      ...tooltipBase(tokens, "item"),
      formatter: (raw: unknown) => {
        const param = paramsArray(raw)[0] as TooltipParam & { name?: string; percent?: number };
        const value = (param?.data as { value?: unknown } | undefined)?.value;
        const percent = typeof param?.percent === "number" ? ` (${param.percent.toFixed(1)}%)` : "";
        return `${param?.name ?? ""}: ${formatValue(value, format)}${percent}`;
      },
    },
    series: [
      {
        id: chart.id,
        name: chart.value.label ?? chart.value.column,
        type: "pie",
        radius: chart.donut ? ["42%", "68%"] : "68%",
        center: ["50%", showLegend ? "42%" : "50%"],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: tokens.surface, borderWidth: 2 },
        label: {
          show: showLabels,
          color: tokens.textSecondary,
          fontFamily: tokens.fontFamily,
          formatter: "{b}",
        },
        labelLine: { lineStyle: { color: tokens.axisLine } },
        data,
      },
    ],
  };
}

function buildScatterOption(
  chart: ScatterChart,
  rows: DatasetRows,
  theme?: DashboardTheme | ThemeTokens,
): EChartsOption {
  const tokens = resolveTokens(theme);
  const model = buildXAxisModel(chart.x, rows);
  const sizeColumn = chart.size;
  const colorColumn = chart.color;
  let maxSize = 0;
  if (sizeColumn) {
    for (const row of rows) maxSize = Math.max(maxSize, toNumber(row[sizeColumn]) ?? 0);
  }
  const groups = new Map<string, number[]>();
  rows.forEach((row, index) => {
    const key = colorColumn ? String(row[colorColumn] ?? "–") : chart.y.label ?? chart.y.column;
    const list = groups.get(key);
    if (list) list.push(index);
    else groups.set(key, [index]);
  });
  const symbolSize = (raw: unknown) => {
    const data = raw as unknown[];
    const size = toNumber(data?.[2]);
    if (!sizeColumn || size === undefined || maxSize <= 0) return 8;
    return 6 + 24 * Math.sqrt(Math.max(0, size) / maxSize);
  };
  const series = [...groups.entries()].map(([name, rowIndexes], index) => ({
    id: `${chart.id}:${index}`,
    name,
    type: "scatter" as const,
    color: tokens.palette[index % tokens.palette.length],
    symbolSize,
    itemStyle: { opacity: 0.85, borderColor: tokens.surface, borderWidth: 1 },
    data: rowIndexes.flatMap((rowIndex) => {
      const row = rows[rowIndex];
      const x = model.kind === "category" ? model.categoryIndex[rowIndex] : model.numeric[rowIndex];
      const y = toNumber(row[chart.y.column]);
      if (x === undefined || y === undefined) return [];
      const size = sizeColumn ? (toNumber(row[sizeColumn]) ?? null) : null;
      return [{ value: [x, y, size], rowIndex }];
    }),
  }));
  const multiple = series.length > 1;
  return {
    ...baseOption(tokens),
    grid: gridOption(multiple, Boolean(chart.x.label)),
    legend: legendOption(tokens, multiple, series.length),
    tooltip: {
      ...tooltipBase(tokens, "item"),
      formatter: (raw: unknown) => {
        const param = paramsArray(raw)[0];
        const data = param?.data as { value?: unknown[]; rowIndex?: number } | undefined;
        const rowIndex = data?.rowIndex ?? -1;
        const row = rows[rowIndex];
        if (!row) return "";
        const lines = [
          `${chart.x.label ?? chart.x.column}: ${formatXValue(model, rowIndex, row[chart.x.column])}`,
          `${chart.y.label ?? chart.y.column}: ${formatValue(row[chart.y.column], chart.y.format)}`,
        ];
        if (sizeColumn) lines.push(`${sizeColumn}: ${formatValue(row[sizeColumn])}`);
        if (colorColumn) lines.unshift(String(row[colorColumn] ?? "–"));
        return lines.join("<br/>");
      },
    },
    xAxis: xAxisOption(chart.x, model, tokens),
    yAxis: valueAxisOption(tokens, chart.y.format),
    series: series as EChartsOption["series"],
  };
}

export function isOptionChart(chart: DashboardChart): chart is ChartOptionChart {
  return chart.type !== "kpi" && chart.type !== "table";
}

/** Build the ECharts option for any chart type that renders through ECharts. */
export function buildChartOption(
  chart: ChartOptionChart,
  rows: DatasetRows,
  theme?: DashboardTheme | ThemeTokens,
): EChartsOption {
  switch (chart.type) {
    case "combo":
      return buildComboOption(chart, rows, theme);
    case "heatmap":
      return buildHeatmapOption(chart, rows, theme);
    case "pie":
      return buildPieOption(chart, rows, theme);
    case "scatter":
      return buildScatterOption(chart, rows, theme);
    default:
      return buildCartesianOption(chart, rows, theme);
  }
}
