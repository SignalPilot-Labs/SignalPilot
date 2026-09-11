import { describe, expect, it } from "vitest";
import type {
  StandaloneChatEvent,
  StandaloneChatMessage,
  StandaloneChatRun,
} from "~/lib/api";
import {
  deriveChatTelemetry,
  estimateMessageTokens,
  formatTelemetryDuration,
  parseChatTokenUsage,
  totalChatTokens,
} from "~/lib/chat-telemetry";

const event = (
  sequence: number,
  type: StandaloneChatEvent["type"],
  second: number,
  payload: Record<string, unknown> = {},
): StandaloneChatEvent => ({
  run_id: "run-1",
  sequence,
  type,
  payload,
  created_at: `2026-09-03T12:00:${String(second).padStart(2, "0")}.000Z`,
});

const messages: StandaloneChatMessage[] = [
  {
    id: "user-1",
    role: "user",
    content: "Analyze this",
    sequence: 1,
    created_at: Date.parse("2026-09-03T12:00:00Z") / 1_000,
    metadata: {},
  },
  {
    id: "assistant-1",
    role: "assistant",
    content: "Done",
    sequence: 2,
    created_at: Date.parse("2026-09-03T12:00:10Z") / 1_000,
    metadata: { run_id: "run-1" },
  },
];

const run: StandaloneChatRun = {
  id: "run-1",
  conversation_id: "conversation-1",
  status: "completed",
  retry_of_run_id: null,
  public_error_code: null,
  public_error_message: null,
  cancellation_requested_at: null,
  created_at: "2026-09-03T12:00:00Z",
  started_at: "2026-09-03T12:00:01Z",
  terminal_at: "2026-09-03T12:00:10Z",
  last_event_sequence: 6,
  usage: {
    input_tokens: 100,
    output_tokens: 25,
    cache_creation_input_tokens: 50,
    cache_read_input_tokens: 400,
  },
};

describe("deriveChatTelemetry", () => {
  it("measures tool, text, response, and browser arrival pacing", () => {
    const events = [
      event(1, "status", 1),
      event(2, "tool_started", 2, { tool_call_id: "tool-1" }),
      event(3, "tool_completed", 5, { tool_call_id: "tool-1", error: false }),
      event(4, "text_delta", 6, { delta: "hello" }),
      event(5, "text_delta", 8, { delta: " world" }),
      event(6, "status", 10),
    ];
    const metrics = deriveChatTelemetry(
      messages,
      events,
      run,
      [
        { runId: "run-1", sequence: 4, type: "text_delta", receivedAt: 1_000 },
        { runId: "run-1", sequence: 5, type: "text_delta", receivedAt: 1_400 },
      ],
      Date.parse("2026-09-03T12:00:20Z"),
    );

    expect(metrics.currentRunMs).toBe(9_000);
    expect(metrics.messageCount).toBe(2);
    expect(metrics.averageAssistantResponseMs).toBe(10_000);
    expect(metrics.toolCallCount).toBe(1);
    expect(metrics.averageToolDurationMs).toBe(3_000);
    expect(metrics.averageToolToTextMs).toBe(1_000);
    expect(metrics.textChunkCount).toBe(2);
    expect(metrics.averageChunkGapMs).toBe(2_000);
    expect(metrics.averageBrowserArrivalGapMs).toBe(400);
    expect(metrics.firstTextMs).toBe(5_000);
    expect(metrics.totalTokens).toBe(575);
    expect(metrics.inputTokens).toBe(100);
    expect(metrics.outputTokens).toBe(25);
    expect(metrics.runsWithUsage).toBe(1);
  });

  it("does not count synthetic optimistic transcript rows", () => {
    const metrics = deriveChatTelemetry(
      [
        ...messages,
        { ...messages[1], id: "synthetic", metadata: { optimistic: true } },
      ],
      [],
      null,
      [],
      Date.now(),
    );
    expect(metrics.messageCount).toBe(2);
    expect(metrics.assistantMessageCount).toBe(1);
  });
});

describe("chat token helpers", () => {
  it("normalizes exact SDK usage and totals cache tokens", () => {
    const usage = parseChatTokenUsage({
      input_tokens: 10,
      output_tokens: 5,
      cache_creation_input_tokens: 20,
      cache_read_input_tokens: 100,
      ignored: "provider metadata",
    });
    expect(usage).toEqual({
      input_tokens: 10,
      output_tokens: 5,
      cache_creation_input_tokens: 20,
      cache_read_input_tokens: 100,
    });
    expect(totalChatTokens(usage)).toBe(135);
  });

  it("marks visible message tokenization as an estimate", () => {
    expect(estimateMessageTokens("12345678")).toBe(2);
    expect(estimateMessageTokens("")).toBe(0);
  });
});

describe("formatTelemetryDuration", () => {
  it("uses readable units for subsecond, second, and minute values", () => {
    expect(formatTelemetryDuration(250)).toBe("250 ms");
    expect(formatTelemetryDuration(1_250)).toBe("1.3 s");
    expect(formatTelemetryDuration(125_000)).toBe("2m 05s");
  });
});
