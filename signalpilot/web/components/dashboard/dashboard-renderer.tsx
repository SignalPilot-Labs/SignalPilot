"use client";

import type { ComponentType } from "react";

import { LightdashCartesianChart } from "~/dashboard/lightdash/LightdashCartesianChart";
import type {
  ChartDefinition,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";
import { toLightdashCartesianInput } from "~/lib/dashboard/to-lightdash-results";

export type DashboardRendererKey = "kpi" | "table" | "bar" | "line" | "area";

type RendererProps = {
  chart: ChartDefinition;
  result: DashboardQueryResult;
  onMarkClick?: (mark: Record<string, unknown>) => void;
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
  }
  return String(value);
}

function KpiRenderer({ chart, result }: RendererProps) {
  if (chart.visualization.type !== "big_number") return null;
  const value = result.rows[0]?.[chart.visualization.config.field];
  return <div data-dashboard-renderer="kpi">{formatValue(value)}</div>;
}

function TableRenderer({ chart, result }: RendererProps) {
  if (chart.visualization.type !== "table") return null;
  const columns = chart.visualization.config.columns;
  return (
    <table data-dashboard-renderer="table">
      <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
      <tbody>
        {result.rows.map((row, index) => (
          <tr key={index}>{columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}

function CartesianRenderer({ chart, result, onMarkClick }: RendererProps) {
  if (chart.visualization.type !== "cartesian") return null;
  return (
    <div data-dashboard-renderer={chart.visualization.config.seriesType} style={{ height: "100%" }}>
      <LightdashCartesianChart
        input={toLightdashCartesianInput(result, chart)}
        onMarkClick={onMarkClick ?? (() => undefined)}
      />
    </div>
  );
}

export const dashboardRendererRegistry: Record<
  DashboardRendererKey,
  ComponentType<RendererProps>
> = {
  kpi: KpiRenderer,
  table: TableRenderer,
  bar: CartesianRenderer,
  line: CartesianRenderer,
  area: CartesianRenderer,
};

export function getDashboardRendererKey(
  chart: ChartDefinition,
): DashboardRendererKey {
  if (chart.visualization.type === "big_number") return "kpi";
  if (chart.visualization.type === "table") return "table";
  return chart.visualization.config.seriesType;
}

export function DashboardRenderer(props: RendererProps) {
  const Renderer = dashboardRendererRegistry[getDashboardRendererKey(props.chart)];
  return <Renderer {...props} />;
}
