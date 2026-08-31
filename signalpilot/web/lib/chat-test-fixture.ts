import type {
  ConversationFileInfo,
  ConversationNotebook,
  SqlTraceExecution,
  StandaloneChatArtifact,
  StandaloneChatEvent,
  StandaloneChatRunStatus,
} from "~/lib/api";
import {
  FIXTURE_GATEWAY_SESSION_ID,
  FIXTURE_KERNEL_SESSION_ID,
  FIXTURE_NOTEBOOK_PATH,
  FIXTURE_QUERY_TOOL_CALL_ID,
  FIXTURE_RUN_ID,
  FIXTURE_WRITTEN_FILE_PATH,
  PYTHON_FILE,
  fixtureEvents,
} from "./chat-test-fixture-data";

/**
 * Deterministic fixture for /chats/test: a scripted agent run replayed on a
 * timeline so the chat UX can be exercised without a live model or gateway.
 * The raw event script lives in lib/chat-test-fixture-data.ts; this module
 * re-exports it and adds the replay accessors.
 * `at` is the millisecond offset from replay start at which the event lands.
 */

export {
  FIXTURE_GATEWAY_SESSION_ID,
  FIXTURE_KERNEL_SESSION_ID,
  FIXTURE_NOTEBOOK_PATH,
  FIXTURE_RUN_ID,
  fixtureEvents,
};
export type { FixtureEvent } from "./chat-test-fixture-data";

const BASE_EPOCH = Date.UTC(2026, 0, 15, 17, 30, 0);

/** Name of the second fixture notebook; appears late in the replay. */
export const FIXTURE_SECOND_NOTEBOOK_NAME = "forecast";
export const FIXTURE_SECOND_NOTEBOOK_PATH =
  "/tmp/signalpilot-chat-runs/run-fixture-0001/forecast.py";

const FORECAST_FILE = `# %% [markdown]
# ## Q4 forecast scratch notebook
# Quick projection from the Q3 regional growth rates.

# %%
q3 = {"AMER": 9_204_100, "EMEA": 4_812_400, "APAC": 2_118_800}
growth = {"AMER": 0.031, "EMEA": 0.173, "APAC": 0.315}
q4 = {region: round(value * (1 + growth[region])) for region, value in q3.items()}
q4
`;

/**
 * Simulate the gateway's conversation notebook list from the replayed
 * events. Mirrors the server: the "analysis" notebook is live while the
 * kernel runs and ends with a saved document after it stops; a second
 * "forecast" notebook lands, already ended, once the archive completes.
 */
export function fixtureConversationNotebooks(
  events: StandaloneChatEvent[],
): ConversationNotebook[] {
  const notebooks: ConversationNotebook[] = [];
  const started = events.some((event) => event.type === "notebook_started");
  if (started) {
    const stopped = events.some((event) => event.type === "kernel_stopped");
    notebooks.push({
      name: "analysis",
      status: stopped ? "ended" : "live",
      gateway_session_id: FIXTURE_GATEWAY_SESSION_ID,
      kernel_session_id: FIXTURE_KERNEL_SESSION_ID,
      notebook_path: FIXTURE_NOTEBOOK_PATH,
      document: stopped ? { source: PYTHON_FILE, session: null } : null,
    });
  }
  const archived = events.some((event) => event.type === "archive_completed");
  if (archived) {
    notebooks.push({
      name: FIXTURE_SECOND_NOTEBOOK_NAME,
      status: "ended",
      gateway_session_id: FIXTURE_GATEWAY_SESSION_ID,
      kernel_session_id: null,
      notebook_path: FIXTURE_SECOND_NOTEBOOK_PATH,
      document: { source: FORECAST_FILE, session: null },
    });
  }
  return notebooks;
}

/** Compat accessor: the default ("analysis") notebook, or null. */
export function fixtureConversationNotebook(
  events: StandaloneChatEvent[],
): ConversationNotebook | null {
  return (
    fixtureConversationNotebooks(events).find(
      (notebook) => notebook.name === "analysis",
    ) ?? null
  );
}

/**
 * Simulate the gateway's conversation file manifest from the replayed
 * events. The fixture agent writes one Python file with the Write tool at
 * ~9.2s; the Edit at ~14.3s bumps its hash and updated_at.
 */
