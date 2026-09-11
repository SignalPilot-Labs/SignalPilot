/**
 * Combo chart: grouped or stacked bars on the left value axis with lines
 * drawn over them, by default on a right-hand value axis.
 *
 * Print-path module: relative imports only, no React, no DOM.
 */
import type { EChartsOption } from "echarts";

import type { DatasetRows } from "../datasets";
import { formatValue } from "../format";
import type { ComboChart, DashboardFormat, DashboardSeries } from "../schema";
import type { DashboardTheme, ThemeTokens } from "../theme";
import {
  buildXAxisModel,
  formatXValue,
  gridOption,
  legendOption,
  tooltipBase,
  valueAxisOption,
  xAxisOption,
  type XAxisModel,
} from "./axes";
import { baseOption, paramsArray, resolveTokens, seriesData } from "./option-helpers";

function alignedData(series: DashboardSeries, rows: DatasetRows, model: XAxisModel) {
  const all = rows.map((_, index) => index);
  const spec = { name: series.column, column: series.column, rowIndexes: all };
  return seriesData(spec, rows, model, false).map((point) => ({
    value: point.value,
    rowIndex: point.rowIndex,
    column: series.column,
  }));
}

export function buildComboOption(
  chart: ComboChart,
  rows: DatasetRows,
  theme?: DashboardTheme | ThemeTokens,
): EChartsOption {
  const tokens = resolveTokens(theme);
  const model = buildXAxisModel(chart.x, rows);
  const secondary = chart.secondary_axis !== false;
  const stacked = chart.stack === true;
  const formatByColumn = new Map<string, DashboardFormat | undefined>(
    [...chart.bars, ...chart.lines].map((series) => [series.column, series.format]),
  );

  const bars = chart.bars.map((series, index) => ({
    id: `${chart.id}:bar:${index}`,
    name: series.label ?? series.column,
    type: "bar" as const,
    yAxisIndex: 0,
    color: tokens.palette[index % tokens.palette.length],
    ...(stacked ? { stack: "bars" } : {}),
    barMaxWidth: 42,
    barGap: "12%",
    itemStyle: { borderRadius: stacked ? 0 : [4, 4, 0, 0] },
    data: alignedData(series, rows, model),
  }));
  const lines = chart.lines.map((series, index) => {
    const data = alignedData(series, rows, model);
    return {
      id: `${chart.id}:line:${index}`,
      name: series.label ?? series.column,
      type: "line" as const,
      yAxisIndex: secondary ? 1 : 0,
      z: 3,
      color: tokens.palette[(chart.bars.length + index) % tokens.palette.length],
      showSymbol: data.length <= 1,
      symbolSize: 8,
      lineStyle: { width: 2 },
      emphasis: { focus: "series" as const },
      connectNulls: false,
      data,
    };
  });
  const series = [...bars, ...lines];
  const multiple = series.length > 1;

  const leftAxis = valueAxisOption(tokens, chart.bars[0]?.format);
  const rightAxis = { ...valueAxisOption(tokens, chart.lines[0]?.format), splitLine: { show: false } };
  const grid = gridOption(multiple, Boolean(chart.x.label));

  return {
    ...baseOption(tokens),
    grid: secondary ? { ...grid, right: 24 } : grid,
    legend: legendOption(tokens, multiple, series.length),
    tooltip: {
      ...tooltipBase(tokens, "axis"),
      axisPointer: { type: "shadow" },
      formatter: (raw: unknown) => {
        const params = paramsArray(raw);
        const firstData = params[0]?.data as { rowIndex?: number } | undefined;
        const rowIndex = firstData?.rowIndex ?? -1;
        const heading =
          rowIndex >= 0 ? formatXValue(model, rowIndex, rows[rowIndex]?.[chart.x.column]) : "";
        const entries = params.map((param) => {
          const data = param.data as { value?: unknown; column?: string } | undefined;
          const value = Array.isArray(data?.value) ? data?.value[1] : data?.value;
          const format = data?.column ? formatByColumn.get(data.column) : undefined;
          return `${param.seriesName ?? ""}: ${formatValue(value, format)}`;
        });
        return [heading, ...entries].filter(Boolean).join("<br/>");
      },
    },
    xAxis: xAxisOption(chart.x, model, tokens),
    yAxis: secondary ? [leftAxis, rightAxis] : leftAxis,
    series: series as EChartsOption["series"],
  };
}
