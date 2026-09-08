import type { ConversationFileInfo, StandaloneChatEvent } from "~/lib/api";
import type {
  DashboardVersion,
  PublishDashboardRequest,
  PublishedDashboard,
} from "~/lib/api/dashboards";
import type { FixtureEvent } from "./chat-test-fixture-data";

/**
 * Fixture extension: the dashboard artifact the scripted agent writes from
 * the notebook cell (a `*.dashboard.json` spec plus its two datasets) and
 * the two dashboard tools that check and render it. The spec is a copy of
 * `dashboard-renderer/fixtures/revenue.dashboard.json` with the dataset
 * paths the agent would really use under `artifacts/`.
 */

export const FIXTURE_DASHBOARD_FILE_PATH = "artifacts/revenue.dashboard.json";
export const FIXTURE_DASHBOARD_MONTHLY_PATH = "artifacts/revenue_monthly.csv";
export const FIXTURE_DASHBOARD_REGION_PATH = "artifacts/revenue_by_region.json";

export const FIXTURE_DASHBOARD_FILE_ID = "file-fixture-dashboard";
export const FIXTURE_DASHBOARD_MONTHLY_FILE_ID = "file-fixture-dashboard-monthly";
export const FIXTURE_DASHBOARD_REGION_FILE_ID = "file-fixture-dashboard-region";

export const FIXTURE_DASHBOARD_TITLE = "Revenue overview 2024";

export const FIXTURE_DASHBOARD_CHART_IDS = [
  "kpi_revenue",
  "kpi_orders",
  "kpi_aov",
  "kpi_growth",
  "revenue_trend",
  "region_share",
  "region_vs_target",
  "customers_vs_revenue",
  "top_months",
] as const;

export const DASHBOARD_SPEC_FILE = JSON.stringify(
  {
    version: 1,
    title: FIXTURE_DASHBOARD_TITLE,
    description:
      "Monthly revenue by region with targets, share of revenue and customer economics.",
    layout: { columns: 12, rowHeight: 72 },
    datasets: {
      summary: {
        rows: [
          {
            total_revenue: 5896400,
            prior_revenue: 5210000,
            orders: 28410,
            avg_order_value: 207.55,
            growth: 0.1318,
          },
        ],
      },
      revenue_monthly: { file: FIXTURE_DASHBOARD_MONTHLY_PATH },
      revenue_by_region: {
        file: FIXTURE_DASHBOARD_REGION_PATH,
        source: {
          kind: "sql",
          connection: "warehouse",
          sql: "select region, sum(revenue) as revenue from fct_orders group by 1",
        },
      },
    },
    filters: [
      {
        id: "period",
        label: "Period",
        dataset: "revenue_monthly",
        column: "month",
        type: "date_range",
        default: { from: "2024-01-01", to: "2024-12-01" },
      },
      {
        id: "regions",
        label: "Regions",
        dataset: "revenue_by_region",
        column: "region",
        type: "in",
        default: ["North", "South", "East", "West"],
      },
    ],
    charts: [
      {
        id: "kpi_revenue",
        type: "kpi",
        title: "Total revenue",
        dataset: "summary",
        value: { column: "total_revenue", format: "currency:USD" },
        comparison: { column: "prior_revenue", label: "Prior year", format: "currency:USD" },
        grid: { x: 0, y: 0, w: 3, h: 2 },
      },
      {
        id: "kpi_orders",
        type: "kpi",
        title: "Orders",
        dataset: "summary",
        value: { column: "orders", format: "integer" },
        grid: { x: 3, y: 0, w: 3, h: 2 },
      },
      {
        id: "kpi_aov",
        type: "kpi",
        title: "Average order value",
        dataset: "summary",
        value: { column: "avg_order_value", format: "currency:USD" },
        grid: { x: 6, y: 0, w: 3, h: 2 },
      },
      {
        id: "kpi_growth",
        type: "kpi",
        title: "Growth vs prior year",
        description: "Year over year revenue growth.",
        dataset: "summary",
        value: { column: "growth", format: "percentage" },
        grid: { x: 9, y: 0, w: 3, h: 2 },
      },
      {
        id: "revenue_trend",
        type: "line",
        title: "Monthly revenue by region",
        dataset: "revenue_monthly",
        x: { column: "month", type: "date", label: "Month" },
        y: [{ column: "revenue", label: "Revenue", format: "currency:USD" }],
        series: { column: "region" },
        grid: { x: 0, y: 2, w: 8, h: 4 },
      },
      {
        id: "region_share",
        type: "pie",
        title: "Revenue share by region",
        dataset: "revenue_by_region",
        label: "region",
        value: { column: "revenue", format: "currency:USD" },
        donut: true,
        grid: { x: 8, y: 2, w: 4, h: 4 },
      },
      {
        id: "region_vs_target",
        type: "bar",
        title: "Revenue vs target by region",
        dataset: "revenue_by_region",
        x: { column: "region", type: "category" },
        y: [
          { column: "revenue", label: "Revenue", format: "currency:USD" },
          { column: "target", label: "Target", format: "currency:USD" },
        ],
        sort: { column: "revenue", direction: "desc" },
      },
      {
        id: "customers_vs_revenue",
        type: "scatter",
        title: "Customers vs revenue",
        dataset: "revenue_by_region",
        x: { column: "customers", type: "number", label: "Customers" },
        y: { column: "revenue", label: "Revenue", format: "currency:USD" },
        size: "avg_order_value",
        color: "region",
      },
      {
        id: "top_months",
        type: "table",
        title: "Top months by revenue",
        dataset: "revenue_monthly",
        columns: [
          { column: "month", label: "Month" },
          { column: "region", label: "Region" },
          { column: "revenue", label: "Revenue", format: "currency:USD" },
          { column: "orders", label: "Orders", format: "integer" },
          { column: "target", label: "Target", format: "currency:USD" },
        ],
        sort: { column: "revenue", direction: "desc" },
        limit: 10,
      },
    ],
  },
  null,
  2,
);

