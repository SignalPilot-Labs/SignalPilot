import { expect, test, type Page, type Route } from "@playwright/test";

const artifact = {
  id: "artifact-1",
  kind: "table",
  filename: "revenue.csv",
  project_id: "project-1",
  project_name: "Revenue Warehouse",
  original_thread_id: "conversation-1",
  original_thread_title: "Quarterly revenue",
  created_at: "2026-08-10T12:00:00Z",
  freshness_state: "unknown",
  freshness_at: "2026-08-10T11:00:00Z",
  freshness_checked_at: "2026-08-10T12:00:00Z",
  saved_report_id: null,
  saved_version_id: null,
  snapshot: {
    columns: [{ name: "revenue" }],
    rows: [{ revenue: 100 }],
  },
  download_formats: ["csv"],
};

const version = {
  id: "version-1",
  ordinal: 1,
  kind: "table",
  filename: "revenue.csv",
  content_hash: "a".repeat(64),
  freshness_state: "fresh",
  freshness_at: "2026-08-10T11:00:00Z",
  freshness_checked_at: "2026-08-10T12:00:00Z",
  dbt_commit_sha: "b".repeat(40),
  schema_fingerprint: "c".repeat(64),
  published_at: "2026-08-10T12:00:00Z",
  snapshot: artifact.snapshot,
  download_url: "/api/chat/report-versions/version-1/download",
};

function reportDetail(refresh: Record<string, unknown> | null = null) {
  return {
    id: "report-1",
    title: "Saved revenue",
    kind: "table",
    project_id: "project-1",
    project_name: "Revenue Warehouse",
    original_thread_id: "conversation-1",
    original_thread_title: "Quarterly revenue",
    current_version_id: version.id,
    revision: 1,
    created_at: "2026-08-10T12:00:00Z",
    updated_at: "2026-08-10T12:00:00Z",
    current_version: version,
    versions: [version],
    active_share_version_ids: [] as string[],
    refresh,
  };
}

function library() {
  return {
    artifacts: { items: [artifact], next_cursor: null },
    reports: {
      items: [
        {
          id: "report-1",
          report_id: "report-1",
          title: "Saved revenue",
          kind: "table",
          filename: "revenue.csv",
          is_shared: false,
          project_id: "project-1",
          project_name: "Revenue Warehouse",
          original_thread_id: "conversation-1",
          original_thread_title: "Quarterly revenue",
          version_id: "version-1",
          version_ordinal: 1,
          freshness_state: "fresh",
          freshness_at: "2026-08-10T11:00:00Z",
          freshness_checked_at: "2026-08-10T12:00:00Z",
          updated_at: "2026-08-10T12:00:00Z",
          snapshot: artifact.snapshot,
          download_url: "/api/chat/report-versions/version-1/download",
        },
      ],
      next_cursor: null,
    },
    facets: {
      artifact_types: ["table"],
      projects: [{ id: "project-1", name: "Revenue Warehouse" }],
      original_threads: [{ id: "conversation-1", title: "Quarterly revenue" }],
    },
  };
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mockReportsApi(
  page: Page,
  options: {
    detail?: ReturnType<typeof reportDetail>;
    onRequest?: (request: {
      method: string;
      path: string;
      body: unknown;
    }) => void;
  } = {},
) {
  const detail = options.detail ?? reportDetail();
  await page.route("**/api/local-key", (route) =>
    json(route, { key: "sp_chat_reports_e2e" }),
  );
  await page.route(
    /^http:\/\/localhost:\d+\/api\/chat(?:\/.*)?$/,
    async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      const method = request.method();
      const body = request.postDataJSON?.() ?? null;
      options.onRequest?.({ method, path, body });
      if (path === "/api/chat/library") return json(route, library());
      if (path === "/api/chat/bootstrap") {
        return json(route, {
          enabled: true,
          projects: [
            {
              id: "project-1",
              name: "revenue",
              display_name: "Revenue Warehouse",
              connection_name: "production",
              default_branch: "main",
              ready: true,
              readiness_message: "Ready",
            },
          ],
          selected_project_id: "project-1",
          is_admin: true,
          starter_questions: [],
          default_per_query_budget_usd: 0.25,
          default_chat_budget_usd: 1,
          enterprise_features: { organization_sharing: true },
        });
      }
      if (path === "/api/chat/projects/project-1/readiness") {
        return json(route, {
          project_id: "project-1",
          ready: true,
          code: "ready",
          message: "Ready",
          setup_cta: false,
          branch: "main",
          connection_name: "production",
          starter_questions: [],
        });
      }
      if (path === "/api/chat/conversations") {
        return json(route, {
          conversations: [
            {
              id: "conversation-new",
              project_id: "project-1",
              project_name: "Revenue Warehouse",
              branch: "main",
              title: "Q2 revenue follow-up",
              status: "active",
              created_at: 1,
              updated_at: 2,
              run_status: "completed",
              commit_sha: "b".repeat(40),
              per_query_budget_usd: 0.25,
              chat_budget_usd: 1,
              estimated_spend_usd: 0,
              actual_spend_usd: 0,
              reserved_spend_usd: 0,
            },
          ],
        });
      }
      if (path === "/api/chat/reports" && method === "POST") {
        return json(
          route,
          { status: "created", report_id: "report-1", version_id: "version-1" },
          201,
        );
      }
      if (path === "/api/chat/reports/report-1" && method === "GET") {
        return json(route, detail);
      }
      if (path === "/api/chat/reports/report-1/versions" && method === "POST") {
        return json(
          route,
          {
            status: "created",
            report_id: "report-1",
            version_id: "version-2",
            current_version_id: "version-2",
          },
          201,
        );
      }
      if (
        path === "/api/chat/reports/report-1/refreshes" &&
        method === "POST"
      ) {
        return json(
          route,
          {
            refresh_id: "refresh-1",
            report_id: "report-1",
            version_id: "version-1",
            conversation_id: "conversation-refresh",
            run_id: "run-1",
            status: "refreshing",
            drift_state: "unknown",
            explanation: "Refresh requested in a new Data Chat.",
            checked_at: "2026-08-10T12:00:00Z",
          },
          201,
        );
      }
      if (
        path === "/api/chat/report-versions/version-1/share" &&
        method === "POST"
      ) {
        detail.active_share_version_ids = ["version-1"];
        return json(
          route,
          {
            token: "fixed-token",
            version_id: "version-1",
            created_at: "2026-08-10T12:00:00Z",
          },
          201,
        );
      }
      if (
        path === "/api/chat/report-versions/version-1/share" &&
        method === "DELETE"
      ) {
        detail.active_share_version_ids = [];
        return route.fulfill({ status: 204 });
      }
      if (path === "/api/chat/shared-reports/fixed-token") {
        const {
          content_hash,
          dbt_commit_sha,
          schema_fingerprint,
          ...safeVersion
        } = version;
        void content_hash;
        void dbt_commit_sha;
        void schema_fingerprint;
        return json(route, {
          title: "Saved revenue",
          kind: "table",
          version: safeVersion,
          shared_at: "2026-08-10T12:00:00Z",
        });
      }
      return route.abort();
    },
  );
}

