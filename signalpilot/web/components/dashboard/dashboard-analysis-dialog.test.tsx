import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardAnalysisDialog } from "~/components/dashboard/dashboard-analysis-dialog";
import type {
  ChartDefinition,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";

const chart: ChartDefinition = {
  id: "gross-profit",
  title: "Gross Profit",
  query: {
    kind: "semantic",
    exploreName: "profitability",
    dimensions: [],
    metrics: ["profitability.gross_profit"],
    filters: {},
    sorts: [],
    limit: 1,
    projectId: "project-1",
    commitSha: "a".repeat(40),
  },
  visualization: {
    type: "big_number",
    config: { field: "profitability.gross_profit", format: "currency:USD" },
  },
  signalPilot: { crossFilter: false, provenanceRef: "test:gross-profit" },
};

const result: DashboardQueryResult = {
  resultId: "result-1",
  executionId: "execution-1",
  columns: [
    {
      name: "profitability.gross_profit",
      logicalType: "number",
      nullable: false,
      format: "currency:USD",
    },
  ],
  rows: [{ "profitability.gross_profit": 77_814_557.66 }],
  completeness: "truncated",
  freshnessAt: "2026-08-25T14:47:00Z",
  timezone: "America/Sao_Paulo",
  locale: "en-US",
};

describe("DashboardAnalysisDialog frozen reference", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    document.body.replaceChildren();
  });

  it("separates the KPI label and puts precise completeness below the visual", async () => {
    await act(async () => {
      root.render(
        <DashboardAnalysisDialog
          dashboardId="dashboard-1"
          versionId="version-1"
          tileUuid="tile-1"
          chart={chart}
          result={result}
          dashboardResultId="dashboard-result-1"
          filters={[]}
          drillPath={[]}
          selectedMark={{}}
          onClose={vi.fn()}
        />,
      );
    });

    const frozen = document.body.querySelector<HTMLElement>(
      "[aria-label='Frozen selected chart']",
    );
    expect(frozen?.children).toHaveLength(2);
    expect(frozen?.querySelector("strong")?.textContent).toBe("$77,814,557.66");
    expect(
      frozen?.querySelector("[data-dashboard-renderer='kpi'] span")
        ?.textContent,
    ).toBe("Gross Profit");
    expect(frozen?.querySelector("footer")?.textContent).toContain(
      "Result may be incomplete",
    );
  });
});