const MONTHS = [
  "2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01", "2024-05-01", "2024-06-01",
  "2024-07-01", "2024-08-01", "2024-09-01", "2024-10-01", "2024-11-01", "2024-12-01",
];
const MONTHLY_ROWS: [string, number, number, number][][] = [
  [["North", 120000, 667, 120000], ["South", 102125, 511, 95000], ["East", 158187, 719, 140000], ["West", 92000, 383, 80000]],
  [["North", 131580, 731, 122160], ["South", 109488, 547, 96710], ["East", 164220, 746, 142520], ["West", 92200, 384, 81440]],
  [["North", 141012, 783, 124320], ["South", 113620, 568, 98420], ["East", 164514, 748, 145040], ["West", 89440, 373, 82880]],
  [["North", 146280, 813, 126480], ["South", 113781, 569, 100130], ["East", 159530, 725, 147560], ["West", 84800, 353, 84320]],
  [["North", 146436, 814, 128640], ["South", 110295, 551, 101840], ["East", 151200, 687, 150080], ["West", 79920, 333, 85760]],
  [["North", 141900, 788, 130800], ["South", 104500, 523, 103550], ["East", 142450, 648, 152600], ["West", 76568, 319, 87200]],
  [["North", 134400, 747, 132960], ["South", 98420, 492, 105260], ["East", 136431, 620, 155120], ["West", 76160, 317, 88640]],
  [["North", 126540, 703, 135120], ["South", 94231, 471, 106970], ["East", 135660, 617, 157640], ["West", 79353, 331, 90080]],
  [["North", 121117, 673, 137280], ["South", 93670, 468, 108680], ["East", 141304, 642, 160160], ["West", 85840, 358, 91520]],
  [["North", 120360, 669, 139440], ["South", 97538, 488, 110390], ["East", 152810, 695, 162680], ["West", 94400, 393, 92960]],
  [["North", 125294, 696, 141600], ["South", 105450, 527, 112100], ["East", 168000, 764, 165200], ["West", 103200, 430, 94400]],
  [["North", 135420, 752, 143760], ["South", 115900, 580, 113810], ["East", 183610, 835, 167720], ["West", 110279, 459, 95840]],
];

