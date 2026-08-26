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
    ? "High confidence: this chart uses approved semantic fields at the dashboard's pinned dbt commit."
    : "Low confidence: this chart uses explicitly confirmed custom SQL rather than an approved semantic metric.";
}

export function dashboardConfidenceSummary(definition: DashboardDefinition) {
  const high = definition.charts.filter(
    (chart) => chartConfidence(chart) === "high",
  ).length;
  return { high, low: definition.charts.length - high };
}
