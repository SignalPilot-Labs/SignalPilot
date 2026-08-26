import { describe, expect, it } from "vitest";
import {
  foldRunBlocks,
  foldRunSteps,
  formatStepDuration,
  normalizeToolName,
  summarizeRunSteps,
} from "~/lib/chat-run-steps";
import {
  FIXTURE_RUN_ID,
  FIXTURE_TOTAL_MS,
  materializeFixtureEvents,
} from "~/lib/chat-test-fixture";

const allEvents = materializeFixtureEvents(FIXTURE_TOTAL_MS);

describe("normalizeToolName", () => {
  it("strips MCP prefixes and classifies the origin", () => {
    expect(normalizeToolName("mcp__signalpilot__query_database")).toEqual({
      tool: "query_database",
      origin: "signalpilot",
    });
    expect(
      normalizeToolName("mcp__standalone-chat__run_scratch_python"),
    ).toEqual({ tool: "run_scratch_python", origin: "chat" });
    expect(normalizeToolName("mcp__signalpilot-notebook__run_cells")).toEqual({
      tool: "run_cells",
      origin: "notebook",
    });
    expect(normalizeToolName("Bash")).toEqual({
      tool: "Bash",
      origin: "claude-code",
    });
  });
});

describe("foldRunSteps", () => {
  const steps = foldRunSteps(allEvents, FIXTURE_RUN_ID);

  it("pairs tool starts with completions in order", () => {
    expect(steps.every((step) => step.status !== "running")).toBe(true);
    const validate = steps.find((step) => step.tool === "validate_sql");
    expect(validate?.status).toBe("failed");
    expect(validate?.sql).toContain("region_name");
    expect(validate?.detail).toContain("does not exist");
    const query = steps.find((step) => step.tool === "query_database");
    expect(query?.status).toBe("succeeded");
    expect(query?.durationMs).toBeGreaterThan(2_000);
  });

  it("extracts code and file paths from base Claude Code tools", () => {
    const write = steps.find((step) => step.tool === "Write");
    expect(write?.category).toBe("file-write");
    expect(write?.file).toBe("analysis/q3_growth.py");
    expect(write?.code).toContain("def growth");
    const bash = steps.find((step) => step.tool === "Bash");
    expect(bash?.category).toBe("terminal");
    expect(bash?.code).toContain("python analysis/q3_growth.py");
    const edit = steps.find((step) => step.tool === "Edit");
    expect(edit?.category).toBe("file-edit");
    expect(edit?.input?.new_string).toContain("all regions");
  });

  it("extracts python source from the scratch runtime tool", () => {
    const scratch = steps.find((step) => step.tool === "run_scratch_python");
    expect(scratch?.category).toBe("python");
    expect(scratch?.code).toContain("round((q3[region]");
  });

  it("attaches source chips to schema tools", () => {
    const schema = steps.find((step) => step.tool === "get_table_schema");
    expect(schema?.category).toBe("source");
    expect(schema?.sources).toEqual(
      expect.arrayContaining(["analytics", "fct_orders"]),
    );
  });

  it("ignores events from other runs", () => {
    expect(foldRunSteps(allEvents, "other-run")).toEqual([]);
  });

  it("leaves an unmatched tool start running", () => {
    const partial = foldRunSteps(
      materializeFixtureEvents(5_000),
      FIXTURE_RUN_ID,
    );
    const last = partial[partial.length - 1];
    expect(last.tool).toBe("query_database");
    expect(last.status).toBe("running");
  });
});

describe("plan and route step enrichment", () => {
  const base = { run_id: "run-p", created_at: "2026-01-01T00:00:00Z" } as const;
  const steps = foldRunSteps(
    [
      {
        ...base,
        sequence: 1,
        type: "plan_created",
        payload: {
          plan_id: "p1",
          purpose: "Rank accounts by revenue",
          sql: "select 1",
          estimated_output_rows: 120,
        },
      },
      {
        ...base,
        sequence: 2,
        type: "route_selected",
        payload: {
          plan_id: "p1",
          route: "aggregate_required",
          route_reason: "The projected output exceeds the direct-query row budget.",
        },
      },
    ],
    "run-p",
  );

  it("surfaces the plan purpose, SQL, and row estimate", () => {
    expect(steps[0].title).toBe("Planned a governed query (~120 rows)");
    expect(steps[0].detail).toBe("Rank accounts by revenue");
    expect(steps[0].sql).toBe("select 1");
  });

  it("explains the chosen route with its reason", () => {
    expect(steps[1].title).toContain("needs a bounded aggregate");
    expect(steps[1].detail).toContain("row budget");
  });
});

describe("foldRunBlocks", () => {
  it("splits the run into tool chains separated by streamed narration", () => {
    const blocks = foldRunBlocks(allEvents, FIXTURE_RUN_ID);
    expect(blocks.map((block) => block.kind)).toEqual([
      "steps",
      "text",
      "steps",
      "text",
    ]);
    const [chain1, narration, chain2, answer] = blocks;
    if (chain1.kind !== "steps" || chain2.kind !== "steps") throw new Error();
    if (narration.kind !== "text" || answer.kind !== "text") throw new Error();
    expect(chain1.steps).toHaveLength(5); // progress → todo → schema → validate → query
    expect(chain1.steps.at(-1)?.tool).toBe("query_database");
    expect(narration.text).toContain("analysis runtime");
    expect(chain2.steps).toHaveLength(8); // notebook → write → bash → python → todo → edit → 2 publishes
    expect(chain2.steps[0]?.tool).toBe("start_analysis_notebook");
    expect(answer.text).toContain("EMEA drove the growth");
  });

  it("keeps a mid-stream narration attached to no group while the next chain runs", () => {
    const blocks = foldRunBlocks(
      materializeFixtureEvents(9_500),
      FIXTURE_RUN_ID,
    );
    expect(blocks.map((block) => block.kind)).toEqual([
      "steps",
      "text",
      "steps",
    ]);
    const tail = blocks[2];
    if (tail.kind !== "steps") throw new Error();
    expect(tail.steps.some((step) => step.status === "running")).toBe(true);
  });
});

describe("summarizeRunSteps", () => {
  it("counts queries, code runs, files and errors", () => {
    const summary = summarizeRunSteps(foldRunSteps(allEvents, FIXTURE_RUN_ID));
    expect(summary.queries).toBe(2); // validate_sql + query_database
    expect(summary.codeRuns).toBe(2); // Bash + run_scratch_python
    expect(summary.files).toBe(4); // Write + Edit + publish_table + publish_chart
    expect(summary.errors).toBe(1);
    expect(summary.running).toBe(false);
  });
});

describe("formatStepDuration", () => {
  it("formats sub-second, second and minute scales", () => {
    expect(formatStepDuration(null)).toBeNull();
    expect(formatStepDuration(40)).toBe("<0.1s");
    expect(formatStepDuration(2_600)).toBe("2.6s");
    expect(formatStepDuration(94_000)).toBe("1m 34s");
  });
});