export const DASHBOARD_MONTHLY_CSV_FILE = [
  "month,region,revenue,orders,target",
  ...MONTHS.flatMap((month, index) =>
    MONTHLY_ROWS[index].map((row) => [month, ...row].join(",")),
  ),
  "",
].join("\n");

const REGION_ROWS = [
  { region: "North", revenue: 1627200, target: 1584000, customers: 1200, avg_order_value: 180, growth: 0.12 },
  { region: "South", revenue: 1288200, target: 1254000, customers: 1630, avg_order_value: 200, growth: 0.08 },
  { region: "East", revenue: 1898400, target: 1848000, customers: 2060, avg_order_value: 220, growth: 0.21 },
  { region: "West", revenue: 1084800, target: 1056000, customers: 2490, avg_order_value: 240, growth: -0.03 },
];

export const DASHBOARD_REGION_JSON_FILE = JSON.stringify(REGION_ROWS, null, 2);

/** Millisecond offsets shared by the events and the simulated manifest. */
const DASHBOARD_CAPTURED_AT = 20_750;
const RUN_CELLS_TOOL_CALL_ID = "t10b";
const SAMPLE_TOOL_CALL_ID = "t11d";
const SCREENSHOT_TOOL_CALL_ID = "t12d";

const FILE_ENTRIES = [
  {
    id: FIXTURE_DASHBOARD_FILE_ID,
    path: FIXTURE_DASHBOARD_FILE_PATH,
    kind: "dashboard" as const,
    mime: "application/json",
    body: DASHBOARD_SPEC_FILE,
  },
  {
    id: FIXTURE_DASHBOARD_MONTHLY_FILE_ID,
    path: FIXTURE_DASHBOARD_MONTHLY_PATH,
    kind: "data" as const,
    mime: "text/csv",
    body: DASHBOARD_MONTHLY_CSV_FILE,
  },
  {
    id: FIXTURE_DASHBOARD_REGION_FILE_ID,
    path: FIXTURE_DASHBOARD_REGION_PATH,
    kind: "data" as const,
    mime: "application/json",
    body: DASHBOARD_REGION_JSON_FILE,
  },
];

/** The wire projection of `dashboard_sample_data` for two charts. */
export function fixtureDashboardSampleResult() {
  const monthlyRows = MONTHLY_ROWS[0].map(([region, revenue, orders, target]) => ({
    month: MONTHS[0],
    region,
    revenue,
    orders,
    target,
  }));
  return {
    kind: "dashboard_sample" as const,
    dashboard_valid: true,
    charts: [
      {
        id: "revenue_trend",
        type: "line",
        dataset: "revenue_monthly",
        row_count: 48,
        issue_count: 0,
        columns: [
          { name: "month", inferred_type: "date" },
          { name: "region", inferred_type: "string" },
          { name: "revenue", inferred_type: "number" },
          { name: "orders", inferred_type: "number" },
          { name: "target", inferred_type: "number" },
        ],
        rows: monthlyRows,
        issues: [],
      },
      {
        id: "region_share",
        type: "pie",
        dataset: "revenue_by_region",
        row_count: 4,
        issue_count: 0,
        columns: [
          { name: "region", inferred_type: "string" },
          { name: "revenue", inferred_type: "number" },
          { name: "target", inferred_type: "number" },
          { name: "customers", inferred_type: "number" },
          { name: "avg_order_value", inferred_type: "number" },
          { name: "growth", inferred_type: "number" },
        ],
        rows: REGION_ROWS,
        issues: [],
      },
    ],
  };
}

/** The wire projection of `dashboard_screenshot` for the whole dashboard. */
export function fixtureDashboardScreenshotResult() {
  return {
    kind: "dashboard_screenshot" as const,
    dashboard_valid: true,
    rendered: [...FIXTURE_DASHBOARD_CHART_IDS],
    failed: [],
    width: 1280,
    height: 684,
    preview_path: ".dashboard-previews/revenue-1737051660.png",
  };
}

/**
 * The dashboard segment of the scripted run: the sandbox capture that lists
 * the spec and its datasets (anchored to the run_cells call), then the
 * data check and the render. Slots after the runtime capture (20.7s) and
 * before the follow-up verification chain (21.2s).
 */
