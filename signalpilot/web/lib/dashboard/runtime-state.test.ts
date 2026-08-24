import { describe, expect, it } from "vitest";

import fiveComponents from "~/dashboard/lightdash-contract/fixtures/five-components.json";
import { fromLightdashFixture } from "~/dashboard/lightdash-contract";
import {
  chartForAvailableResult,
  markRemainsSelected,
  parseDashboardRuntimeState,
  runtimeStateSearchParams,
  toggleCrossFilter,
} from "~/lib/dashboard/runtime-state";
import type {
  ChartDefinition,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";

describe("dashboard runtime state", () => {
  it("round-trips Lightdash-shaped filter overrides and drill state", () => {
    const definition = fromLightdashFixture(fiveComponents);
    definition.filters.dimensions = [
      {
        id: "region",
        operator: "equals",
        values: [],
        label: "Region",
        target: { fieldId: "orders.region", tableName: "orders" },
      },
    ];
    const state = {
      filters: [
        { id: "region", operator: "equals" as const, values: ["North"] },
      ],
      drills: { "chart-bar": [{ fieldId: "orders.region", value: "North" }] },
    };
    const search = runtimeStateSearchParams(definition, state).toString();
    expect(parseDashboardRuntimeState(definition, search)).toEqual(state);
  });

  it("replaces, toggles off, and command-multiselects values", () => {
    const rule = {
      id: "region",
      operator: "equals" as const,
      label: "Region",
      target: { fieldId: "orders.region", tableName: "orders" },
    };
    expect(toggleCrossFilter([], rule, "North", false)[0]?.values).toEqual([
      "North",
    ]);
    expect(
      toggleCrossFilter(
        [{ id: "region", operator: "equals", values: ["North"] }],
        rule,
        "North",
        false,
      ),
    ).toEqual([]);
    expect(
      toggleCrossFilter(
        [{ id: "region", operator: "equals", values: ["North"] }],
        rule,
        "South",
        true,
      )[0]?.values,
    ).toEqual(["North", "South"]);

    const selected = { "orders.region": "North" };
    expect(
      markRemainsSelected(
        [{ id: "region", operator: "equals", values: ["North"] }],
        "region",
        selected,
        "orders.region",
      ),
    ).toBe(true);
    expect(markRemainsSelected([], "region", selected, "orders.region")).toBe(
      false,
    );
  });

  it("keeps the visible drill dimension aligned with the available receipt", () => {
    const chart: ChartDefinition = {
      id: "revenue-by-brand",
      title: "Revenue by brand",
      query: {
        kind: "semantic",
        exploreName: "accounts",
        dimensions: ["accounts.brand"],
        metrics: ["accounts.revenue"],
        filters: {},
        sorts: [],
        limit: 100,
        projectId: "project-1",
        commitSha: "b91bd22",
      },
      visualization: {
        type: "cartesian",
        config: {
          seriesType: "bar",
          layout: {
            xField: "accounts.brand",
            yField: ["accounts.revenue"],
          },
        },
      },
      signalPilot: {
        crossFilter: true,
        drillDimensions: ["accounts.customer_name"],
        provenanceRef: "test:drill",
      },
    };
    const result = (dimension: string): DashboardQueryResult => ({
      resultId: `result-${dimension}`,
      executionId: `execution-${dimension}`,
      columns: [
        { name: dimension, logicalType: "string", nullable: false },
        { name: "accounts.revenue", logicalType: "number", nullable: false },
      ],
      rows: [{ [dimension]: "value", "accounts.revenue": 10 }],
      completeness: "complete",
      freshnessAt: "2026-08-24T12:00:00Z",
    });

    const parent = chartForAvailableResult(chart, result("accounts.brand"));
    const child = chartForAvailableResult(
      chart,
      result("accounts.customer_name"),
    );

    expect(parent.visualization.type).toBe("cartesian");
    expect(child.visualization.type).toBe("cartesian");
    if (
      parent.visualization.type === "cartesian" &&
      child.visualization.type === "cartesian"
    ) {
      expect(parent.visualization.config.layout.xField).toBe("accounts.brand");
      expect(child.visualization.config.layout.xField).toBe(
        "accounts.customer_name",
      );
    }
  });
});
