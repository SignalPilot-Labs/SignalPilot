import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardChartTile } from "~/components/dashboard/dashboard-chart-tile";
import type {
  ChartDefinition,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";

const chart: ChartDefinition = {
  id: "accounts",
  title: "Accounts",
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
    type: "table",
    config: {
      columns: ["accounts.brand", "accounts.revenue"],
      groups: ["accounts.brand"],
    },
  },
  signalPilot: { crossFilter: true, provenanceRef: "test:accounts" },
};

const result: DashboardQueryResult = {
  resultId: "result-1",
  executionId: "execution-1",
  columns: [
    { name: "accounts.brand", logicalType: "string", nullable: false },
    { name: "accounts.revenue", logicalType: "number", nullable: false },
  ],
  rows: [{ "accounts.brand": "HaulPro", "accounts.revenue": 100 }],
  completeness: "complete",
  freshnessAt: "2026-08-24T12:00:00Z",
};

describe("DashboardChartTile interactions", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("opens View data inside an opaque dialog panel and closes from the backdrop", async () => {
    await act(async () => {
      root.render(<DashboardChartTile chart={chart} result={result} />);
    });
    const viewData = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "View data",
    );
    await act(async () => viewData?.click());

    const dialog = document.body.querySelector<HTMLElement>("[role='dialog']");
    expect(dialog).not.toBeNull();
    expect(dialog?.querySelector("section")).not.toBeNull();

    await act(async () => dialog?.click());
    expect(document.body.querySelector("[role='dialog']")).toBeNull();
  });

  it("explains the required mark selection and drills once a value is selected", async () => {
    const onDrill = vi.fn();
    await act(async () => {
      root.render(
        <DashboardChartTile
          chart={chart}
          result={result}
          onDrill={onDrill}
          canDrill={false}
        />,
      );
    });
    const disabled = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Drill down",
    );
    expect(disabled?.disabled).toBe(true);
    expect(container.textContent).toContain("Select a chart mark to drill");

    await act(async () => {
      root.render(
        <DashboardChartTile
          chart={chart}
          result={result}
          onDrill={onDrill}
          canDrill
          drillSelection="HaulPro"
        />,
      );
    });
    const enabled = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Drill down",
    );
    await act(async () => enabled?.click());
    expect(onDrill).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("Selected: HaulPro");
  });
});
