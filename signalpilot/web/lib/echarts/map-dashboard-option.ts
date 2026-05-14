import type { DashboardChart, CachedData } from "@/lib/dashboards/types";

function deepMerge(
  a: Record<string, unknown>,
  b: Record<string, unknown>,
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
        bVal as Record<string, unknown>,
      );
    } else {
      result[key] = bVal;
    }
  }
  return result;
}

const MAX_POINTS = 1000;

function toNum(v: unknown): number {
  if (typeof v === "number") return v;
  const n = Number(v);
  return isNaN(n) ? 0 : n;
}

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

function deriveRadar(data: CachedData): Record<string, unknown> {
  const rows = data.rows.slice(0, MAX_POINTS);
  const indicators = rows.map((row) => {
    const values = row.slice(1).map(toNum);
    const max = Math.max(...values, 1);
    return { name: row[0] == null ? "" : String(row[0]), max: max * 1.2 };
  });
  const seriesCols = data.columns.slice(1);
  const seriesData = seriesCols.map((col, idx) => ({
    name: col.name,
    value: rows.map((row) => toNum(row[idx + 1])),
  }));
  return {
    radar: { indicator: indicators },
    series: [{ type: "radar", data: seriesData }],
  };
}

function deriveGauge(data: CachedData): Record<string, unknown> {
  const value = toNum(data.rows[0]?.[0]);
  return {
    series: [
      {
        type: "gauge",
        data: [{ value }],
        detail: { formatter: "{value}" },
      },
    ],
  };
}

function deriveFunnel(data: CachedData): Record<string, unknown> {
  const rows = data.rows.slice(0, MAX_POINTS);
  const funnelData = rows.map((row) => ({
    name: row[0] == null ? "" : String(row[0]),
    value: toNum(row[1]),
  }));
  return {
    series: [
      {
        type: "funnel",
        data: funnelData,
        left: "10%",
        width: "80%",
        label: { show: true, position: "inside" },
      },
    ],
  };
}

function deriveHeatmap(data: CachedData): Record<string, unknown> {
  const rows = data.rows.slice(0, MAX_POINTS);
  const xLabels = [...new Set(rows.map((r) => String(r[0] ?? "")))];
  const yLabels = [...new Set(rows.map((r) => String(r[1] ?? "")))];
  const xMap = new Map(xLabels.map((l, i) => [l, i]));
  const yMap = new Map(yLabels.map((l, i) => [l, i]));

  let min = Infinity;
  let max = -Infinity;
  const heatData = rows.map((row) => {
    const v = toNum(row[2]);
    if (v < min) min = v;
    if (v > max) max = v;
    return [xMap.get(String(row[0] ?? "")) ?? 0, yMap.get(String(row[1] ?? "")) ?? 0, v];
  });

  return {
    xAxis: { type: "category", data: xLabels },
    yAxis: { type: "category", data: yLabels },
    visualMap: {
      min: isFinite(min) ? min : 0,
      max: isFinite(max) ? max : 1,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      textStyle: { color: "var(--color-text-dim)" },
    },
    series: [
      {
        type: "heatmap",
        data: heatData,
        label: { show: false },
      },
    ],
  };
}

function deriveTreemap(data: CachedData): Record<string, unknown> {
  const rows = data.rows.slice(0, MAX_POINTS);
  const treeData = rows.map((row) => ({
    name: row[0] == null ? "" : String(row[0]),
    value: toNum(row[1]),
  }));
  return {
    series: [
      {
        type: "treemap",
        data: treeData,
        label: { show: true, formatter: "{b}" },
        breadcrumb: { show: false },
      },
    ],
  };
}

function deriveSunburst(data: CachedData): Record<string, unknown> {
  const rows = data.rows.slice(0, MAX_POINTS);
  const sunburstData = rows.map((row) => ({
    name: row[0] == null ? "" : String(row[0]),
    value: toNum(row[1]),
  }));
  return {
    series: [
      {
        type: "sunburst",
        data: sunburstData,
        radius: ["15%", "80%"],
        label: { show: true, rotate: "radial" },
      },
    ],
  };
}