export function fixtureConversationFiles(
  events: StandaloneChatEvent[],
): ConversationFileInfo[] {
  const written = events.some(
    (event) => event.type === "tool_started" && event.payload.tool === "Write",
  );
  if (!written) return [];
  const edited = events.some(
    (event) => event.type === "tool_started" && event.payload.tool === "Edit",
  );
  return [
    {
      id: "file-fixture-1",
      path: FIXTURE_WRITTEN_FILE_PATH,
      filename: FIXTURE_WRITTEN_FILE_PATH.split("/").pop() ?? "",
      kind: "code",
      mime_type: "text/x-python",
      byte_size: PYTHON_FILE.length,
      content_hash: edited ? "fixture-file-hash-2" : "fixture-file-hash-1",
      origin_run_id: FIXTURE_RUN_ID,
      origin: "mirror",
      status: "active",
      created_at: fixtureEventCreatedAt(9_200),
      updated_at: fixtureEventCreatedAt(edited ? 14_300 : 9_200),
    },
  ];
}

/**
 * Simulate the gateway's SQL trace from the replayed events. Only the
 * governed query_database call produces an execution, and only once its
 * completion event has landed; validate_sql never executes.
 */
export function fixtureSqlTrace(
  events: StandaloneChatEvent[],
): SqlTraceExecution[] {
  let armed = false;
  let sql: string | null = null;
  for (const event of events) {
    if (
      event.type === "tool_started" &&
      event.payload.tool === "mcp__signalpilot__query_database"
    ) {
      armed = true;
    } else if (
      armed &&
      sql === null &&
      event.type === "sql" &&
      typeof event.payload.sql === "string"
    ) {
      sql = event.payload.sql;
    }
  }
  const completed = events.some(
    (event) =>
      event.type === "tool_completed" &&
      event.payload.tool_call_id === FIXTURE_QUERY_TOOL_CALL_ID,
  );
  if (sql === null || !completed) return [];
  return [
    {
      execution_id: "exec-fixture-1",
      run_id: FIXTURE_RUN_ID,
      connection_name: "warehouse_prod",
      sql,
      sql_hash: "fixture-sql-hash-1",
      status: "completed",
      query_path: "governed",
      estimated_cost_usd: 0.0031,
      actual_cost_usd: 0.0028,
      actual_scan_bytes: 52_428_800,
      execution_ms: 2_650,
      row_count: 3,
      completeness: "complete",
      public_error_code: null,
      created_at: fixtureEventCreatedAt(4_720),
      started_at: fixtureEventCreatedAt(4_750),
      terminal_at: fixtureEventCreatedAt(7_400),
    },
  ];
}

export type FixtureArtifact = StandaloneChatArtifact & { at: number };

export const FIXTURE_USER_PROMPT =
  "Which regions drove Q3 revenue growth compared to Q2?";

const TABLE_ROWS = [
  { region: "AMER", revenue_q3: 9_204_100, revenue_q2: 8_930_600, growth_pct: 3.1 },
  { region: "EMEA", revenue_q3: 4_812_400, revenue_q2: 4_101_900, growth_pct: 17.3 },
  { region: "APAC", revenue_q3: 2_118_800, revenue_q2: 1_611_200, growth_pct: 31.5 },
];

export const fixtureArtifacts: FixtureArtifact[] = [
  {
    at: 16_700,
    id: "artifact-table-1",
    run_id: FIXTURE_RUN_ID,
    assistant_message_id: null,
    kind: "table",
    filename: "q3_revenue_by_region.csv",
    mime_type: "text/csv",
    snapshot: {
      columns: ["region", "revenue_q3", "revenue_q2", "growth_pct"],
      rows: TABLE_ROWS,
      truncated: false,
    },
    provenance: null,
    freshness_at: "2026-01-15T06:10:00Z",
    assumptions: ["Net revenue excludes refunds issued after quarter close."],
    exclusions: ["Internal test accounts (7 accounts) are excluded."],
    caveats: ["APAC growth reflects a small Q2 base."],
    parent_artifact_id: null,
    created_at: "2026-01-15T17:30:16Z",
    download_formats: ["csv"],
  },
  {
    at: 17_900,
    id: "artifact-chart-1",
    run_id: FIXTURE_RUN_ID,
    assistant_message_id: null,
    kind: "chart",
    filename: "q3_growth_by_region.vl.json",
    mime_type: "application/json",
    snapshot: {
      spec: {
        mark: { type: "bar" },
        encoding: {
          x: { field: "region", type: "nominal", title: "Region" },
          y: { field: "revenue", type: "quantitative", title: "Net revenue (USD)" },
          xOffset: { field: "quarter" },
          color: { field: "quarter", type: "nominal", title: "Quarter" },
        },
      },
      rows: TABLE_ROWS.flatMap((row) => [
        { region: row.region, quarter: "2025-Q2", revenue: row.revenue_q2 },
        { region: row.region, quarter: "2025-Q3", revenue: row.revenue_q3 },
      ]),
      truncated: false,
    },
    provenance: null,
    freshness_at: "2026-01-15T06:10:00Z",
    assumptions: [],
    exclusions: [],
    caveats: [],
    parent_artifact_id: null,
    created_at: "2026-01-15T17:30:18Z",
    download_formats: ["csv"],
  },
];

