import { describe, expect, it } from "vitest";

import fixture from "~/dashboard/lightdash-contract/fixtures/five-components.json";
import type { DashboardDefinition } from "~/lib/dashboard/contracts";
import {
  chartConfidence,
  dashboardConfidenceSummary,
} from "~/lib/dashboard/confidence";

const definition = {
  schemaVersion: 1,
  name: fixture.dashboard.name,
  description: fixture.dashboard.description,
  filters: fixture.dashboard.filters,
  tiles: fixture.dashboard.tiles,
  charts: fixture.charts,
  signalPilot: fixture.signalPilot,
} as DashboardDefinition;

describe("dashboard confidence", () => {
  it("classifies semantic charts as high and custom SQL as low", () => {
    expect(chartConfidence(definition.charts[0])).toBe("high");
    expect(
      chartConfidence({
        ...definition.charts[0],
        query: {
          kind: "sql",
          connectionName: "warehouse",
          sqlTemplate: "SELECT 1 AS value",
          parameterDefinitions: [],
          outputBindings: [],
          limit: 1,
        },
      }),
    ).toBe("low");
    expect(dashboardConfidenceSummary(definition)).toEqual({ high: 5, low: 0 });
  });
});
