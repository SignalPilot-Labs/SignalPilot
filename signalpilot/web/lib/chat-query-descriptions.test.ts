import { describe, expect, it } from "vitest";
import type { SqlTraceExecution, StandaloneChatEvent } from "~/lib/api";
import { describeQueryExecutions, normalizeSql } from "./chat-query-descriptions";

const RUN = "run-1";

function event(
  sequence: number,
  type: StandaloneChatEvent["type"],
  payload: Record<string, unknown>,
): StandaloneChatEvent {
  return { run_id: RUN, sequence, type, payload, created_at: "2026-09-03T00:00:00Z" };
}

function execution(id: string, sql: string | null): SqlTraceExecution {
  return {
    execution_id: id,
    run_id: RUN,
    connection_name: "warehouse",
    sql,
    sql_hash: `hash-${id}`,
    status: "completed",
    query_path: "governed",
    estimated_cost_usd: null,
    actual_cost_usd: null,
    actual_scan_bytes: null,
    execution_ms: 10,
    row_count: 1,
    completeness: "complete",
    public_error_code: null,
    created_at: "2026-09-03T00:00:00Z",
    started_at: null,
    terminal_at: null,
  };
}

describe("normalizeSql", () => {
  it("collapses whitespace, drops the trailing semicolon and lowercases", () => {
    expect(normalizeSql("SELECT  1\n  FROM t ;")).toBe("select 1 from t");
    expect(normalizeSql("   ")).toBeNull();
    expect(normalizeSql(null)).toBeNull();
  });
});

describe("describeQueryExecutions", () => {
  it("matches by SQL text when the result carries no execution id", () => {
    const events = [
      event(1, "tool_started", {
        tool: "mcp__signalpilot__query_database",
        tool_call_id: "c1",
        input: { sql: "select count(*) from orders", description: "Counting orders." },
      }),
    ];
    const map = describeQueryExecutions(events, [execution("e1", "SELECT COUNT(*)\nFROM orders;")]);
    expect(map.get("e1")).toBe("Counting orders");
  });

  it("prefers the execution id reported by the structured result", () => {
    const events = [
      event(1, "tool_started", {
        tool: "mcp__signalpilot__query_database",
        tool_call_id: "c1",
        input: { sql: "select 1", description: "First run" },
      }),
      event(2, "tool_completed", {
        tool_call_id: "c1",
        error: false,
        summary: "1 row",
        result: { kind: "table", execution_id: "e2" },
      }),
      event(3, "tool_started", {
        tool: "mcp__signalpilot__query_database",
        tool_call_id: "c2",
        input: { sql: "select 1", description: "Second run" },
      }),
    ];
    const map = describeQueryExecutions(events, [execution("e1", "select 1"), execution("e2", "select 1")]);
    expect(map.get("e2")).toBe("First run");
    expect(map.get("e1")).toBe("Second run");
  });

  it("uses each description once and skips queries without one", () => {
    const events = [
      event(1, "tool_started", {
        tool: "mcp__signalpilot__query_database",
        input: { sql: "select a" },
      }),
      event(2, "tool_started", {
        tool: "mcp__signalpilot__query_database",
        input: { sql: "select b", description: "Reading b" },
      }),
      event(3, "tool_started", { tool: "Bash", input: { command: "select b", description: "nope" } }),
    ];
    const map = describeQueryExecutions(events, [
      execution("e1", "select a"),
      execution("e2", "select b"),
      execution("e3", "select b"),
      execution("e4", null),
    ]);
    expect(map.has("e1")).toBe(false);
    expect(map.get("e2")).toBe("Reading b");
    expect(map.has("e3")).toBe(false);
    expect(map.has("e4")).toBe(false);
  });
});
