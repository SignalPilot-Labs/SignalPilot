import type {
  ConversationFileInfo,
  ConversationNotebook,
  SqlTraceExecution,
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
  type FixtureEvent,
} from "./chat-test-fixture-data";
import {
  CHART_SVG_FILE,
  CSV_FILE,
  REPORT_HTML_FILE,
  REVENUE_CSV_FILE,
  REVENUE_PNG_BASE64,
  SUMMARY_MD_FILE,
  fixtureArtifactFiles,
} from "./chat-test-fixture-artifact-files";

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
  // Export files (HTML report, SVG chart, CSV) land later in the replay,
  // each gated on its files_changed mirror event.
  const exportFiles = fixtureArtifactFiles(
    events,
    FIXTURE_RUN_ID,
    fixtureEventCreatedAt,
  );
  const written = events.some(
    (event) =>
      event.type === "tool_started" &&
      event.payload.tool === "Write" &&
      (event.payload.input as { file_path?: string } | undefined)?.file_path ===
        FIXTURE_WRITTEN_FILE_PATH,
  );
  if (!written) return exportFiles;
  const edited = events.some(
    (event) => event.type === "tool_started" && event.payload.tool === "Edit",
  );
  return [
    ...exportFiles,
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

export const FIXTURE_USER_PROMPT =
  "Which regions drove Q3 revenue growth compared to Q2?";

export const FIXTURE_TOTAL_MS = 24_800;

export function fixtureEventCreatedAt(at: number): string {
  return new Date(BASE_EPOCH + at).toISOString();
}

/** The frozen wall clock (epoch ms) at a replay offset — injected into the
 * chat UI context so relative timestamps stay honest on frozen frames. */
export function fixtureNowMs(at: number): number {
  return BASE_EPOCH + at;
}

/**
 * Literal contents of the fixture's mirrored files, by manifest id. The
 * harness turns these into object URLs so content-dependent UI (the image
 * card thumbnail) renders for real at /chats/test.
 */
export function fixtureFileContent(
  fileId: string,
): { body: string | Uint8Array<ArrayBuffer>; mime: string } | null {
  switch (fileId) {
    case "file-fixture-revenue-png":
      return { body: decodeBase64(REVENUE_PNG_BASE64), mime: "image/png" };
    case "file-fixture-revenue-csv":
      return { body: REVENUE_CSV_FILE, mime: "text/csv" };
    case "file-fixture-1":
      return { body: PYTHON_FILE, mime: "text/x-python" };
    case "file-fixture-report":
      return { body: REPORT_HTML_FILE, mime: "text/html" };
    case "file-fixture-chart":
      return { body: CHART_SVG_FILE, mime: "image/svg+xml" };
    case "file-fixture-csv":
      return { body: CSV_FILE, mime: "text/csv" };
    case "file-fixture-summary":
      return { body: SUMMARY_MD_FILE, mime: "text/markdown" };
    default:
      return null;
  }
}

/** Base64 to bytes without Buffer, so the harness works in the browser. */
function decodeBase64(value: string): Uint8Array<ArrayBuffer> {
  const binary = atob(value);
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

export function materializeFixtureEvents(
  upToMs: number,
  extra: FixtureEvent[] = [],
): StandaloneChatEvent[] {
  return [...fixtureEvents, ...extra]
    .filter((event) => event.at <= upToMs)
    .sort((a, b) => a.at - b.at)
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
