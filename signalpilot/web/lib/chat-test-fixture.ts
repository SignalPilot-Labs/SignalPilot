import type {
  StandaloneChatArtifact,
  StandaloneChatEvent,
  StandaloneChatRunStatus,
} from "~/lib/api";

/**
 * Deterministic fixture for /chats/test: a scripted agent run replayed on a
 * timeline so the chat UX can be exercised without a live model or gateway.
 * `at` is the millisecond offset from replay start at which the event lands.
 */

export const FIXTURE_RUN_ID = "run-fixture-0001";
const BASE_EPOCH = Date.UTC(2026, 0, 15, 17, 30, 0);

export type FixtureEvent = Omit<StandaloneChatEvent, "created_at"> & {
  at: number;
};

export type FixtureArtifact = StandaloneChatArtifact & { at: number };

const PYTHON_FILE = `"""Q3 regional growth decomposition."""

import json
from pathlib import Path

REVENUE_SNAPSHOT = Path("snapshots/q3_revenue_by_region.json")


def growth(current: float, prior: float) -> float:
    if prior == 0:
        return 0.0
    return round((current - prior) / prior * 100, 1)


def main() -> None:
    rows = json.loads(REVENUE_SNAPSHOT.read_text())
    for row in rows:
        row["growth_pct"] = growth(row["revenue_q3"], row["revenue_q2"])
    ranked = sorted(rows, key=lambda row: row["growth_pct"], reverse=True)
    print(json.dumps(ranked[:3], indent=2))


if __name__ == "__main__":
    main()
`;

const SCRATCH_PYTHON = `q3 = {"EMEA": 4_812_400, "AMER": 9_204_100, "APAC": 2_118_800}
q2 = {"EMEA": 4_101_900, "AMER": 8_930_600, "APAC": 1_611_200}

result = {
    region: round((q3[region] - q2[region]) / q2[region] * 100, 1)
    for region in q3
}
`;

const BAD_SQL = `select region_name, sum(net_revenue) as revenue
from analytics.fct_orders
where order_quarter = '2025-Q3'
group by region_name`;

const GOOD_SQL = `select r.region, sum(o.net_revenue) as revenue_q3,
  sum(case when o.order_quarter = '2025-Q2' then o.net_revenue end) as revenue_q2
from analytics.fct_orders o
join analytics.dim_regions r on r.region_id = o.region_id
where o.order_quarter in ('2025-Q2', '2025-Q3')
group by r.region
order by revenue_q3 desc`;

const ANSWER_CHUNKS: { at: number; delta: string }[] = [
  { at: 18_100, delta: "**AMER led Q3 in absolute revenue, but EMEA drove the growth.**\n\n" },
  { at: 18_450, delta: "Across the three governed regions, Q3 revenue reached **$16.1M**, up " },
  { at: 18_800, delta: "**10.4%** quarter-over-quarter:\n\n" },
  { at: 19_150, delta: "- **EMEA** grew **17.3%** to $4.81M — the largest swing, concentrated in the enterprise tier\n" },
  { at: 19_500, delta: "- **APAC** grew **31.5%** to $2.12M from a smaller base, led by two new marketplace launches\n" },
  { at: 19_850, delta: "- **AMER** grew a steady **3.1%** to $9.20M and still contributes 57% of total revenue\n\n" },
  { at: 20_200, delta: "The published table has the full per-region breakdown, and the chart compares Q2 vs Q3 side by side. " },
  { at: 20_500, delta: "Growth percentages were computed in the sandboxed Python runtime from the exact query snapshot, so the numbers match the table to the cent." },
];

export const FIXTURE_USER_PROMPT =
  "Which regions drove Q3 revenue growth compared to Q2?";

/**
 * Streamed narration between the query chain and the notebook chain — the
 * agent reporting mid-run before starting its next tool chain, which the UI
 * renders as a natural split between two activity groups.
 */
const MID_RUN_CHUNKS: { at: number; delta: string }[] = [
  { at: 7_460, delta: "The governed query came back clean — **AMER leads in absolute revenue**, " },
  { at: 7_620, delta: "but the growth stories differ sharply by region.\n\n" },
  { at: 7_780, delta: "I'll spin up the analysis runtime to compute exact growth rates from the query snapshot, then publish a table and a Q2-vs-Q3 comparison chart." },
];

