import { expect, test } from "@playwright/test";

import fixture from "../dashboard/lightdash-contract/fixtures/five-components.json";

const definition = {
  schemaVersion: 1,
  name: fixture.dashboard.name,
  description: fixture.dashboard.description,
  filters: fixture.dashboard.filters,
  tiles: fixture.dashboard.tiles,
  charts: fixture.charts,
  signalPilot: {
    ...fixture.signalPilot,
    dashboardId: "dashboard-phase-6",
    timezone: "America/Sao_Paulo",
  },
};

function resultFor(chartId: string) {
  if (chartId === "chart-kpi") {
    return {
      columns: [
        {
          name: "orders.revenue",
          logical_type: "decimal",
          nullable: false,
          format: "currency:USD",
          currency_code: "USD",
        },
      ],
      rows: [{ "orders.revenue": 1_595_000 }],
    };
  }
  const dimension =
    chartId === "chart-bar" || chartId === "chart-table"
      ? "orders.region"
      : "orders.month";
  return {
    columns: [
      { name: dimension, logical_type: "string", nullable: false },
      {
        name: "orders.revenue",
        logical_type: "decimal",
        nullable: false,
        format: "currency:USD",
        currency_code: "USD",
      },
    ],
    rows: [
      {
        [dimension]: dimension.endsWith("region") ? "Northeast" : "2026-08",
        "orders.revenue": 520_000,
      },
      {
        [dimension]: dimension.endsWith("region") ? "Southeast" : "2026-09",
        "orders.revenue": 410_000,
      },
    ],
  };
}

test("keeps exact cached charts visible through an outage and recovers with one Retry", async ({
  page,
}) => {
  const retryTokens = new Set<string>();
  let queryCount = 0;
  await page.addInitScript(() =>
    sessionStorage.setItem("sp_api_key", "sp_test"),
  );
  await page.route("**/api/dashboards/dashboard-phase-6**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/suggestions")) {
      return route.fulfill({ status: 200, json: [] });
    }
    const query = /\/charts\/([^/]+)\/query$/.exec(url.pathname);
    if (query) {
      queryCount += 1;
      const body = request.postDataJSON() as {
        refresh: boolean;
        retry_token?: string;
      };
      if (body.retry_token) retryTokens.add(body.retry_token);
      const fresh = body.refresh && Boolean(body.retry_token);
      const result = resultFor(query[1]);
      return route.fulfill({
        status: 200,
        json: {
          dashboard_result_id: `dashboard-result-${query[1]}-${fresh ? "fresh" : "cached"}`,
          result_id: `result-${query[1]}`,
          execution_id: `execution-${query[1]}`,
          ...result,
          row_count: result.rows.length,
          completeness: "complete",
          result_time: "2026-08-25T12:00:00Z",
          freshness_at: "2026-08-25T12:00:00Z",
          sql_hash: "sql-hash",
          parameter_hash: "parameter-hash",
          tables: ["dbo.orders"],
          semantic_definition: {},
          compiled_sql: null,
          cache_state: fresh ? "fresh" : "cached_source_unavailable",
          refresh_failure: fresh
            ? null
            : {
                code: "data_source_unavailable",
                message: "raw driver address tcp://warehouse.internal:1433",
                retryable: true,
                connection_name: "mssql-pilot",
                scope: "connection",
                correlation_id: "incident-phase-6",
                occurred_at: "2026-08-25T12:05:00Z",
                cache_fallback_available: true,
                retry_after_seconds: 1,
              },
        },
      });
    }
    return route.fulfill({
      status: 200,
      json: {
        dashboard: {
          id: "dashboard-phase-6",
          current_version_id: "version-phase-6",
          visibility: "private",
          is_owner: false,
          parent_dashboard_id: null,
          parent_version_id: null,
        },
        version: { id: "version-phase-6", definition },
      },
    });
  });

  await page.goto("/dashboards/dashboard-phase-6");
  await expect(page.getByText("Database unavailable")).toHaveCount(1);
  await expect(page.getByText(/showing cached data from/)).toBeVisible();
  await expect(page.getByText("$1,595,000.00")).toBeVisible();
  await expect(page.getByText(/raw driver address/)).toHaveCount(0);

  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect.poll(() => queryCount, { timeout: 15_000 }).toBe(10);
  await expect(page.getByText("Database unavailable")).toHaveCount(0, {
    timeout: 15_000,
  });
  expect(retryTokens.size).toBe(1);
});
