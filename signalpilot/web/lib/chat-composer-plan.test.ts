import { describe, expect, it } from "vitest";

import type { StandaloneChatEvent } from "~/lib/api";
import {
  composerPlanSummary,
  selectComposerPlan,
} from "~/lib/chat-composer-plan";

const at = "2026-01-01T00:00:00Z";

function todoWrite(
  runId: string,
  sequence: number,
  todos: { content: string; status: string; activeForm?: string }[],
  parent?: string,
): StandaloneChatEvent {
  return {
    run_id: runId,
    sequence,
    type: "tool_started",
    payload: {
      tool: "TodoWrite",
      tool_call_id: `call-${sequence}`,
      input: { todos },
      ...(parent ? { parent_tool_call_id: parent } : {}),
    },
    created_at: at,
  };
}

const events: StandaloneChatEvent[] = [
  todoWrite("run-1", 2, [
    { content: "Find the model", status: "in_progress", activeForm: "Finding the model" },
    { content: "Query it", status: "pending" },
  ]),
  // A subagent's TodoWrite never replaces the main plan.
  todoWrite("run-1", 3, [{ content: "Child task", status: "pending" }], "spawn-1"),
  todoWrite("run-1", 5, [
    { content: "Find the model", status: "completed" },
    { content: "Query it", status: "completed" },
  ]),
  todoWrite("run-2", 7, [{ content: "Second run step", status: "in_progress" }]),
];

describe("selectComposerPlan", () => {
  it("returns null without a current run", () => {
    expect(selectComposerPlan(events, null)).toBeNull();
    expect(selectComposerPlan(events, undefined)).toBeNull();
  });

  it("returns null when the run published no plan", () => {
    expect(
      selectComposerPlan(events, { id: "run-3", status: "running" }),
    ).toBeNull();
    expect(selectComposerPlan([], { id: "run-1", status: "running" })).toBeNull();
  });

  it("picks the latest main-run TodoWrite for the current run", () => {
    const selected = selectComposerPlan(events, {
      id: "run-1",
      status: "completed",
    });
    expect(selected?.runId).toBe("run-1");
    expect(selected?.running).toBe(false);
    expect(selected?.plan.sequence).toBe(5);
    expect(selected?.plan.completed).toBe(2);
    expect(selected?.plan.items.map((item) => item.content)).toEqual([
      "Find the model",
      "Query it",
    ]);
  });

  it("scopes the plan to the current run only", () => {
    const selected = selectComposerPlan(events, {
      id: "run-2",
      status: "running",
    });
    expect(selected?.running).toBe(true);
    expect(selected?.plan.items).toHaveLength(1);
    expect(selected?.plan.currentLabel).toBe("Second run step");
  });

  it("treats queued and running as streaming, terminal states as settled", () => {
    const run = (status: Parameters<typeof selectComposerPlan>[1]) => status;
    expect(
      selectComposerPlan(events, run({ id: "run-1", status: "queued" }))?.running,
    ).toBe(true);
    expect(
      selectComposerPlan(events, run({ id: "run-1", status: "failed" }))?.running,
    ).toBe(false);
    expect(
      selectComposerPlan(events, run({ id: "run-1", status: "cancelled" }))
        ?.running,
    ).toBe(false);
  });
});

describe("composerPlanSummary", () => {
  it("counts progress and marks a finished plan done", () => {
    const partial = selectComposerPlan(events, {
      id: "run-2",
      status: "running",
    })!.plan;
    expect(composerPlanSummary(partial)).toBe("0/1");
    const done = selectComposerPlan(events, {
      id: "run-1",
      status: "completed",
    })!.plan;
    expect(composerPlanSummary(done)).toBe("2/2 done");
  });
});
