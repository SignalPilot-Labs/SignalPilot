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
  question: "Which accounts generate the most revenue?",
  description: "Table showing account revenue ranked from highest to lowest.",
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
    {
      name: "accounts.revenue",
      logicalType: "number",
      nullable: false,
      label: "Revenue",
      format: "currency:USD",
      currencyCode: "USD",
    },
  ],
  rows: [{ "accounts.brand": "HaulPro", "accounts.revenue": 100 }],
  completeness: "complete",
  freshnessAt: "2026-08-24T12:00:00Z",
  timezone: "America/Sao_Paulo",
  locale: "en-US",
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
    expect(dialog?.textContent).toContain("$100.00");
    expect(document.activeElement?.textContent).toBe("Close");

    await act(async () => dialog?.click());
    expect(document.body.querySelector("[role='dialog']")).toBeNull();
  });

  it("shows the business question and moves receipt metadata into the overflow menu", async () => {
    await act(async () => {
      root.render(<DashboardChartTile chart={chart} result={result} />);
    });
    expect(container.querySelector("h2")?.textContent).toBe(
      "Which accounts generate the most revenue?",
    );
    expect(container.querySelector("[role='tooltip']")?.textContent).toContain(
      "Table showing",
    );
    expect(container.querySelector("summary")?.getAttribute("aria-label")).toBe(
      "More actions for Accounts",
    );
    expect(container.textContent).toContain("Complete result");
    expect(container.textContent).toContain("View data");
    const verification = container.querySelector<HTMLElement>(
      "[aria-label^='High confidence']",
    );
    expect(verification).not.toBeNull();
    expect(
      container.querySelector(
        `#${verification?.getAttribute("aria-describedby")}`,
      )?.textContent,
    ).toContain("approved semantic fields");
  });

  it("centers a spinner in a chart while its governed data is loading", async () => {
    await act(async () => {
      root.render(<DashboardChartTile chart={chart} loading />);
    });

    const loadingState =
      container.querySelector<HTMLElement>("[role='status']");
    expect(loadingState?.textContent).toBe("");
    expect(loadingState?.getAttribute("aria-label")).toBe(
      "Loading governed data",
    );
    expect(loadingState?.querySelector("[aria-hidden='true']")).not.toBeNull();
  });

  it("shows a compact business-facing message for a network failure", async () => {
    await act(async () => {
      root.render(<DashboardChartTile chart={chart} error="Failed to fetch" />);
    });

    expect(container.textContent).toContain(
      "The data source is temporarily unavailable",
    );
    expect(container.textContent).not.toContain("Failed to fetch");
  });

  it("does not expose a truncated time series as a usable chart", async () => {
    await act(async () => {
      root.render(
        <DashboardChartTile
          chart={chart}
          error={'422: {"detail":{"code":"dashboard_time_series_truncated"}}'}
        />,
      );
    });

    expect(container.textContent).toContain(
      "This time series exceeds its safe row limit",
    );
    expect(container.textContent).not.toContain(
      "dashboard_time_series_truncated",
    );
  });

  it("closes View data with Escape", async () => {
    await act(async () => {
      root.render(<DashboardChartTile chart={chart} result={result} />);
    });
    const viewData = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "View data",
    );
    await act(async () => viewData?.click());
    await act(async () =>
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })),
    );
    expect(document.body.querySelector("[role='dialog']")).toBeNull();
  });

  it("offers distinct filter and drill actions only after an explicit selection", async () => {
    const onDrill = vi.fn();
    const onFilter = vi.fn();
    await act(async () => {
      root.render(
        <DashboardChartTile
          chart={chart}
          result={result}
          onDrill={onDrill}
          onFilter={onFilter}
          canDrill={false}
          canFilter={false}
        />,
      );
    });
    const disabled = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Drill into value",
    );
    expect(disabled).toBeUndefined();
    expect(container.textContent).not.toContain(
      "Select a chart mark to filter or drill",
    );

    await act(async () => {
      root.render(
        <DashboardChartTile
          chart={chart}
          result={result}
          onDrill={onDrill}
          onFilter={onFilter}
          canDrill
          canFilter
          selectionLabel="HaulPro"
        />,
      );
    });
    const enabled = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Drill into value",
    );
    await act(async () => enabled?.click());
    expect(onDrill).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("Selected: HaulPro");

    const filter = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Filter dashboard",
    );
    await act(async () => filter?.click());
    expect(onFilter).toHaveBeenCalledOnce();
  });
});
