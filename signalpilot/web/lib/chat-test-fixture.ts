import type {
  ConversationNotebook,
  StandaloneChatArtifact,
  StandaloneChatEvent,
  StandaloneChatRunStatus,
} from "~/lib/api";
import {
  FIXTURE_GATEWAY_SESSION_ID,
  FIXTURE_KERNEL_SESSION_ID,
  FIXTURE_NOTEBOOK_PATH,
  FIXTURE_RUN_ID,
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

/**
 * Simulate the gateway's conversation notebook resource from the replayed
 * events. Mirrors the server: live while the kernel runs, ended with a
 * saved document after it stops, null before any notebook starts.
 */
export function fixtureConversationNotebook(
  events: StandaloneChatEvent[],
): ConversationNotebook | null {
  const started = events.some((event) => event.type === "notebook_started");
  if (!started) return null;
  const stopped = events.some((event) => event.type === "kernel_stopped");
  return {
    status: stopped ? "ended" : "live",
    gateway_session_id: FIXTURE_GATEWAY_SESSION_ID,
    kernel_session_id: FIXTURE_KERNEL_SESSION_ID,
    notebook_path: FIXTURE_NOTEBOOK_PATH,
    document: stopped ? { source: PYTHON_FILE, session: null } : null,
  };
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
