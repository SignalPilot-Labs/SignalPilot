export const DASHBOARD_CHART_TYPES = [
  "bar",
  "line",
  "area",
  "scatter",
  "pie",
  "histogram",
  "radar",
  "gauge",
  "funnel",
  "heatmap",
  "treemap",
  "sunburst",
  "sankey",
  "boxplot",
  "candlestick",
  "graph",
  "table",
  "kpi",
] as const;
export type DashboardChartType = (typeof DASHBOARD_CHART_TYPES)[number];

export interface ChartPosition {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface CachedData {
  columns: { name: string; type: string }[];
  rows: unknown[][];
  computedAt: string;
}

export interface DashboardChart {
  id: string;
  title: string;
  chartType: DashboardChartType;
  sql: string;
  connectionName: string;
  echartsOption: Record<string, unknown>;
  position: ChartPosition;
  cachedData?: CachedData;
}

export interface DashboardLayout {
  columns: number;
  rowHeight: number;
}

export interface DashboardDefinition {
  schemaVersion: 1;
  id: string;
  name: string;
  description: string;
  layout: DashboardLayout;
  charts: DashboardChart[];
  createdAt: string;
  updatedAt: string;
}
