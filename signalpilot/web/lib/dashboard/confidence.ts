import type {
  ChartDefinition,
  DashboardDefinition,
} from "~/lib/dashboard/contracts";

export type DashboardConfidence = "high" | "low";

export function chartConfidence(chart: ChartDefinition): DashboardConfidence {
  return chart.query.kind === "semantic" ? "high" : "low";
}

export function confidenceExplanation(chart: ChartDefinition): string {
  return chart.query.kind === "semantic"
    ? "DBT-backed: this chart uses model fields at the dashboard's pinned dbt commit."
    : "Direct SQL: this chart uses an explicitly confirmed custom query.";
}

export function dashboardConfidenceSummary(definition: DashboardDefinition) {
  const high = definition.charts.filter(
    (chart) => chartConfidence(chart) === "high",
  ).length;
  return { high, low: definition.charts.length - high };
}