const RAW_EVENTS: FixtureEvent[] = [
  {
    at: 400,
    run_id: FIXTURE_RUN_ID,
    sequence: 1,
    type: "progress",
    payload: { label: "Reviewing the project context" },
  },
  {
    at: 900,
    run_id: FIXTURE_RUN_ID,
    sequence: 2,
    type: "tool_started",
    payload: {
      tool: "TodoWrite",
      input: {
        todos: [
          { content: "Confirm the revenue model and region join", status: "in_progress" },
          { content: "Query Q2 vs Q3 revenue by region", status: "pending" },
          { content: "Compute growth in the analysis runtime", status: "pending" },
          { content: "Publish a table and comparison chart", status: "pending" },
        ],
      },
    },
  },
  {
    at: 1_050,
    run_id: FIXTURE_RUN_ID,
    sequence: 3,
    type: "tool_completed",
    payload: { tool_call_id: "t1", summary: "The governed tool completed.", error: false },
  },
  {
    at: 1_500,
    run_id: FIXTURE_RUN_ID,
    sequence: 4,
    type: "tool_started",
    payload: {
      tool: "mcp__signalpilot__get_table_schema",
      input: { schema_name: "analytics", table_name: "fct_orders" },
    },
  },
  {
    at: 1_520,
    run_id: FIXTURE_RUN_ID,
    sequence: 5,
    type: "source",
    payload: {
      tool: "mcp__signalpilot__get_table_schema",
      schema_name: "analytics",
      table_name: "fct_orders",
    },
  },
  {
    at: 2_700,
    run_id: FIXTURE_RUN_ID,
    sequence: 6,
    type: "tool_completed",
    payload: { tool_call_id: "t2", summary: "The governed tool completed.", error: false },
  },
  {
    at: 3_200,
    run_id: FIXTURE_RUN_ID,
    sequence: 7,
    type: "tool_started",
    payload: {
      tool: "mcp__signalpilot__validate_sql",
      input: { sql: BAD_SQL },
    },
  },
  {
    at: 3_220,
    run_id: FIXTURE_RUN_ID,
    sequence: 8,
    type: "sql",
    payload: { sql: BAD_SQL },
  },
  {
    at: 4_100,
    run_id: FIXTURE_RUN_ID,
    sequence: 9,
    type: "tool_completed",
    payload: {
      tool_call_id: "t3",
      summary: "The governed tool returned an error.",
      error: true,
      message: 'column "region_name" does not exist on analytics.fct_orders — regions live on dim_regions',
    },
  },
  {
    at: 4_700,
    run_id: FIXTURE_RUN_ID,
    sequence: 10,
    type: "tool_started",
    payload: {
      tool: "mcp__signalpilot__query_database",
      input: { sql: GOOD_SQL },
    },
  },
  {
    at: 4_720,
    run_id: FIXTURE_RUN_ID,
    sequence: 11,
    type: "sql",
    payload: { sql: GOOD_SQL },
  },
  {
    at: 4_750,
    run_id: FIXTURE_RUN_ID,
    sequence: 12,
    type: "source",
    payload: {
      tool: "mcp__signalpilot__query_database",
      table_name: "dim_regions",
    },
  },
  {
    at: 7_400,
    run_id: FIXTURE_RUN_ID,
    sequence: 13,
    type: "tool_completed",
    payload: { tool_call_id: "t4", summary: "The governed tool completed.", error: false },
  },
  ...MID_RUN_CHUNKS.map((chunk) => ({
    at: chunk.at,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "text_delta" as const,
    payload: { delta: chunk.delta },
  })),
  {
    at: 7_900,
    run_id: FIXTURE_RUN_ID,
    sequence: 14,
    type: "tool_started",
    payload: {
      tool: "mcp__standalone-chat__start_analysis_notebook",
      input: { plan_id: "plan-8842" },
    },
  },
  {
    at: 8_700,
    run_id: FIXTURE_RUN_ID,
    sequence: 15,
    type: "tool_completed",
    payload: { tool_call_id: "t5", summary: "The governed tool completed.", error: false },
  },
  {
    at: 8_720,
    run_id: FIXTURE_RUN_ID,
    sequence: 16,
    type: "notebook_started",
    payload: { status: "running" },
  },
  {
    at: 9_200,
    run_id: FIXTURE_RUN_ID,
    sequence: 17,
    type: "tool_started",
    payload: {
      tool: "Write",
      input: { file_path: "analysis/q3_growth.py", content: PYTHON_FILE },
    },
  },
  {
    at: 10_500,
    run_id: FIXTURE_RUN_ID,
    sequence: 18,
    type: "tool_completed",
    payload: { tool_call_id: "t6", summary: "The governed tool completed.", error: false },
  },
  {
    at: 10_900,
    run_id: FIXTURE_RUN_ID,
    sequence: 19,
    type: "tool_started",
    payload: {
      tool: "Bash",
      input: { command: "python analysis/q3_growth.py --check" },
    },
  },
  {
    at: 11_900,
    run_id: FIXTURE_RUN_ID,
    sequence: 20,
    type: "tool_completed",
    payload: { tool_call_id: "t7", summary: "The governed tool completed.", error: false },
  },
  {
    at: 12_300,
    run_id: FIXTURE_RUN_ID,
    sequence: 21,
    type: "tool_started",
    payload: {
      tool: "mcp__standalone-chat__run_scratch_python",
      input: { source: SCRATCH_PYTHON },
    },
  },
  {
    at: 13_900,
    run_id: FIXTURE_RUN_ID,
    sequence: 22,
    type: "tool_completed",
    payload: { tool_call_id: "t8", summary: "The governed tool completed.", error: false },
  },
  {
    at: 14_300,
    run_id: FIXTURE_RUN_ID,
    sequence: 23,
    type: "tool_started",
    payload: {
      tool: "Edit",
      input: {
        file_path: "analysis/q3_growth.py",
        old_string: 'print(json.dumps(ranked[:3], indent=2))',
        new_string: 'print(json.dumps(ranked, indent=2))  # all regions, not top 3',
      },
    },
  },
  {
    at: 15_100,
    run_id: FIXTURE_RUN_ID,
    sequence: 24,
    type: "tool_completed",
    payload: { tool_call_id: "t9", summary: "The governed tool completed.", error: false },
  },
  {
    at: 15_500,
    run_id: FIXTURE_RUN_ID,
    sequence: 25,
    type: "tool_started",
    payload: {
      tool: "TodoWrite",
      input: {
        todos: [
          { content: "Confirm the revenue model and region join", status: "completed" },
          { content: "Query Q2 vs Q3 revenue by region", status: "completed" },
          { content: "Compute growth in the analysis runtime", status: "completed" },
          { content: "Publish a table and comparison chart", status: "in_progress" },
        ],
      },
    },
  },
  {
    at: 15_650,
    run_id: FIXTURE_RUN_ID,
    sequence: 26,
    type: "tool_completed",
    payload: { tool_call_id: "t10", summary: "The governed tool completed.", error: false },
  },
  {
    at: 16_000,
    run_id: FIXTURE_RUN_ID,
    sequence: 27,
    type: "tool_started",
    payload: {
      tool: "mcp__standalone-chat__publish_table",
      input: { filename: "q3_revenue_by_region.csv", result_id: "res-31" },
    },
  },
  {
    at: 16_700,
    run_id: FIXTURE_RUN_ID,
    sequence: 28,
    type: "tool_completed",
    payload: { tool_call_id: "t11", summary: "The governed tool completed.", error: false },
  },
  {
    at: 17_100,
    run_id: FIXTURE_RUN_ID,
    sequence: 29,
    type: "tool_started",
    payload: {
      tool: "mcp__standalone-chat__publish_chart",
      input: { filename: "q3_growth_by_region.vl.json", result_id: "res-31" },
    },
  },
  {
    at: 17_900,
    run_id: FIXTURE_RUN_ID,
    sequence: 30,
    type: "tool_completed",
    payload: { tool_call_id: "t12", summary: "The governed tool completed.", error: false },
  },
  ...ANSWER_CHUNKS.map((chunk, index) => ({
    at: chunk.at,
    run_id: FIXTURE_RUN_ID,
    sequence: 31 + index,
    type: "text_delta" as const,
    payload: { delta: chunk.delta },
  })),
  {
    at: 21_000,
    run_id: FIXTURE_RUN_ID,
    sequence: 31 + ANSWER_CHUNKS.length,
    type: "status",
    payload: { status: "completed" },
  },
];

/** Sequences are assigned from stream order so entries can be inserted freely. */
export const fixtureEvents: FixtureEvent[] = RAW_EVENTS.map(
  (event, index) => ({ ...event, sequence: index + 1 }),
);

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