export function dashboardFixtureEvents(runId: string): FixtureEvent[] {
  const sampleResult = fixtureDashboardSampleResult();
  const screenshotResult = fixtureDashboardScreenshotResult();
  return [
    {
      at: DASHBOARD_CAPTURED_AT,
      run_id: runId,
      sequence: 0,
      type: "files_changed",
      payload: {
        changed: FILE_ENTRIES.length,
        files: FILE_ENTRIES.map((entry) => ({
          file_id: entry.id,
          path: entry.path,
          filename: entry.path.split("/").pop() ?? entry.path,
          kind: entry.kind,
          byte_size: entry.body.length,
          content_hash: `${entry.id}-hash-1`,
          deleted: false,
        })),
        tool_call_id: RUN_CELLS_TOOL_CALL_ID,
        origin: "runtime",
      },
    },
    {
      at: 20_950,
      run_id: runId,
      sequence: 0,
      type: "tool_started",
      payload: {
        tool: "mcp__standalone-chat__dashboard_sample_data",
        tool_call_id: SAMPLE_TOOL_CALL_ID,
        input: {
          path: FIXTURE_DASHBOARD_FILE_PATH,
          chart_ids: ["revenue_trend", "region_share"],
          limit: 5,
        },
      },
    },
    {
      at: 21_050,
      run_id: runId,
      sequence: 0,
      type: "tool_completed",
      payload: {
        tool_call_id: SAMPLE_TOOL_CALL_ID,
        tool: "mcp__standalone-chat__dashboard_sample_data",
        error: false,
        summary: "2 charts checked, 0 issues",
        result: sampleResult,
        result_text: JSON.stringify(sampleResult),
        result_chars: JSON.stringify(sampleResult).length,
        truncated: false,
        v: 1,
      },
    },
    {
      at: 21_080,
      run_id: runId,
      sequence: 0,
      type: "tool_started",
      payload: {
        tool: "mcp__standalone-chat__dashboard_screenshot",
        tool_call_id: SCREENSHOT_TOOL_CALL_ID,
        input: { path: FIXTURE_DASHBOARD_FILE_PATH, width: 1280, theme: "light" },
      },
    },
    {
      at: 21_180,
      run_id: runId,
      sequence: 0,
      type: "tool_completed",
      payload: {
        tool_call_id: SCREENSHOT_TOOL_CALL_ID,
        tool: "mcp__standalone-chat__dashboard_screenshot",
        error: false,
        summary: "Rendered 9 charts",
        result: screenshotResult,
        result_text: JSON.stringify(screenshotResult),
        result_chars: JSON.stringify(screenshotResult).length,
        truncated: false,
        v: 1,
      },
    },
  ];
}

function captured(events: StandaloneChatEvent[], path: string): boolean {
  return events.some((event) => {
    if (event.type !== "files_changed") return false;
    const files = Array.isArray(event.payload.files)
      ? (event.payload.files as Array<{ path?: unknown }>)
      : [];
    return files.some((file) => file.path === path);
  });
}

/** Manifest rows for the dashboard files, gated on their capture event. */
export function fixtureDashboardFiles(
  events: StandaloneChatEvent[],
  runId: string,
  createdAt: (atMs: number) => string,
): ConversationFileInfo[] {
  return FILE_ENTRIES.filter((entry) => captured(events, entry.path)).map((entry) => ({
    id: entry.id,
    path: entry.path,
    filename: entry.path.split("/").pop() ?? entry.path,
    kind: entry.kind,
    mime_type: entry.mime,
    byte_size: entry.body.length,
    content_hash: `${entry.id}-hash-1`,
    origin_run_id: runId,
    origin: "runtime",
    status: "active",
    created_at: createdAt(DASHBOARD_CAPTURED_AT),
    updated_at: createdAt(DASHBOARD_CAPTURED_AT),
  }));
}

/** Literal contents of the dashboard files, by manifest id. */
export function fixtureDashboardFileContent(
  fileId: string,
): { body: string; mime: string } | null {
  const entry = FILE_ENTRIES.find((candidate) => candidate.id === fileId);
  return entry ? { body: entry.body, mime: entry.mime } : null;
}

