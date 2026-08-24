import { describe, expect, it } from "vitest";

import type {
  ChartDefinition,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";
import { toLightdashCartesianInput } from "~/lib/dashboard/to-lightdash-results";

const chart: ChartDefinition = {
  id: "revenue-by-region",
  title: "Revenue by region",
  visualization: {
    type: "cartesian",
    config: {
      seriesType: "bar",
      layout: { xField: "region", yField: ["revenue"] },
    },
  },
  query: {
    kind: "semantic",
    exploreName: "orders",
    dimensions: ["region"],
    metrics: ["revenue"],
    filters: {},
    sorts: [],
    limit: 100,
    projectId: "project-1",
    commitSha: "b91bd22",
  },
  signalPilot: { crossFilter: true, provenanceRef: "provenance-1" },
};

const result: DashboardQueryResult = {
  resultId: "result-1",
  executionId: "execution-1",
  columns: [
    { name: "region", logicalType: "string", nullable: false },
    { name: "revenue", logicalType: "number", nullable: false },
  ],
  rows: [{ region: "Northeast", revenue: 520000 }],
  completeness: "complete",
  freshnessAt: "2026-08-21T12:00:00Z",
  timezone: "UTC",
  locale: "en-US",
};

describe("toLightdashCartesianInput", () => {
  it("adapts SignalPilot rows and field roles to Lightdash-shaped input", () => {
    const adapted = toLightdashCartesianInput(result, chart);

    expect(adapted.chartType).toBe("cartesian");
    expect(adapted.fields.region.role).toBe("dimension");
    expect(adapted.fields.revenue.role).toBe("metric");
    expect(adapted.rows).toEqual([
      {
        region: { value: { raw: "Northeast", formatted: "Northeast" } },
        revenue: { value: { raw: 520000, formatted: "520,000" } },
      },
    ]);
  });

  it("fails closed when the result omits a configured field", () => {
    expect(() =>
      toLightdashCartesianInput(
        { ...result, columns: result.columns.slice(0, 1) },
        chart,
      ),
    ).toThrow("missing required field 'revenue'");
  });
});
