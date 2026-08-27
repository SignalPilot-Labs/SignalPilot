import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardDetailsDrawer } from "~/components/dashboard/dashboard-inspector";
import type { DashboardQueryReceipt } from "~/lib/dashboard/api-data-source";
import type {
  ChartDefinition,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";

const chart: ChartDefinition = {
  id: "revenue",
  title: "Revenue",
  description: "Recognized revenue after approved adjustments.",
  query: {
    kind: "semantic",
    exploreName: "orders",
    dimensions: [],
    metrics: ["orders.revenue"],
    filters: {},
    sorts: [],
    limit: 1,
    projectId: "project-1",
    commitSha: "b91bd22",
  },
  visualization: { type: "big_number", config: { field: "orders.revenue" } },
  signalPilot: { crossFilter: false, provenanceRef: "test:revenue" },
};

const result: DashboardQueryResult = {
  resultId: "result-1",
  executionId: "execution-1",
  columns: [{ name: "orders.revenue", logicalType: "number", nullable: false }],
  rows: [{ "orders.revenue": 100 }],
  completeness: "complete",
  freshnessAt: "2026-08-24T12:00:00Z",
  timezone: "UTC",
  locale: "en-US",
};

const receipt: DashboardQueryReceipt = {
  dashboard_result_id: "result-uuid",
  result_id: "structured-uuid",
  execution_id: "execution-uuid",
  columns: [],
  rows: [],
  completeness: "complete",
  result_time: "2026-08-24T12:00:00Z",
  freshness_at: "2026-08-24T12:00:00Z",
  sql_hash: "sql-hash",
  parameter_hash: "parameter-hash",
  tables: ["dbo.orders"],
  semantic_definition: { metric: "orders.revenue" },
  compiled_sql: "SELECT SUM(revenue) FROM dbo.orders",
  cache_state: "fresh",
};

describe("DashboardDetailsDrawer", () => {
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

  it("leads with business evidence and keeps identifiers and SQL collapsed", async () => {
    await act(async () => {
      root.render(
        <DashboardDetailsDrawer
          chart={chart}
          result={result}
          receipt={receipt}
          filters={[]}
          onClose={vi.fn()}
        />,
      );
    });
    expect(container.textContent).toContain("Business definition");
    expect(container.textContent).toContain(
      "High — governed semantic definition",
    );
    const technical = Array.from(container.querySelectorAll("details")).find(
      (details) =>
        details.querySelector("summary")?.textContent === "Technical details",
    );
    expect(technical?.open).toBe(false);
  });
});
