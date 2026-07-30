import { expect, test, type Page, type Route } from "@playwright/test";

const CONVERSATION_ID = "standalone-chart-visual-test";
const RUN_ID = "run-chart-visual-test";
const PROJECT_ID = "project-chart-visual-test";
const PALETTE = [
  "#56B4E9",
  "#E69F00",
  "#009E73",
  "#F0E442",
  "#0072B2",
  "#D55E00",
  "#CC79A7",
  "#B3B3B3",
];

const themeConfig = {
  font: "DM Sans, Segoe UI, sans-serif",
  numberFormat: ".3~s",
  view: { fill: "#141416", stroke: "#55555C" },
  axis: {
    domainColor: "#55555C",
    grid: true,
    gridColor: "#333338",
    labelColor: "#EDEDED",
    labelFontSize: 12,
    labelLimit: 180,
    labelPadding: 8,
    tickColor: "#55555C",
    titleColor: "#EDEDED",
    titleFontSize: 13,
    titleLimit: 240,
    titlePadding: 12,
  },
  legend: {
    columns: 4,
    columnPadding: 14,
    direction: "horizontal",
    labelColor: "#EDEDED",
    labelFontSize: 12,
    labelLimit: 160,
    orient: "bottom",
    rowPadding: 5,
    symbolLimit: 8,
    titleColor: "#EDEDED",
    titleFontSize: 13,
  },
  title: {
    anchor: "start",
    color: "#EDEDED",
    fontSize: 16,
    fontWeight: 600,
    offset: 18,
  },
  range: { category: PALETTE },
  bar: { color: PALETTE[0] },
  line: { color: PALETTE[0] },
  point: { color: PALETTE[0] },
};

function spec(
  mark: "bar" | "line" | "point",
  title: string,
  encoding: Record<string, unknown>,
) {
  const markStyle =
    mark === "line"
      ? {
          type: "line",
          strokeWidth: 2.5,
          point: { filled: true, size: 58, stroke: "#141416" },
          invalid: "break-paths-filter-domains",
        }
      : mark === "point"
        ? {
            type: "point",
            filled: true,
            size: 78,
            stroke: "#141416",
            strokeWidth: 1,
            invalid: "filter",
          }
        : { type: "bar", cornerRadiusEnd: 3, invalid: "filter" };
  return {
    title,
    mark: markStyle,
    encoding,
    background: "#141416",
    width: 640,
    height: 400,
    autosize: { type: "fit", contains: "padding", resize: true },
    padding: { left: 8, right: 16, top: 8, bottom: 8 },
    config: themeConfig,
    usermeta: {
      signalpilotChartTheme: "signalpilot-dark-v1",
      categoryLimit: 24,
      legendLimit: 8,
    },
  };
}

const categoricalX = (domain: string[], mark: "bar" | "line") => ({
  field: "category",
  type: "nominal",
  axis: {
    title: "Reporting period",
    labelAngle: -45,
    labelLimit: 140,
    labelOverlap: false,
    labelFlush: false,
  },
  scale:
    mark === "bar"
      ? { type: "band", domain, paddingInner: 0.2, paddingOuter: 0.12 }
      : { type: "point", domain, padding: 0.5 },
});
const quantitativeY = {
  field: "value",
  type: "quantitative",
  axis: {
    title: "Revenue",
    labelAngle: 0,
    labelOverlap: "greedy",
    labelFlush: false,
    format: ".3~s",
  },
  scale: { type: "linear", nice: true, zero: true },
};
const seriesColor = {
  field: "series",
  type: "nominal",
  scale: { domain: ["North", "South", "West"], range: PALETTE.slice(0, 3) },
  legend: { title: "Region", symbolLimit: 8 },
};

