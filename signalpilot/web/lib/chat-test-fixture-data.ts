import type { StandaloneChatEvent } from "~/lib/api";

/**
 * Raw fixture data for /chats/test: the scripted event timeline and the
 * literal payloads it carries. Import this through lib/chat-test-fixture.ts.
 * `at` is the millisecond offset from replay start at which the event lands.
 */

export const FIXTURE_RUN_ID = "run-fixture-0001";

// Live notebook panel wiring: the ids the enriched notebook_started event
// carries so the chat page can attach the notebook inner view.
export const FIXTURE_GATEWAY_SESSION_ID = "gw-session-fixture-1";
export const FIXTURE_KERNEL_SESSION_ID = "s_fixt01";
export const FIXTURE_NOTEBOOK_PATH =
  "/tmp/signalpilot-chat-runs/run-fixture-0001/analysis.py";

// Artifacts panel wiring: the file the fixture agent writes and the
// tool_call_id whose completion marks the governed query as executed.
export const FIXTURE_WRITTEN_FILE_PATH = "analysis/q3_growth.py";
export const FIXTURE_QUERY_TOOL_CALL_ID = "t4";

export type FixtureEvent = Omit<StandaloneChatEvent, "created_at"> & {
  at: number;
};

export const PYTHON_FILE = `"""Q3 regional growth decomposition."""

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

/** Extended-thinking stretch before the first tool chain. */
const THINKING_CHUNKS: { at: number; delta: string }[] = [
  { at: 240, delta: "The user wants Q3 vs Q2 revenue growth by region. " },
  { at: 300, delta: "I should confirm which model carries net revenue first — fct_orders looks right, but regions may live on a dimension table. " },
  { at: 360, delta: "Plan: check the schema, query both quarters in one governed pass, then compute growth rates in the sandbox so the numbers match the published table exactly." },
];

const RAW_EVENTS: FixtureEvent[] = [
  // Cold-start boot: present in this fixture so the boot UX is replayable.
  // Warm runs simply have no runtime_boot events.
  {
    at: 40,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "runtime_boot",
    payload: { phase: "provisioning" },
  },
  {
    at: 180,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "runtime_boot",
    payload: { phase: "ready", boot_ms: 41_200 },
  },
  ...THINKING_CHUNKS.map((chunk) => ({
    at: chunk.at,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "thinking_delta" as const,
    payload: { delta: chunk.delta },
  })),
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
    payload: { tool_call_id: "t1", summary: "The tool completed.", error: false },
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
    payload: { tool_call_id: "t2", summary: "The tool completed.", error: false },
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
      // The worker writes the failure text as `summary` (chat-run-steps reads
      // summary first, message only as a legacy fallback).
      summary:
        'column "region_name" does not exist on analytics.fct_orders — regions live on dim_regions',
      error: true,
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
  // A subagent explores the dbt project in parallel with the warehouse query.
  {
    at: 4_900,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "tool_started",
    payload: {
      tool: "Agent",
      tool_call_id: "sub-1",
      input: {
        subagent_type: "Explore",
        description: "Map the revenue marts and their grain",
        prompt: "Find every mart that touches net_revenue and report its grain.",
      },
    },
  },
  {
    at: 5_100,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "tool_started",
    payload: {
      tool: "Glob",
      tool_call_id: "sub-1-c1",
      parent_tool_call_id: "sub-1",
      input: { pattern: "models/marts/**/*.sql" },
    },
  },
  {
    at: 5_400,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "tool_completed",
    payload: { tool_call_id: "sub-1-c1", parent_tool_call_id: "sub-1", summary: "The tool completed.", error: false },
  },
  {
    at: 5_600,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "text_delta",
    payload: {
      delta: "Three marts reference net_revenue; checking each one's grain.",
      parent_tool_call_id: "sub-1",
    },
  },
  {
    at: 5_800,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "tool_started",
    payload: {
      tool: "Read",
      tool_call_id: "sub-1-c2",
      parent_tool_call_id: "sub-1",
      input: { file_path: "models/marts/fct_orders.sql" },
    },
  },
  {
    at: 6_300,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "tool_completed",
    payload: { tool_call_id: "sub-1-c2", parent_tool_call_id: "sub-1", summary: "The tool completed.", error: false },
  },
  {
    at: 6_500,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "tool_started",
    payload: {
      tool: "Grep",
      tool_call_id: "sub-1-c3",
      parent_tool_call_id: "sub-1",
      input: { pattern: "net_revenue", path: "models/" },
    },
  },
  {
    at: 6_900,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "tool_completed",
    payload: { tool_call_id: "sub-1-c3", parent_tool_call_id: "sub-1", summary: "The tool completed.", error: false },
  },
  {
    at: 7_350,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "tool_completed",
    payload: {
      tool_call_id: "sub-1",
      summary: "The tool completed.",
      error: false,
      report:
        "**Three marts touch `net_revenue`.** `fct_orders` is order-grain and joins regions via `region_id`; `rpt_daily_revenue` and `rpt_region_rollup` both aggregate from it, so the Q2/Q3 comparison should read from `fct_orders` directly.",
    },
  },
  {
    at: 7_400,
    run_id: FIXTURE_RUN_ID,
    sequence: 13,
    type: "tool_completed",
    payload: { tool_call_id: "t4", summary: "The tool completed.", error: false },
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
    payload: { tool_call_id: "t5", summary: "The tool completed.", error: false },
  },
  {
    at: 8_720,
    run_id: FIXTURE_RUN_ID,
    sequence: 16,
    type: "notebook_started",
    payload: {
      status: "running",
      gateway_session_id: FIXTURE_GATEWAY_SESSION_ID,
      kernel_session_id: FIXTURE_KERNEL_SESSION_ID,
      notebook_path: FIXTURE_NOTEBOOK_PATH,
    },
  },
  {
    at: 9_200,
    run_id: FIXTURE_RUN_ID,
    sequence: 17,
    type: "tool_started",
    payload: {
      tool: "Write",
      input: { file_path: FIXTURE_WRITTEN_FILE_PATH, content: PYTHON_FILE },
    },
  },
  {
    at: 10_500,
    run_id: FIXTURE_RUN_ID,
    sequence: 18,
    type: "tool_completed",
    payload: { tool_call_id: "t6", summary: "The tool completed.", error: false },
  },
  // The gateway mirrors the Write to the conversation file store and
  // announces it. Content-free: the client only refetches the manifest.
  {
    at: 10_520,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "files_changed",
    payload: { changed: [FIXTURE_WRITTEN_FILE_PATH], deleted: [] },
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
    payload: { tool_call_id: "t7", summary: "The tool completed.", error: false },
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
    payload: { tool_call_id: "t9", summary: "The tool completed.", error: false },
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
    payload: { tool_call_id: "t10", summary: "The tool completed.", error: false },
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
    payload: { tool_call_id: "t11", summary: "The tool completed.", error: false },
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
    payload: { tool_call_id: "t12", summary: "The tool completed.", error: false },
  },
  ...ANSWER_CHUNKS.map((chunk, index) => ({
    at: chunk.at,
    run_id: FIXTURE_RUN_ID,
    sequence: 31 + index,
    type: "text_delta" as const,
    payload: { delta: chunk.delta },
  })),
  {
    at: 20_800,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "archive_completed",
    payload: { archive_id: "archive-fixture-1" },
  },
  {
    at: 20_900,
    run_id: FIXTURE_RUN_ID,
    sequence: 0,
    type: "kernel_stopped",
    payload: { status: "stopped" },
  },
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
