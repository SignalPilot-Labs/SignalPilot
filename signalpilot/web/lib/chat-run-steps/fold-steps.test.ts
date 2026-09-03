import { describe, expect, it } from "vitest";
import type { StandaloneChatEvent } from "~/lib/api";
import { foldRunSteps } from "~/lib/chat-run-steps";

const RUN = "run-results";

function started(
  sequence: number,
  tool: string,
  extra: Record<string, unknown> = {},
): StandaloneChatEvent {
  return {
    run_id: RUN,
    sequence,
    type: "tool_started",
    payload: { tool, input: {}, ...extra },
    created_at: `2026-09-01T10:00:${String(sequence).padStart(2, "0")}Z`,
  };
}

function completed(
  sequence: number,
  payload: Record<string, unknown>,
): StandaloneChatEvent {
  return {
    run_id: RUN,
    sequence,
    type: "tool_completed",
    payload: { error: false, ...payload },
    created_at: `2026-09-01T10:00:${String(sequence).padStart(2, "0")}Z`,
  };
}

const tableResult = (rows: number) => ({
  kind: "table",
  columns: [{ name: "n" }],
  rows: Array.from({ length: rows }, (_, i) => [i]),
  preview_row_count: rows,
  row_count: rows,
  preview_truncated: false,
  columns_truncated: false,
  result_id: null,
  completeness: "complete",
  source: "parsed",
});

describe("foldRunSteps tool results", () => {
  it("attaches the parsed result to the step with the matching tool_call_id", () => {
    const steps = foldRunSteps(
      [
        started(1, "mcp__signalpilot__query_database", { tool_call_id: "a" }),
        completed(2, {
          tool_call_id: "a",
          summary: "3 rows · 12 ms",
          result: tableResult(3),
          result_text: "n\n0\n1\n2",
        }),
      ],
      RUN,
    );
    expect(steps).toHaveLength(1);
    expect(steps[0].status).toBe("succeeded");
    expect(steps[0].result?.kind).toBe("table");
    expect(steps[0].result?.summary).toBe("3 rows · 12 ms");
    expect(steps[0].result?.resultText).toBe("n\n0\n1\n2");
    expect(steps[0].detail).toBe("3 rows · 12 ms");
  });

  it("pairs out-of-order completions by id, each with its own result", () => {
    const steps = foldRunSteps(
      [
        started(1, "mcp__signalpilot__query_database", { tool_call_id: "slow" }),
        started(2, "mcp__signalpilot__list_tables", { tool_call_id: "fast" }),
        completed(3, {
          tool_call_id: "fast",
          summary: "Discovered 2 tables",
          result: { kind: "table_list", total: 2, entries: [], entries_truncated: false },
        }),
        completed(4, {
          tool_call_id: "slow",
          summary: "10 rows · 90 ms",
          result: tableResult(10),
        }),
      ],
      RUN,
    );
    expect(steps.map((step) => step.tool)).toEqual(["query_database", "list_tables"]);
    expect(steps[0].result).toMatchObject({ kind: "table", rowCount: 10 });
    expect(steps[0].detail).toBe("10 rows · 90 ms");
    expect(steps[1].result).toMatchObject({ kind: "table_list", total: 2 });
    expect(steps[1].detail).toBe("Discovered 2 tables");
    expect(steps[1].endedAt).toBe("2026-09-01T10:00:03Z");
  });

  it("falls back to FIFO pairing when no tool_call_id is present", () => {
    const steps = foldRunSteps(
      [
        started(1, "Bash"),
        started(2, "Read"),
        completed(3, {
          summary: "ls · exit 0",
          result: { kind: "terminal", exit_code: 0, stdout: "a\nb", stderr: "", stdout_truncated: false, stderr_truncated: false },
        }),
        completed(4, { summary: "The tool completed." }),
      ],
      RUN,
    );
    expect(steps[0].tool).toBe("Bash");
    expect(steps[0].result).toMatchObject({ kind: "terminal", stdout: "a\nb" });
    expect(steps[0].detail).toBe("ls · exit 0");
    expect(steps[1].tool).toBe("Read");
    expect(steps[1].result).toMatchObject({ kind: "legacy", summary: null });
    expect(steps[1].detail).toBeNull();
  });

  it("attaches results to subagent children and the spawn itself", () => {
    const steps = foldRunSteps(
      [
        started(1, "Agent", {
          tool_call_id: "sub",
          input: { subagent_type: "Explore", description: "Scan the marts" },
        }),
        started(2, "Grep", { tool_call_id: "sub-c1", parent_tool_call_id: "sub", input: { pattern: "x" } }),
        completed(3, {
          tool_call_id: "sub-c1",
          parent_tool_call_id: "sub",
          summary: "4 matches",
          result_text: "a.sql\nb.sql\nc.sql\nd.sql",
        }),
        completed(4, { tool_call_id: "sub", summary: "The tool completed.", report: "Done." }),
      ],
      RUN,
    );
    expect(steps).toHaveLength(1);
    const spawn = steps[0];
    expect(spawn.category).toBe("subagent");
    expect(spawn.report).toBe("Done.");
    expect(spawn.result?.kind).toBe("legacy");
    expect(spawn.detail).toBeNull();
    expect(spawn.children).toHaveLength(1);
    expect(spawn.children[0].result).toMatchObject({ kind: "text", summary: "4 matches" });
    expect(spawn.children[0].detail).toBe("4 matches");
    expect(spawn.children[0].status).toBe("succeeded");
  });

  it("keeps the failure detail path and still parses the result kind", () => {
    const steps = foldRunSteps(
      [
        started(1, "mcp__signalpilot__validate_sql", { tool_call_id: "v" }),
        completed(2, {
          tool_call_id: "v",
          error: true,
          summary: "The governed tool returned an error.",
          result: { kind: "validation", valid: false, message: "bad column" },
        }),
        started(3, "mcp__hubspot__list_deals", { tool_call_id: "h" }),
        completed(4, {
          tool_call_id: "h",
          error: true,
          summary: "HubSpot needs you to sign in before this tool can run.",
        }),
      ],
      RUN,
    );
    expect(steps[0].status).toBe("failed");
    expect(steps[0].detail).toBe("The tool returned an error.");
    expect(steps[0].result).toMatchObject({ kind: "validation", valid: false, message: "bad column", summary: null });
    expect(steps[1].title).toContain("needs sign-in");
    expect(steps[1].detail).toBeNull();
    expect(steps[1].result).toMatchObject({ kind: "legacy" });
  });

  it("clears the agent-facing error text from a connector sign-in failure", () => {
    const steps = foldRunSteps(
      [
        started(1, "mcp__hubspot__list_deals", { tool_call_id: "h" }),
        completed(2, {
          tool_call_id: "h",
          error: true,
          summary: "HubSpot needs you to sign in before this tool can run.",
        }),
        started(3, "mcp__signalpilot__validate_sql", { tool_call_id: "v" }),
        completed(4, { tool_call_id: "v", error: true, summary: "bad column" }),
      ],
      RUN,
    );
    // The card's error banner reads `result.errorMessage`; neither it nor
    // `detail` may carry the sign-in sentence.
    expect(steps[0].status).toBe("failed");
    expect(steps[0].detail).toBeNull();
    expect(steps[0].result).toMatchObject({ kind: "legacy", summary: null, errorMessage: null });
    expect(JSON.stringify(steps[0])).not.toMatch(/needs you to sign in/);
    // Ordinary failures keep their error text.
    expect(steps[1].result?.errorMessage).toBe("bad column");
    expect(steps[1].detail).toBe("bad column");
  });

  it("leaves a still-running step without a result", () => {
    const steps = foldRunSteps([started(1, "Bash", { tool_call_id: "open" })], RUN);
    expect(steps[0].status).toBe("running");
    expect(steps[0].result).toBeNull();
  });
});