test.describe("Data Chat reports", () => {
  test("uses the reports-first split view and promotes from the artifact preview", async ({
    page,
  }) => {
    const requests: Array<{ method: string; path: string; body: unknown }> = [];
    await mockReportsApi(page, {
      onRequest: (request) => requests.push(request),
    });
    await page.goto("/reports", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("tab", { name: /^Reports/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByText("Saved revenue").first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Open report" })).toBeVisible();
    await expect(page.getByLabel("Artifact type")).toBeHidden();
    await page.getByRole("button", { name: "Show filters" }).click();
    await expect(page.getByLabel("Artifact type")).toBeVisible();
    await page
      .getByLabel("Search artifacts and reports")
      .fill("Revenue Warehouse");
    await expect(page.getByText("Saved revenue").first()).toBeVisible();

    await page.getByRole("tab", { name: /^Artifacts/ }).click();
    await expect(
      page.getByRole("button", { name: "Save as report" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Save as report" }).click();
    await page.getByLabel("Report title").fill("Board revenue");
    await page.getByRole("button", { name: "Save report" }).click();
    await expect(page).toHaveURL(/\/reports\/report-1$/);
    expect(
      requests.find(
        (request) =>
          request.method === "POST" && request.path === "/api/chat/reports",
      )?.body,
    ).toEqual({ artifact_id: "artifact-1", title: "Board revenue" });
  });

  test("publishes a refresh candidate and manages a fixed-version share", async ({
    context,
    page,
  }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const detail = reportDetail({
      id: "refresh-1",
      base_version_id: "version-1",
      status: "update_available",
      drift_state: "none",
      explanation: "No dbt or warehouse schema changes were detected.",
      checked_at: "2026-08-10T12:00:00Z",
      run_id: "run-1",
      conversation_id: "conversation-refresh",
      candidate_artifact_ids: ["artifact-refresh"],
    });
    const requests: Array<{ method: string; path: string; body: unknown }> = [];
    await mockReportsApi(page, {
      detail,
      onRequest: (request) => requests.push(request),
    });
    await page.goto("/reports/report-1", { waitUntil: "domcontentloaded" });

    await expect(
      page.getByText("Update available", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Update report" }).click();
    await expect
      .poll(() =>
        requests.some(
          (request) =>
            request.method === "POST" &&
            request.path === "/api/chat/reports/report-1/versions",
        ),
      )
      .toBe(true);

    await page.getByRole("button", { name: "Share version 1" }).click();
    await expect(page.getByText(/reports\/shared\/fixed-token/)).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Revoke version 1 link" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Revoke", exact: true }).click();
    await expect(page.getByText(/reports\/shared\/fixed-token/)).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: "Use in Data Chat" }),
    ).toHaveAttribute(
      "href",
      "/chats?project=project-1&report=report-1&version=version-1",
    );
  });

  test("starts report refresh in a new Data Chat", async ({ page }) => {
    const requests: Array<{ method: string; path: string; body: unknown }> = [];
    await mockReportsApi(page, {
      onRequest: (request) => requests.push(request),
    });
    await page.goto("/reports/report-1", { waitUntil: "domcontentloaded" });

    await page
      .getByRole("button", { name: "Refresh data", exact: true })
      .click();
    await expect(page).toHaveURL(/\/chats\/conversation-refresh$/);
    expect(
      requests.filter(
        (request) =>
          request.method === "POST" &&
          request.path === "/api/chat/reports/report-1/refreshes",
      ),
    ).toHaveLength(1);
    expect(requests.some((request) => request.path.includes("/confirm"))).toBe(
      false,
    );
  });

  test("shared recipients see only the pinned view and download action", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockReportsApi(page);
    await page.goto("/reports/shared/fixed-token", {
      waitUntil: "domcontentloaded",
    });

    await expect(
      page.getByRole("heading", { name: "Saved revenue" }),
    ).toBeVisible();
    await expect(
      page.getByText("Shared fixed version · Version 1"),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Download CSV" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Refresh data" }),
    ).toHaveCount(0);
    await expect(page.getByText("Version history")).toHaveCount(0);
    await expect(page.getByText("Original thread")).toHaveCount(0);
    await expect(page.getByText("Use in Data Chat")).toHaveCount(0);
  });
});
