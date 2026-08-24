import { describe, expect, it } from "vitest";

import fiveComponents from "~/dashboard/lightdash-contract/fixtures/five-components.json";
import { fromLightdashFixture } from "~/dashboard/lightdash-contract";
import {
  dashboardRendererRegistry,
  getDashboardRendererKey,
} from "~/components/dashboard/dashboard-renderer";

describe("dashboard renderer registry", () => {
  it("resolves the five supported engine-neutral component types", () => {
    const definition = fromLightdashFixture(fiveComponents);
    expect(definition.charts.map(getDashboardRendererKey)).toEqual([
      "kpi",
      "table",
      "bar",
      "line",
      "area",
    ]);
    expect(Object.keys(dashboardRendererRegistry)).toEqual([
      "kpi",
      "table",
      "bar",
      "line",
      "area",
    ]);
  });
});