const chartFixtures = [
  {
    filename: "bar-readability.png",
    spec: spec("bar", "Revenue includes gains and refunds", {
      x: categoricalX(
        [
          "January enterprise accounts",
          "February enterprise accounts",
          "March enterprise accounts",
          "April enterprise accounts",
          "May enterprise accounts",
        ],
        "bar",
      ),
      y: quantitativeY,
    }),
    rows: [
      { category: "January enterprise accounts", value: 1_200_000 },
      { category: "February enterprise accounts", value: -1_200_000_000 },
      { category: "March enterprise accounts", value: null },
      { category: "April enterprise accounts", value: 3_450_000_000 },
      { category: "May enterprise accounts", value: 2_100_000_000 },
    ],
  },
  {
    filename: "line-readability.png",
    spec: spec("line", "Revenue trend with a missing period", {
      x: categoricalX(
        [
          "January enterprise accounts",
          "February enterprise accounts",
          "March enterprise accounts",
          "April enterprise accounts",
          "May enterprise accounts",
        ],
        "line",
      ),
      y: quantitativeY,
    }),
    rows: [
      { category: "January enterprise accounts", value: 900_000 },
      { category: "February enterprise accounts", value: 1_400_000 },
      { category: "March enterprise accounts", value: null },
      { category: "April enterprise accounts", value: -450_000 },
      { category: "May enterprise accounts", value: 2_800_000 },
    ],
  },
  {
    filename: "point-readability.png",
    spec: spec("point", "Account size versus net revenue", {
      x: {
        field: "accounts",
        type: "quantitative",
        axis: { title: "Accounts", format: ".3~s", labelAngle: 0 },
        scale: { type: "linear", nice: true, zero: true },
      },
      y: quantitativeY,
    }),
    rows: [
      { accounts: 10, value: -350_000 },
      { accounts: 25, value: 850_000 },
      { accounts: 48, value: 2_400_000 },
      { accounts: 70, value: 3_900_000 },
      { accounts: 95, value: 6_200_000 },
    ],
  },
  {
    filename: "multi-series-readability.png",
    spec: spec("bar", "Revenue by region", {
      x: categoricalX(
        [
          "January accounts",
          "February accounts",
          "March accounts",
          "April accounts",
        ],
        "bar",
      ),
      y: quantitativeY,
      color: seriesColor,
      xOffset: {
        field: "series",
        type: "nominal",
        scale: { domain: ["North", "South", "West"] },
      },
    }),
    rows: [
      ...[
        "January accounts",
        "February accounts",
        "March accounts",
        "April accounts",
      ].flatMap((category, index) =>
        ["North", "South", "West"].map((series, seriesIndex) => ({
          category,
          series,
          value: (index + 1) * (seriesIndex + 1) * 680_000,
        })),
      ),
    ],
  },
];

function artifact(fixture: (typeof chartFixtures)[number], index: number) {
  return {
    id: `artifact-${index}`,
    run_id: RUN_ID,
    assistant_message_id: "assistant-message",
    kind: "chart",
    filename: fixture.filename,
    mime_type: "image/png",
    snapshot: {
      spec: fixture.spec,
      rows: fixture.rows,
      source: { columns: [], rows: fixture.rows, truncated: false },
      display: {
        category_limit: 24,
        legend_limit: 8,
        limited: false,
        omitted_rows: 0,
      },
      truncated: false,
    },
    provenance: null,
    freshness_at: null,
    assumptions: [],
    exclusions: [],
    caveats: [],
    parent_artifact_id: null,
    created_at: "2026-07-30T12:00:00Z",
    download_formats: ["png", "csv"],
  };
}

