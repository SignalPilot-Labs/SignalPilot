import { describe, expect, it } from "vitest";
import type { StandaloneChatEvent } from "~/lib/api";
import { extractRunPlan } from "~/lib/chat-run-steps";
import {
  extractPlanFilePlan,
  isPlanFilePath,
  parsePlanMarkdown,
  replayPlanFile,
} from "./plan-file";

const PLAN_PATH = "/tmp/signalpilot-chat-runs/r1/artifacts/plan.md";
const FIRST_PLAN = [
  "# Plan: Q3 revenue by region",
  "- [ ] Load the dbt workflow",
  "- [ ] Query revenue by region",
  "- [ ] Chart the result",
].join("\n");

let sequence = 0;
function started(
  runId: string,
  tool: string,
  input: Record<string, unknown>,
  id = `t${sequence + 1}`,
): StandaloneChatEvent {
  sequence += 1;
  return {
    run_id: runId,
    sequence,
    type: "tool_started",
    payload: { tool, input, tool_call_id: id },
    created_at: "2026-09-22T00:00:00Z",
  } as unknown as StandaloneChatEvent;
}
function completed(runId: string, id: string, error: boolean): StandaloneChatEvent {
  sequence += 1;
  return {
    run_id: runId,
    sequence,
    type: "tool_completed",
    payload: { tool_call_id: id, error },
    created_at: "2026-09-22T00:00:00Z",
  } as unknown as StandaloneChatEvent;
}

describe("isPlanFilePath", () => {
  it("matches artifacts/plan.md in any path style", () => {
    expect(isPlanFilePath(PLAN_PATH)).toBe(true);
    expect(isPlanFilePath("artifacts/plan.md")).toBe(true);
    expect(isPlanFilePath(String.raw`C:\scratch\artifacts\plan.md`)).toBe(true);
    expect(isPlanFilePath("/tmp/plan.md")).toBe(false);
    expect(isPlanFilePath("/tmp/artifacts/sub/plan.md")).toBe(false);
    expect(isPlanFilePath(undefined)).toBe(false);
  });
});

describe("parsePlanMarkdown", () => {
  it("reads the heading and task list; the first open item is live", () => {
    const parsed = parsePlanMarkdown(
      "# Plan: Q3 revenue\n\n- [x] Load\n* [X] Scan\n- [ ] Query\n- [ ] Chart\nnotes",
    );
    expect(parsed.title).toBe("Q3 revenue");
    expect(parsed.items.map((item) => [item.content, item.status])).toEqual([
      ["Load", "completed"],
      ["Scan", "completed"],
      ["Query", "in_progress"],
      ["Chart", "pending"],
    ]);
  });
});

describe("replayPlanFile", () => {
  it("applies Write then Edit, and skips a failed edit", () => {
    sequence = 0;
    const events = [
      started("r1", "Write", { file_path: PLAN_PATH, content: FIRST_PLAN }),
      started(
        "r1",
        "Edit",
        {
          file_path: PLAN_PATH,
          old_string: "- [ ] Load the dbt workflow",
          new_string: "- [x] Load the dbt workflow",
        },
        "ok-edit",
      ),
      completed("r1", "ok-edit", false),
      started(
        "r1",
        "Edit",
        {
          file_path: PLAN_PATH,
          old_string: "- [ ] Chart the result",
          new_string: "- [x] Chart the result",
        },
        "bad-edit",
      ),
      completed("r1", "bad-edit", true),
    ];
    const plan = extractPlanFilePlan(events, "r1");
    expect(plan?.title).toBe("Q3 revenue by region");
    expect(plan?.completed).toBe(1);
    expect(plan?.currentLabel).toBe("Query revenue by region");
    expect(plan?.items[2].status).toBe("pending");
  });

  it("lets an edit-only follow-up run build on the previous run's file", () => {
    sequence = 0;
    const events = [
      started("r1", "Write", { file_path: PLAN_PATH, content: FIRST_PLAN }),
      started("r2", "MultiEdit", {
        file_path: PLAN_PATH,
        edits: [
          { old_string: "- [ ]", new_string: "- [x]", replace_all: true },
        ],
      }),
    ];
    expect(replayPlanFile(events, "r2")?.content).not.toContain("- [ ]");
    expect(extractPlanFilePlan(events, "r2")?.completed).toBe(3);
    // A run that never touched the plan file has no file plan.
    expect(extractPlanFilePlan(events, "r3")).toBeNull();
  });

  it("ignores other files and subagent writes", () => {
    sequence = 0;
    const events = [
      started("r1", "Write", { file_path: "/x/artifacts/notes.md", content: FIRST_PLAN }),
      {
        ...started("r1", "Write", { file_path: PLAN_PATH, content: FIRST_PLAN }),
        payload: {
          tool: "Write",
          input: { file_path: PLAN_PATH, content: FIRST_PLAN },
          parent_tool_call_id: "agent-1",
        },
      } as unknown as StandaloneChatEvent,
    ];
    expect(extractPlanFilePlan(events, "r1")).toBeNull();
  });
});

describe("extractRunPlan", () => {
  it("prefers whichever of TodoWrite and the plan file the run updated last", () => {
    sequence = 0;
    const todo = started("r1", "TodoWrite", {
      todos: [{ content: "Old todo", status: "in_progress" }],
    });
    const file = started("r1", "Write", { file_path: PLAN_PATH, content: FIRST_PLAN });
    expect(extractRunPlan([todo, file], "r1")?.items[0].content).toBe(
      "Load the dbt workflow",
    );
    const laterTodo = started("r1", "TodoWrite", {
      todos: [{ content: "Newer todo", status: "in_progress" }],
    });
    expect(extractRunPlan([todo, file, laterTodo], "r1")?.items[0].content).toBe(
      "Newer todo",
    );
  });
});
