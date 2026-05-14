import type { DashboardChart, CachedData } from "@/lib/dashboards/types";

function deepMerge(
  a: Record<string, unknown>,
  b: Record<string, unknown>
): Record<string, unknown> {
  const result: Record<string, unknown> = { ...a };
  for (const key of Object.keys(b)) {
    const aVal = result[key];
    const bVal = b[key];
    if (
      bVal !== null &&
      typeof bVal === "object" &&
      !Array.isArray(bVal) &&
      aVal !== null &&
      typeof aVal === "object" &&
      !Array.isArray(aVal)
    ) {
      result[key] = deepMerge(
        aVal as Record<string, unknown>,
        bVal as Record<string, unknown>
      );
    } else {
      result[key] = bVal;
    }
  }
  return result;
}

const MAX_POINTS = 1000;

function deriveBarLine(
  chart: DashboardChart,
  data: CachedData,
): Record<string, unknown> {
  const rows = data.rows.slice(0, MAX_POINTS);
  const xData = rows.map((row) => (row[0] == null ? "" : String(row[0])));
  const seriesColumns = data.columns.slice(1);
  const seriesType = chart.chartType === "bar" || chart.chartType === "histogram" ? "bar" : "line";

  const series = seriesColumns.map((col, idx) => {
    const base: Record<string, unknown> = {
      name: col.name,
      type: seriesType,
      data: rows.map((row) => row[idx + 1] ?? null),
    };
    if (chart.chartType === "area") {
      base.areaStyle = {};
    }
    return base;
  });

  return {
    xAxis: { type: "category", data: xData },
    yAxis: { type: "value" },
    series,
  };
}

function deriveScatter(data: CachedData): Record<string, unknown> {
  const rows = data.rows.slice(0, MAX_POINTS);
  const scatterData = rows.map((row) => [row[0] ?? null, row[1] ?? null]);
  return {
    xAxis: { type: "value" },
    yAxis: { type: "value" },
    series: [
      {
        type: "scatter",
        data: scatterData,
        name: data.columns[1]?.name ?? "y",
      },
    ],
  };
}

function derivePie(data: CachedData): Record<string, unknown> {
  const rows = data.rows.slice(0, MAX_POINTS);
  const pieData = rows.map((row) => ({
    name: row[0] == null ? "" : String(row[0]),
    value: row[1] ?? 0,
  }));
  return {
    series: [
      {
        type: "pie",
        data: pieData,
        radius: "60%",
      },
    ],
  };
}

export function mapDashboardChartOption(
  chart: DashboardChart,
  data: CachedData,
): Record<string, unknown> {
  let derived: Record<string, unknown>;

  switch (chart.chartType) {
    case "scatter":
      derived = deriveScatter(data);
      break;
    case "pie":
      derived = derivePie(data);
      break;
    case "bar":
    case "line":
    case "area":
    case "histogram":
      derived = deriveBarLine(chart, data);
      break;
    default:
      derived = deriveBarLine(chart, data);
  }

  const overlay = chart.echartsOption ?? {};
  const merged = deepMerge(derived, overlay);

  const forced: Record<string, unknown> = {
    animation: false,
    tooltip: deepMerge(
      typeof merged.tooltip === "object" && merged.tooltip !== null
        ? (merged.tooltip as Record<string, unknown>)
        : {},
      { trigger: chart.chartType === "pie" ? "item" : "axis" }
    ),
  };

  return deepMerge(merged, forced);
}