const REPORT_HTML = `<!doctype html><html><head><style>
body { font-family: -apple-system, "Segoe UI", sans-serif; margin: 2rem; color: #1a1a1a; }
h1 { font-size: 1.3rem; } h2 { font-size: 1rem; margin-top: 1.6rem; }
table { border-collapse: collapse; margin-top: .8rem; }
td, th { border: 1px solid #ddd; padding: .45rem .8rem; font-size: .85rem; text-align: right; }
th:first-child, td:first-child { text-align: left; }
.up { color: #0a7d33; } .flag { color: #b54708; font-weight: 600; }
</style></head><body>
<h1>Q3 2025 Regional Revenue Review</h1>
<p>Q3 revenue reached <b>$16.1M</b>, up <b>10.4%</b> quarter over quarter. EMEA drove the
growth in absolute terms; APAC grew fastest from a smaller base.</p>
<h2>Per-region summary</h2>
<table><tr><th>Region</th><th>Q2</th><th>Q3</th><th>Growth</th></tr>
<tr><td>AMER</td><td>$8.93M</td><td>$9.20M</td><td class="up">+3.1%</td></tr>
<tr><td>EMEA</td><td>$4.10M</td><td>$4.81M</td><td class="up">+17.3%</td></tr>
<tr><td>APAC</td><td>$1.61M</td><td>$2.12M</td><td class="up">+31.5%</td></tr></table>
<h2>Watch items</h2>
<p class="flag">APAC growth is concentrated in two marketplace launches; retention after
the launch quarter is not yet observable.</p>
</body></html>`;

export const fixtureReportArtifact: FixtureArtifact = {
  at: 18_000,
  id: "artifact-report-1",
  run_id: FIXTURE_RUN_ID,
  assistant_message_id: null,
  kind: "report",
  filename: "q3_regional_review.html",
  mime_type: "text/html",
  snapshot: { html: REPORT_HTML },
  provenance: null,
  freshness_at: "2026-01-15T06:10:00Z",
  assumptions: [],
  exclusions: [],
  caveats: [],
  parent_artifact_id: null,
  created_at: "2026-01-15T17:30:18Z",
  download_formats: ["html"],
};
fixtureArtifacts.push(fixtureReportArtifact);

export const FIXTURE_TOTAL_MS = 21_200;

export function fixtureEventCreatedAt(at: number): string {
  return new Date(BASE_EPOCH + at).toISOString();
}

export function materializeFixtureEvents(
  upToMs: number,
): StandaloneChatEvent[] {
  return fixtureEvents
    .filter((event) => event.at <= upToMs)
    .map(({ at, ...event }) => ({
      ...event,
      created_at: fixtureEventCreatedAt(at),
    }));
}

export function fixtureRunStatus(upToMs: number): StandaloneChatRunStatus {
  const statuses = fixtureEvents.filter(
    (event) => event.type === "status" && event.at <= upToMs,
  );
  const last = statuses[statuses.length - 1];
  const value = last?.payload.status;
  return typeof value === "string"
    ? (value as StandaloneChatRunStatus)
    : upToMs > 0
      ? "running"
      : "queued";
}

export function fixtureAssembledText(upToMs: number): string {
  return fixtureEvents
    .filter((event) => event.type === "text_delta" && event.at <= upToMs)
    .map((event) =>
      typeof event.payload.delta === "string" ? event.payload.delta : "",
    )
    .join("");
}
