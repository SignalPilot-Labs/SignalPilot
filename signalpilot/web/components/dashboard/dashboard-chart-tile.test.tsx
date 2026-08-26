import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardChartTile } from "~/components/dashboard/dashboard-chart-tile";
import type {
  ChartDefinition,
  DashboardFailure,
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

function failure(overrides: Partial<DashboardFailure> = {}): DashboardFailure {
  return {
    code: "data_source_unavailable",
    message: "The data source is temporarily unavailable.",
    retryable: true,
    connectionName: "mssql-pilot",
    scope: "connection",
    correlationId: "incident-1",
    occurredAt: "2026-08-25T12:00:00Z",
    cacheFallbackAvailable: false,
    cacheState: "no_usable_cache",
    ...overrides,
  };
}

async function press(element: HTMLElement | null) {
  await act(async () => {
    element?.dispatchEvent(
      new MouseEvent("mousedown", { bubbles: true, button: 0 }),
    );
    element?.dispatchEvent(
      new MouseEvent("mouseup", { bubbles: true, button: 0 }),
    );
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await Promise.resolve();
  });
}

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
    const menu = container.querySelector<HTMLButtonElement>(
      "[aria-label='More actions for Accounts']",
    );
    await press(menu);
    const viewData = Array.from(document.body.querySelectorAll("button")).find(
      (button) => button.textContent === "View data",
    );
    await press(viewData ?? null);

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
    const questionTrigger = container.querySelector<HTMLElement>(
      "[aria-label^='About Which accounts']",
    );
    await act(async () => {
      questionTrigger?.dispatchEvent(
        new MouseEvent("mouseenter", { bubbles: false }),
      );
      questionTrigger?.focus();
      await new Promise((resolve) => setTimeout(resolve, 175));
    });
    const questionTooltip =
      document.body.querySelector<HTMLElement>("[role='tooltip']");
    expect(questionTooltip?.textContent).toContain("Table showing");
    expect(container.contains(questionTooltip)).toBe(false);

    const menu = container.querySelector<HTMLButtonElement>(
      "[aria-label='More actions for Accounts']",
    );
    await press(menu);
    const actions = document.body.querySelector<HTMLElement>(
      "[aria-label='Actions for Accounts']",
    );
    expect(actions).not.toBeNull();
    expect(container.contains(actions)).toBe(false);
    expect(document.body.querySelector("[data-testid='underlay']")).toBeNull();
    expect(document.body.textContent).toContain("Complete result");
    expect(document.body.textContent).toContain("View data");
    const verification = container.querySelector<HTMLElement>(
      "[aria-label^='High confidence']",
    );
    expect(verification).not.toBeNull();
  });

  it("renders confidence help above the tile instead of clipping it inside the card", async () => {
    await act(async () => {
      root.render(<DashboardChartTile chart={chart} result={result} />);
    });
    const confidence = container.querySelector<HTMLElement>(
      "[aria-label^='High confidence']",
    );
    await act(async () => confidence?.focus());

    const tooltip = Array.from(
      document.body.querySelectorAll<HTMLElement>("[role='tooltip']"),
    ).find((candidate) => candidate.textContent?.includes("approved semantic"));
    expect(tooltip).not.toBeNull();
    expect(container.contains(tooltip ?? null)).toBe(false);
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

  it("shows a centered broken state for a chart without usable data", async () => {
    await act(async () => {
      root.render(
        <DashboardChartTile
          chart={chart}
          failure={failure()}
          onRetry={vi.fn()}
        />,
      );
    });

    expect(container.textContent).toContain(
      "The data source is temporarily unavailable",
    );
    expect(container.textContent).toContain("Unable to display this chart");
    expect(container.textContent).not.toContain("No cached data is available");
    expect(container.textContent).toContain("Last checked");
    expect(container.textContent).toContain("Retry");
    expect(container.querySelector("[class*='visualBroken']")).not.toBeNull();
    expect(
      container.querySelector("[class*='chartBrokenIcon']"),
    ).not.toBeNull();
  });

  it("does not expose a result-contract mismatch as a usable chart", async () => {
    await act(async () => {
      root.render(
        <DashboardChartTile
          chart={chart}
          failure={failure({
            code: "result_contract_mismatch",
            message:
              "The returned data does not match this chart's expected fields.",
            retryable: false,
            scope: "chart",
          })}
        />,
      );
    });

    expect(container.textContent).toContain(
      "does not match this chart's expected fields",
    );
  });

  it("keeps cached data visible without repeating a connection incident in the tile", async () => {
    await act(async () => {
      root.render(
        <DashboardChartTile
          chart={chart}
          result={{ ...result, cacheState: "cached_source_unavailable" }}
          failure={failure({ cacheFallbackAvailable: true })}
        />,
      );
    });

    expect(container.textContent).toContain("HaulPro");
    expect(container.textContent).not.toContain("Latest refresh failed");
  });

  it("closes View data with Escape", async () => {
    await act(async () => {
      root.render(<DashboardChartTile chart={chart} result={result} />);
    });
    const menu = container.querySelector<HTMLButtonElement>(
      "[aria-label='More actions for Accounts']",
    );
    await press(menu);
    const viewData = Array.from(document.body.querySelectorAll("button")).find(
      (button) => button.textContent === "View data",
    );
    await press(viewData ?? null);
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
