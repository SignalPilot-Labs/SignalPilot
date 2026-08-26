import { describe, expect, it } from "vitest";

import fiveComponents from "./fixtures/five-components.json";
import prototype from "./fixtures/two-chart-prototype.json";
import { fromLightdashFixture, toLightdashFixture } from "./adapter";
import { UnsupportedDashboardFeatureError } from "./errors";
import { hashDashboardDefinition, normalizeDashboardDefinition } from "./normalize";

describe("Lightdash dashboard compatibility", () => {
  it.each([
    ["five components", fiveComponents],
    ["two-chart prototype", prototype],
  ])("round-trips the supported %s fixture", async (_name, fixture) => {
    const definition = fromLightdashFixture(fixture);
    const roundTrip = toLightdashFixture(definition, fixture.dashboard.version);

    expect(roundTrip).toEqual(fixture);
    expect(normalizeDashboardDefinition(definition)).toEqual(definition);
    expect(await hashDashboardDefinition(definition)).toMatch(/^[a-f0-9]{64}$/);
    if (fixture === fiveComponents) {
      expect(await hashDashboardDefinition(definition)).toBe(
        "cb77d795b8bdbc9e868a4c8edaa2a73657ae71afe26af213a023cff717cec11f",
      );
    }
  });

  it.each([
    ["pie", { ...fiveComponents.charts[2], visualization: { type: "pie", config: {} } }],
    ["scatter", { ...fiveComponents.charts[2], visualization: { type: "cartesian", config: { seriesType: "scatter", layout: { xField: "orders.region", yField: ["orders.revenue"] } } } }],
  ])("fails closed for unsupported %s charts", (_name, unsupportedChart) => {
    const fixture = { ...fiveComponents, charts: [unsupportedChart] };
    expect(() => fromLightdashFixture(fixture)).toThrow(UnsupportedDashboardFeatureError);
  });

  it("fails closed with a typed error for unsupported tile variants", () => {
    const fixture = {
      ...fiveComponents,
      dashboard: {
        ...fiveComponents.dashboard,
        tiles: [
          { ...fiveComponents.dashboard.tiles[0], type: "sql_chart" },
        ],
      },
    };
    expect(() => fromLightdashFixture(fixture)).toThrowError(
      expect.objectContaining({
        code: "UNSUPPORTED_DASHBOARD_FEATURE",
        path: "dashboard.tiles[0].type",
      }),
    );
  });

  it("rejects renderer-specific configuration and invalid encodings", () => {
    const definition = fromLightdashFixture(fiveComponents);
    expect(() =>
      normalizeDashboardDefinition({
        ...definition,
        charts: definition.charts.map((chart, index) =>
          index === 2
            ? { ...chart, visualization: { ...chart.visualization, eChartsConfig: {} } }
            : chart,
        ),
      }),
    ).toThrow();

    expect(() =>
      normalizeDashboardDefinition({
        ...definition,
        charts: definition.charts.map((chart, index) =>
          index === 0 && chart.visualization.type === "big_number"
            ? { ...chart, visualization: { ...chart.visualization, config: { field: "orders.missing" } } }
            : chart,
        ),
      }),
    ).toThrow("unknown query field");
  });
});