describe("query_database description titles", () => {
  it("uses the agent's one-sentence description as the step title", () => {
    const [step] = foldRunSteps(
      [
        started(1, "mcp__signalpilot__query_database", {
          input: {
            sql: "select 1",
            description: "Checking the date range of the rpt_daily_profitability mart.",
          },
        }),
      ],
      RUN,
    );
    expect(step.title).toBe(
      "Checking the date range of the rpt_daily_profitability mart",
    );
  });

  it("falls back to the humanized tool name without a description", () => {
    const [step] = foldRunSteps(
      [started(1, "mcp__signalpilot__query_database", { input: { sql: "select 1" } })],
      RUN,
    );
    expect(step.title).toBe("Queried the warehouse");
    const [blank] = foldRunSteps(
      [started(2, "mcp__signalpilot__query_database", { input: { sql: "x", description: "   " } })],
      RUN,
    );
    expect(blank.title).toBe("Queried the warehouse");
  });

  it("collapses whitespace and truncates long descriptions", () => {
    const long = `Counting ${"orders ".repeat(40)}per region`;
    const [step] = foldRunSteps(
      [
        started(1, "mcp__signalpilot__query_database", {
          input: { sql: "x", description: `  Checking

 the   mart  ` },
        }),
        started(2, "mcp__signalpilot__query_database", { input: { sql: "x", description: long } }),
      ],
      RUN,
    );
    expect(step.title).toBe("Checking the mart");
    const [longStep] = foldRunSteps(
      [started(2, "mcp__signalpilot__query_database", { input: { sql: "x", description: long } })],
      RUN,
    );
    expect(longStep.title.length).toBe(140);
    expect(longStep.title.endsWith("…")).toBe(true);
  });
});