function deriveSankey(data: CachedData): Record<string, unknown> {
  const rows = data.rows.slice(0, MAX_POINTS);
  const nodeSet = new Set<string>();
  const links = rows.map((row) => {
    const source = row[0] == null ? "" : String(row[0]);
    const target = row[1] == null ? "" : String(row[1]);
    nodeSet.add(source);
    nodeSet.add(target);
    return { source, target, value: toNum(row[2]) };
  });
  const nodes = [...nodeSet].map((name) => ({ name }));
  return {
    series: [
      {
        type: "sankey",
        data: nodes,
        links,
        emphasis: { focus: "adjacency" },
        lineStyle: { color: "gradient", curveness: 0.5 },
      },
    ],
  };
}

function deriveBoxplot(data: CachedData): Record<string, unknown> {
  const rows = data.rows.slice(0, MAX_POINTS);
  const groups = new Map<string, number[]>();
  for (const row of rows) {
    const key = row[0] == null ? "" : String(row[0]);
    const val = toNum(row[1]);
    let arr = groups.get(key);
    if (!arr) {
      arr = [];
      groups.set(key, arr);
    }
    arr.push(val);
  }

  const categories: string[] = [];
  const boxData: number[][] = [];
  for (const [key, values] of groups) {
    values.sort((a, b) => a - b);
    const n = values.length;
    const q1 = values[Math.floor(n * 0.25)] ?? 0;
    const median = values[Math.floor(n * 0.5)] ?? 0;
    const q3 = values[Math.floor(n * 0.75)] ?? 0;
    categories.push(key);
    boxData.push([values[0] ?? 0, q1, median, q3, values[n - 1] ?? 0]);
  }

  return {
    xAxis: { type: "category", data: categories },
    yAxis: { type: "value" },
    series: [{ type: "boxplot", data: boxData }],
  };
}

function deriveCandlestick(data: CachedData): Record<string, unknown> {
  const rows = data.rows.slice(0, MAX_POINTS);
  const xData = rows.map((row) => (row[0] == null ? "" : String(row[0])));
  const ohlcData = rows.map((row) => [
    toNum(row[1]),
    toNum(row[2]),
    toNum(row[3]),
    toNum(row[4]),
  ]);
  return {
    xAxis: { type: "category", data: xData },
    yAxis: { type: "value", scale: true },
    series: [{ type: "candlestick", data: ohlcData }],
  };
}

function deriveGraph(data: CachedData): Record<string, unknown> {
  const rows = data.rows.slice(0, MAX_POINTS);
  const nodeSet = new Set<string>();
  const links = rows.map((row) => {
    const source = row[0] == null ? "" : String(row[0]);
    const target = row[1] == null ? "" : String(row[1]);
    nodeSet.add(source);
    nodeSet.add(target);
    return { source, target, value: row[2] != null ? toNum(row[2]) : undefined };
  });
  const nodes = [...nodeSet].map((name) => ({
    name,
    symbolSize: 20,
  }));
  return {
    series: [
      {
        type: "graph",
        layout: "force",
        data: nodes,
        links,
        roam: true,
        label: { show: true, position: "right" },
        force: { repulsion: 100, edgeLength: [50, 200] },
        lineStyle: { curveness: 0.3 },
      },
    ],
  };
}

const ITEM_TOOLTIP_TYPES = new Set([
  "pie", "funnel", "treemap", "sunburst", "sankey", "graph", "gauge",
]);

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
    case "radar":
      derived = deriveRadar(data);
      break;
    case "gauge":
      derived = deriveGauge(data);
      break;
    case "funnel":
      derived = deriveFunnel(data);
      break;
    case "heatmap":
      derived = deriveHeatmap(data);
      break;
    case "treemap":
      derived = deriveTreemap(data);
      break;
    case "sunburst":
      derived = deriveSunburst(data);
      break;
    case "sankey":
      derived = deriveSankey(data);
      break;
    case "boxplot":
      derived = deriveBoxplot(data);
      break;
    case "candlestick":
      derived = deriveCandlestick(data);
      break;
    case "graph":
      derived = deriveGraph(data);
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

  const tooltipTrigger = ITEM_TOOLTIP_TYPES.has(chart.chartType) ? "item" : "axis";
  const forced: Record<string, unknown> = {
    animation: false,
    tooltip: deepMerge(
      typeof merged.tooltip === "object" && merged.tooltip !== null
        ? (merged.tooltip as Record<string, unknown>)
        : {},
      { trigger: tooltipTrigger },
    ),
  };

  return deepMerge(merged, forced);
}
