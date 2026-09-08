import { describe, expect, it } from "vitest";
import type {
  StandaloneChatEvent,
  StandaloneChatMessage,
  StandaloneChatRun,
} from "~/lib/api";
import { buildStandaloneUiMessages } from "./standalone-chat-ui-messages";

const user: StandaloneChatMessage = {
  id: "m1",
  role: "user",
  content: "What changed in revenue?",
  sequence: 1,
  created_at: 1,
  metadata: { surface: "standalone" },
};
const assistant: StandaloneChatMessage = {
  id: "m2",
  role: "assistant",
  content: "Revenue rose 12%.",
  sequence: 2,
  created_at: 2,
  metadata: { surface: "standalone", run_id: "run-1", status: "completed" },
};
const run = (status: StandaloneChatRun["status"]): StandaloneChatRun => ({
  id: "run-1",
  conversation_id: "c1",
  status,
  retry_of_run_id: null,
  public_error_code: null,
  public_error_message: null,
  cancellation_requested_at: null,
  created_at: "2026-09-08T00:00:00Z",
  started_at: null,
  terminal_at: null,
  last_event_sequence: 0,
});
const delta = (text: string, sequence: number): StandaloneChatEvent => ({
  run_id: "run-1",
  sequence,
  type: "text_delta",
  payload: { delta: text },
  created_at: "2026-09-08T00:00:01Z",
});

describe("buildStandaloneUiMessages", () => {
  it("returns finished history unchanged when there is no run to follow", () => {
    const messages = buildStandaloneUiMessages({
      detailMessages: [user, assistant],
      events: [delta("Revenue", 1)],
    });
    expect(messages).toEqual([user, assistant]);
    expect(messages.every((message) => !message.synthetic)).toBe(true);
  });

  it("adds no synthetic row once the run's terminal message is persisted", () => {
    const messages = buildStandaloneUiMessages({
      detailMessages: [user, assistant],
      currentRun: run("completed"),
      events: [],
    });
    expect(messages.map((message) => message.id)).toEqual(["m1", "m2"]);
  });

  it("streams the current run into a synthetic assistant row", () => {
    const messages = buildStandaloneUiMessages({
      detailMessages: [user],
      currentRun: run("running"),
      events: [delta("Revenue", 1), delta(" rose", 2)],
    });
    expect(messages).toHaveLength(2);
    const streamed = messages[1];
    expect(streamed.synthetic).toBe(true);
    expect(streamed.runId).toBe("run-1");
    expect(streamed.runStatus).toBe("running");
    expect(streamed.content).toBe("Revenue rose");
  });

  it("appends the optimistic submission and a queued placeholder", () => {
    const messages = buildStandaloneUiMessages({
      detailMessages: [user, assistant],
      currentRun: run("completed"),
      events: [],
      isSubmitting: true,
      pendingSubmission: { id: "p1", content: "And by region?", createdAt: 3 },
    });
    expect(messages.map((message) => message.id)).toEqual([
      "m1",
      "m2",
      "p1",
      "pending-assistant-p1",
    ]);
    expect(messages[3].runStatus).toBe("queued");
  });
});
