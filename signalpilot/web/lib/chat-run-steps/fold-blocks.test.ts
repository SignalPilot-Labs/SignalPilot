import { describe, expect, it } from "vitest";
import type { StandaloneChatEvent } from "~/lib/api";
import { foldRunBlocks, steeringAnchors } from "./fold-blocks";

const RUN = "run-1";
let clock = 0;
const ev = (sequence: number, type: string, payload: Record<string, unknown>): StandaloneChatEvent =>
  ({
    run_id: RUN,
    sequence,
    type,
    payload,
    created_at: `2026-09-22T10:00:${String(clock++ % 60).padStart(2, "0")}Z`,
  }) as StandaloneChatEvent;

const tool = (sequence: number, id: string): StandaloneChatEvent[] => [
  ev(sequence, "tool_started", { tool: "mcp__signalpilot__query_database", input: {}, tool_call_id: id }),
  ev(sequence + 1, "tool_completed", { tool_call_id: id, error: false }),
];

describe("interjection blocks", () => {
  it("places a follow-up where the agent read it, splitting the tool chain", () => {
    const events = [
      ...tool(1, "a"),
      ev(3, "steering_queued", { message_id: "s1" }),
      ev(4, "steering_picked_up", { message_id: "s1" }),
      ...tool(5, "b"),
      ev(7, "steering_delivered", { message_id: "s1" }),
      ...tool(8, "c"),
      ev(10, "text_delta", { delta: "Done." }),
    ];
    const blocks = foldRunBlocks(events, RUN);
    expect(blocks.map((block) => block.kind)).toEqual(["steps", "interjection", "steps", "text"]);
    const [first, , second] = blocks;
    expect(first.kind === "steps" && first.steps.length).toBe(2);
    expect(second.kind === "steps" && second.steps.length).toBe(1);
  });

  it("does not place a picked-up message on a live run until it is delivered", () => {
    const events = [...tool(1, "a"), ev(3, "steering_picked_up", { message_id: "s1" })];
    expect(steeringAnchors(events, RUN).size).toBe(0);
    expect(foldRunBlocks(events, RUN).some((block) => block.kind === "interjection")).toBe(false);
  });

  it("falls back to the pickup point for a finished run without delivery events", () => {
    const events = [
      ...tool(1, "a"),
      ev(3, "steering_picked_up", { message_id: "s1" }),
      ...tool(4, "b"),
      ev(6, "status", { status: "completed" }),
    ];
    expect([...steeringAnchors(events, RUN).entries()]).toEqual([[3, ["s1"]]]);
  });
});