/** The dashboard already in the fixture gallery: editable, so the publish
 * dialog offers it as an "Update existing" target. */
export const FIXTURE_PUBLISHED_DASHBOARD_ID = "dash_fixture_existing";
export const FIXTURE_PUBLISHED_DASHBOARD_NAME = "Weekly pipeline health";
/** Slug the fake gateway answers a publish with. */
export const FIXTURE_PUBLISHED_SLUG = "revenue-overview-2024";

function fixturePublishedDashboard(
  overrides: Partial<PublishedDashboard> = {},
): PublishedDashboard {
  const at = "2026-09-01T06:00:00Z";
  return {
    id: FIXTURE_PUBLISHED_DASHBOARD_ID,
    slug: "weekly-pipeline-health",
    name: FIXTURE_PUBLISHED_DASHBOARD_NAME,
    description: "Pipeline stages and conversion, refreshed nightly.",
    visibility: "org",
    share_token: null,
    project_id: null,
    created_by_user_id: "user-fixture-me",
    created_by_label: "you",
    source_conversation_id: "conversation-fixture-0",
    source_file_id: "file-fixture-other",
    current_version_id: "dver_fixture_1",
    current_version_no: 3,
    chart_count: 6,
    refresh: { interval_minutes: 1440, anchor_time: "06:00", timezone: "America/New_York", mode: "sql" },
    notify_on_failure: true,
    next_refresh_at: "2026-09-09T10:00:00Z",
    last_refresh_at: at,
    last_refresh_status: "succeeded",
    created_at: at,
    updated_at: at,
    archived_at: null,
    can_edit: true,
    ...overrides,
  };
}

/**
 * In-memory stand-in for the dashboards API used by the publish dialog at
 * /chats/test and in unit tests: one editable dashboard in the gallery, and
 * a publish that answers with a fixed slug (or a new version of the target).
 */
export function createFixtureDashboardPublishApi(options: { latencyMs?: number } = {}) {
  const latency = options.latencyMs ?? 0;
  const wait = () => new Promise<void>((resolve) => setTimeout(resolve, latency));
  const gallery: PublishedDashboard[] = [fixturePublishedDashboard()];
  const calls: { conversationId: string; fileId: string; body: PublishDashboardRequest }[] = [];
  return {
    calls,
    async listDashboards() {
      await wait();
      return { dashboards: [...gallery] };
    },
    async publishDashboard(conversationId: string, fileId: string, body: PublishDashboardRequest) {
      await wait();
      calls.push({ conversationId, fileId, body });
      const now = new Date().toISOString();
      const existing = body.target_dashboard_id
        ? gallery.find((dashboard) => dashboard.id === body.target_dashboard_id)
        : undefined;
      const versionNo = (existing?.current_version_no ?? 0) + 1;
      const dashboard = fixturePublishedDashboard({
        ...(existing ?? {}),
        id: existing?.id ?? "dash_fixture_published",
        slug: existing?.slug ?? FIXTURE_PUBLISHED_SLUG,
        name: body.name,
        description: body.description ?? null,
        visibility: body.visibility,
        source_conversation_id: conversationId,
        source_file_id: fileId,
        current_version_id: `dver_fixture_${versionNo}`,
        current_version_no: versionNo,
        chart_count: FIXTURE_DASHBOARD_CHART_IDS.length,
        refresh: body.refresh,
        notify_on_failure: body.notify_on_failure ?? true,
        created_at: existing?.created_at ?? now,
        updated_at: now,
      });
      const index = gallery.findIndex((item) => item.id === dashboard.id);
      if (index >= 0) gallery[index] = dashboard;
      else gallery.unshift(dashboard);
      const version: DashboardVersion = {
        id: dashboard.current_version_id ?? "",
        version_no: versionNo,
        produced_by: "publish",
        producer_ref: "user-fixture-me",
        chart_count: dashboard.chart_count,
        dataset_meta: {},
        created_at: now,
      };
      return { dashboard, version };
    },
  };
}
