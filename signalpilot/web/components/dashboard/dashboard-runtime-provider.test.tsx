import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardRuntimeProvider } from "~/components/dashboard/dashboard-runtime-provider";
import type { DashboardDefinition } from "~/lib/dashboard/contracts";

const definition: DashboardDefinition = {
  schemaVersion: 1,
  name: "Revenue health",
  description: "Current governed revenue",
  filters: { dimensions: [], metrics: [] },
  tiles: [
    {
      uuid: "tile-revenue",
      tileSlug: "revenue",
      type: "saved_chart",
      x: 0,
      y: 0,
      h: 5,
      w: 36,
      properties: { title: "Revenue", chartSlug: "revenue" },
      chartId: "chart-revenue",
    },
  ],
  charts: [
    {
      id: "chart-revenue",
      title: "Revenue",
      query: {
        kind: "semantic",
        exploreName: "orders",
        dimensions: [],
        metrics: ["orders.revenue"],
        filters: {},
        sorts: [],
        limit: 1,
        timezone: "America/Sao_Paulo",
        projectId: "project-1",
        commitSha: "b91bd2273f38fdc58702c71f538b6b5d5ae462c5",
      },
      visualization: {
        type: "big_number",
        config: { field: "orders.revenue", format: "currency:USD" },
      },
      signalPilot: { crossFilter: false, provenanceRef: "test:revenue" },
    },
  ],
  signalPilot: {
    dashboardId: "dashboard-1",
    projectId: "project-1",
    connectionName: "mssql-pilot",
    commitSha: "b91bd2273f38fdc58702c71f538b6b5d5ae462c5",
    semanticFingerprint: "semantic-1",
    timezone: "America/Sao_Paulo",
  },
};

const baseReceipt = {
  dashboard_result_id: "dashboard-result-1",
  result_id: "result-1",
  execution_id: "execution-1",
  columns: [
    {
      name: "orders.revenue",
      logical_type: "decimal",
      nullable: false,
      format: "currency:USD",
      currency_code: "USD",
    },
  ],
  rows: [{ "orders.revenue": 1250 }],
  row_count: 1,
  completeness: "complete",
  result_time: "2026-08-25T12:00:00Z",
  freshness_at: "2026-08-25T12:00:00Z",
  sql_hash: "sql-hash",
  parameter_hash: "parameter-hash",
  tables: ["dbo.orders"],
  semantic_definition: {},
  compiled_sql: null,
};

describe("DashboardRuntimeProvider incidents", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    sessionStorage.setItem("sp_api_key", "sp_test");
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it("shows one cached-source incident and clears it after a successful Retry", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ...baseReceipt,
            cache_state: "cached_source_unavailable",
            refresh_failure: {
              code: "data_source_unavailable",
              message: "driver detail must not render",
              retryable: true,
              connection_name: "mssql-pilot",
              scope: "connection",
              correlation_id: "incident-1",
              occurred_at: "2026-08-25T12:05:00Z",
              cache_fallback_available: true,
              retry_after_seconds: 1,
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ...baseReceipt,
            dashboard_result_id: "dashboard-result-2",
            result_id: "result-2",
            execution_id: "execution-2",
            result_time: "2026-08-25T12:06:00Z",
            freshness_at: "2026-08-25T12:06:00Z",
            cache_state: "fresh",
            refresh_failure: null,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    await act(async () => {
      root.render(
        <DashboardRuntimeProvider
          dashboardId="dashboard-1"
          versionId="version-1"
          definition={definition}
        />,
      );
    });
    await vi.waitFor(() =>
      expect(container.textContent).toContain("Database unavailable"),
    );
    expect(container.textContent).toContain("showing cached data from");
    expect(container.textContent).toContain("$1,250.00");
    expect(container.textContent).not.toContain("driver detail");
    expect(container.textContent?.match(/Database unavailable/g)).toHaveLength(
      1,
    );

    const retry = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Retry",
    );
    await act(async () => retry?.click());
    await vi.waitFor(() =>
      expect(container.textContent).not.toContain("Database unavailable"),
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const retryBody = JSON.parse(
      String((fetchMock.mock.calls[1]?.[1] as RequestInit | undefined)?.body),
    ) as { refresh: boolean; retry_token?: string };
    expect(retryBody.refresh).toBe(true);
    expect(retryBody.retry_token).toBeTruthy();
  });
});