const conversation = {
  id: CONVERSATION_ID,
  project_id: PROJECT_ID,
  project_name: "Revenue analytics",
  branch: "main",
  title: "Chart readability",
  status: "active",
  created_at: 1_753_878_400,
  updated_at: 1_753_878_400,
  run_status: "completed",
};

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mockStandaloneChat(page: Page) {
  await page.route("**/api/local-key", (route) =>
    fulfillJson(route, { key: "sp_visual_test" }),
  );
  await page.route(/^http:\/\/localhost:\d+\/api\/chat(?:\/.*)?$/, (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/chat/bootstrap") {
      return fulfillJson(route, {
        enabled: true,
        projects: [
          {
            id: PROJECT_ID,
            name: "revenue",
            display_name: "Revenue analytics",
            connection_name: "production",
            default_branch: "main",
            ready: true,
            readiness_message: "Ready",
          },
        ],
        selected_project_id: PROJECT_ID,
        is_admin: true,
        starter_questions: [],
      });
    }
    if (pathname === "/api/chat/conversations") {
      return fulfillJson(route, { conversations: [conversation] });
    }
    if (pathname === `/api/chat/conversations/${CONVERSATION_ID}`) {
      return fulfillJson(route, {
        conversation,
        messages: [
          {
            id: "user-message",
            role: "user",
            content: "Show the important revenue patterns.",
            sequence: 1,
            created_at: 1_753_878_400,
            metadata: { run_id: RUN_ID },
          },
          {
            id: "assistant-message",
            role: "assistant",
            content: "Here are the requested chart views.",
            sequence: 2,
            created_at: 1_753_878_401,
            metadata: { run_id: RUN_ID, status: "completed" },
          },
        ],
        artifacts: chartFixtures.map(artifact),
        current_run: {
          id: RUN_ID,
          conversation_id: CONVERSATION_ID,
          status: "completed",
          retry_of_run_id: null,
          public_error_code: null,
          public_error_message: null,
          cancellation_requested_at: null,
          created_at: "2026-07-30T12:00:00Z",
          started_at: "2026-07-30T12:00:00Z",
          terminal_at: "2026-07-30T12:00:01Z",
          last_event_sequence: 1,
        },
        run_events: [],
      });
    }
    if (pathname === `/api/chat/projects/${PROJECT_ID}/readiness`) {
      return fulfillJson(route, {
        project_id: PROJECT_ID,
        ready: true,
        code: "ready",
        message: "Ready",
        setup_cta: false,
        branch: "main",
        connection_name: "production",
        starter_questions: [],
      });
    }
    return route.abort();
  });
}

test.describe("standalone data-chat chart screenshots", () => {
  test.use({ viewport: { width: 1440, height: 1000 }, colorScheme: "dark" });

  test.beforeEach(async ({ page }) => {
    await mockStandaloneChat(page);
    await page.goto(`/chats/${CONVERSATION_ID}`, {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByTestId("standalone-chart-artifact")).toHaveCount(
      chartFixtures.length,
    );
    await page.waitForFunction(() => document.fonts.status === "loaded");
  });

  test("uses headerless contextual chat controls", async ({
    page,
  }) => {
    await expect(
      page.getByRole("button", { name: "Collapse chat history" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Share conversation" }),
    ).toBeVisible();
    await expect(
      page.getByRole("combobox", { name: "Select project" }),
    ).toHaveCount(0);
    await expect(page.getByTestId("standalone-chat-header")).toHaveCount(0);

    await page.getByRole("button", { name: "Collapse chat history" }).click();
    await expect(page.getByText("Your chats", { exact: true })).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Expand chat history" }),
    ).toBeVisible();

    await page.goto("/chats", { waitUntil: "domcontentloaded" });

    const composer = page.getByTestId("standalone-chat-composer");
    await expect(
      composer.getByRole("combobox", { name: "Select project" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Share conversation" }),
    ).toHaveCount(0);
  });

  for (const fixture of chartFixtures) {
    test(`${fixture.filename} stays readable`, async ({ page }) => {
      const chart = page.locator(
        `[data-testid="standalone-chart-artifact"][data-filename="${fixture.filename}"]`,
      );
      await expect(chart.locator("svg.marks")).toBeVisible();
      await expect(chart).toHaveScreenshot(fixture.filename, {
        animations: "disabled",
        caret: "hide",
        maxDiffPixelRatio: 0.01,
      });
    });
  }
});
