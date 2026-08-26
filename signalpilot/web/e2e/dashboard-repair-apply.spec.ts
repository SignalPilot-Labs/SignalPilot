import { expect, test } from "@playwright/test";

import fixture from "../dashboard/lightdash-contract/fixtures/five-components.json";
import { fromLightdashFixture } from "../dashboard/lightdash-contract";
import type { DashboardDefinition } from "../lib/dashboard/contracts";

const dashboardId = "dashboard-phase-7";
const baseVersionId = "version-phase-7";
const repairedVersionId = "version-phase-7-repaired";

const fixtureDefinition = fromLightdashFixture(fixture);
const baseDefinition: DashboardDefinition = {
  ...fixtureDefinition,
  signalPilot: {
    ...fixtureDefinition.signalPilot,
    dashboardId,
  },
};

const repairedDefinition: DashboardDefinition = {
  ...baseDefinition,
  filters: {
    ...baseDefinition.filters,
    dimensions: [
      {
        id: "activity-date",
        operator: "inThePast",
        values: [90],
        target: {
          tableName: "orders",
          fieldId: "orders.month",
        },
        tileTargets: {
          "tile-kpi": false,
          "tile-table": false,
          "tile-bar": false,
          "tile-line": {
            tableName: "orders",
            fieldId: "orders.month",
          },
          "tile-area": {
            tableName: "orders",
            fieldId: "orders.month",
          },
        },
        label: "Activity date",
        settings: { unitOfTime: "days" },
      },
    ],
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
        [dimension]: dimension.endsWith("region") ? "Northeast" : "2026-07",
        "orders.revenue": 520_000,
      },
      {
        [dimension]: dimension.endsWith("region") ? "Southeast" : "2026-08",
        "orders.revenue": 410_000,
      },
    ],
  };
}

function receipt(chartId: string) {
  const result = resultFor(chartId);
  return {
    dashboard_result_id: `dashboard-result-${chartId}`,
    result_id: `result-${chartId}`,
    execution_id: `execution-${chartId}`,
    ...result,
    row_count: result.rows.length,
    completeness: "complete",
    result_time: "2026-08-26T12:00:00Z",
    freshness_at: "2026-08-26T12:00:00Z",
    sql_hash: "sql-hash",
    parameter_hash: "parameter-hash",
    tables: ["dbo.orders"],
    semantic_definition: {},
    compiled_sql: null,
    cache_state: "fresh",
    refresh_failure: null,
  };
}

function detail(versionId: string, definition = baseDefinition) {
  return {
    dashboard: {
      id: dashboardId,
      current_version_id: versionId,
      visibility: "private",
      is_owner: true,
      parent_dashboard_id: null,
      parent_version_id: null,
    },
    version: { id: versionId, definition },
  };
}

test("repairs truncated time series in preview and applies exactly one version", async ({
  page,
}) => {
  let applyCount = 0;
  const applyResultIds = new Set<string>();

  await page.addInitScript(() =>
    sessionStorage.setItem("sp_api_key", "sp_test"),
  );
  await page.route("**/api/dashboard-authoring/sessions**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const query = /\/sessions\/session-phase-7\/charts\/([^/]+)\/query$/.exec(
      url.pathname,
    );
    if (query) {
      return route.fulfill({ status: 200, json: receipt(query[1]) });
    }
    if (url.pathname.endsWith("/session-phase-7/apply")) {
      applyCount += 1;
      const body = request.postDataJSON() as {
        expected_current_version_id: string;
        visible_complete_result_ids: string[];
      };
      expect(body.expected_current_version_id).toBe(baseVersionId);
      body.visible_complete_result_ids.forEach((id) => applyResultIds.add(id));
      return route.fulfill({
        status: 200,
        json: detail(repairedVersionId, repairedDefinition),
      });
    }
    if (url.pathname === "/api/dashboard-authoring/sessions") {
      const body = request.postDataJSON() as { prompt: string };
      expect(body.prompt).toContain("Revenue trend");
      expect(body.prompt).toContain("Revenue area");
      return route.fulfill({
        status: 201,
        json: {
          id: "session-phase-7",
          thread_id: "thread-phase-7",
          dashboard_id: dashboardId,
          base_version_id: baseVersionId,
          definition: repairedDefinition,
          operations: [],
          summary: "Narrowed the initial activity window to 90 days.",
          status: "preview",
          requires_custom_sql_confirmation: false,
          custom_sql_confirmed: false,
          custom_sql_chart_ids: [],
          draft_revision: 1,
          events: [],
        },
      });
    }
    return route.fulfill({ status: 404, json: { detail: "Not found" } });
  });
  await page.route(`**/api/dashboards/${dashboardId}**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/suggestions")) {
      return route.fulfill({ status: 200, json: [] });
    }
    if (url.pathname.endsWith("/telemetry")) {
      return route.fulfill({ status: 204, body: "" });
    }
    if (url.pathname.endsWith("/active-authoring-session")) {
      return route.fulfill({ status: 200, json: null });
    }
    const query = /\/charts\/([^/]+)\/query$/.exec(url.pathname);
    if (query) {
      if (query[1] === "chart-line" || query[1] === "chart-area") {
        return route.fulfill({
          status: 502,
          json: {
            detail: {
              code: "result_contract_mismatch",
              message: "provider details stay hidden",
              retryable: false,
              scope: "chart",
              correlation_id: `truncated-${query[1]}`,
              occurred_at: "2026-08-26T12:00:00Z",
            },
          },
        });
      }
      return route.fulfill({ status: 200, json: receipt(query[1]) });
    }
    const requestedVersion = url.searchParams.get("version_id");
    return route.fulfill({
      status: 200,
      json:
        requestedVersion === repairedVersionId
          ? detail(repairedVersionId, repairedDefinition)
          : detail(baseVersionId),
    });
  });

  await page.goto(`/dashboards/${dashboardId}`);
  await expect(page.getByText("Unable to display this chart")).toHaveCount(2);
  expect(applyCount).toBe(0);

  await page
    .getByRole("button", { name: "Repair 2 failing charts with AI" })
    .click();
  await expect(page.getByLabel("Repair request")).toHaveValue(
    /Revenue trend/,
  );
  await page.getByRole("button", { name: "Create repair preview" }).click();

  await expect(page.getByText("Draft 1")).toBeVisible();
  const repairPreview = page.getByTestId("dashboard-authoring-overlay");
  for (const renderer of ["kpi", "table", "bar", "line", "area"]) {
    await expect(
      repairPreview.locator(`[data-dashboard-renderer="${renderer}"]`),
    ).toBeVisible();
  }
  await page.getByRole("button", { name: "Apply", exact: true }).click();

  await expect.poll(() => applyCount).toBe(1);
  expect(applyResultIds.size).toBe(5);
  await expect(page).toHaveURL(new RegExp(`version=${repairedVersionId}`));
});
