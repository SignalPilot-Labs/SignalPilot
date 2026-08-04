import { describe, expect, it } from "vitest";

import {
  appendOptimisticUserMessage,
  applyStandaloneChatEvent,
  assembleStandaloneRunText,
  containsStandaloneSubmission,
  isStandaloneRunReconciled,
  standaloneMessageKey,
  upsertStandaloneConversation,
} from "~/lib/standalone-chat-state";
import type { StandaloneConversationDetail } from "~/lib/api";

function detailFixture(): StandaloneConversationDetail {
  return {
    conversation: {
      id: "conversation-1",
      project_id: "project-1",
      project_name: "Revenue",
      branch: "main",
      title: "Revenue question",
      status: "active",
      created_at: 100,
      updated_at: 100,
      run_status: null,
      commit_sha: "abc123",
      per_query_budget_usd: 0.25,
      chat_budget_usd: 1,
      estimated_spend_usd: 0,
      actual_spend_usd: 0,
      reserved_spend_usd: 0,
    },
    messages: [],
    artifacts: [],
    current_run: null,
    run_events: [],
  };
}

describe("standalone chat state", () => {
  it("separates assistant text blocks divided by tool activity", () => {
    const event = (
      sequence: number,
      type: StandaloneConversationDetail["run_events"][number]["type"],
      payload: Record<string, unknown>,
    ): StandaloneConversationDetail["run_events"][number] => ({
      run_id: "run-1",
      sequence,
      type,
      payload,
      created_at: `2026-07-31T12:00:${String(sequence).padStart(2, "0")}Z`,
    });
    const events = [
      event(1, "text_delta", { delta: "underlying data." }),
      event(2, "tool_started", { tool: "inspect_dbt" }),
      event(3, "tool_completed", { tool: "inspect_dbt" }),
      event(4, "text_delta", { delta: "Perfect! I can" }),
      event(5, "text_delta", { delta: " see it." }),
    ];

    expect(assembleStandaloneRunText(events, "run-1")).toBe(
      "underlying data.\n\nPerfect! I can see it.",
    );
  });

  it("preserves whitespace between ordinary token chunks", () => {
    const events: StandaloneConversationDetail["run_events"] = [
      {
        run_id: "run-1",
        sequence: 1,
        type: "text_delta",
        payload: { delta: "and the" },
        created_at: "2026-07-31T12:00:01Z",
      },
      {
        run_id: "run-1",
        sequence: 2,
        type: "text_delta",
        payload: { delta: " underlying data." },
        created_at: "2026-07-31T12:00:02Z",
      },
    ];

    expect(assembleStandaloneRunText(events, "run-1")).toBe(
      "and the underlying data.",
    );
  });

  it("makes a submitted user message visible before the run request completes", () => {
    const updated = appendOptimisticUserMessage(detailFixture(), {
      id: "optimistic-1",
      content: "show me revenue",
      createdAt: 123,
    });

    expect(updated.messages).toContainEqual({
      id: "optimistic-1",
      role: "user",
      content: "show me revenue",
      sequence: 1,
      created_at: 123,
      metadata: { optimistic: true },
    });
  });

  it("recognizes the durable replacement for a pending new-chat message", () => {
    const submission = {
      id: "optimistic-1",
      content: "show me revenue",
      createdAt: 123,
    };
    expect(
      containsStandaloneSubmission(
        [
          {
            id: "durable-1",
            role: "user",
            content: submission.content,
            sequence: 1,
            created_at: 124,
            metadata: { surface: "standalone" },
          },
        ],
        submission,
      ),
    ).toBe(true);
  });

  it("keeps streamed events in conversation state and applies terminal status immediately", () => {
    const detail = detailFixture();
    detail.current_run = {
      id: "run-1",
      conversation_id: detail.conversation.id,
      status: "running",
      retry_of_run_id: null,
      public_error_code: null,
      public_error_message: null,
      cancellation_requested_at: null,
      created_at: "2026-07-31T12:00:00Z",
      started_at: "2026-07-31T12:00:01Z",
      terminal_at: null,
      last_event_sequence: 3,
    };

    const updated = applyStandaloneChatEvent(detail, {
      run_id: "run-1",
      sequence: 4,
      type: "status",
      payload: { status: "completed" },
      created_at: "2026-07-31T12:00:04Z",
    });

    expect(updated.run_events).toHaveLength(1);
    expect(updated.current_run).toMatchObject({
      status: "completed",
      last_event_sequence: 4,
    });
    expect(updated.conversation.run_status).toBe("completed");
  });

  it("puts a newly created conversation in history without waiting for a refetch", () => {
    const created = detailFixture().conversation;
    const history = upsertStandaloneConversation(
      [{ ...created, id: "older", updated_at: 50 }],
      { ...created, id: "new", updated_at: 200, run_status: "queued" },
    );

    expect(history.map((conversation) => conversation.id)).toEqual([
      "new",
      "older",
    ]);
    expect(history[0]?.run_status).toBe("queued");
  });

  it("keeps reconciling a completed run until its durable assistant message arrives", () => {
    const detail = detailFixture();
    detail.current_run = {
      id: "run-1",
      conversation_id: detail.conversation.id,
      status: "completed",
      retry_of_run_id: null,
      public_error_code: null,
      public_error_message: null,
      cancellation_requested_at: null,
      created_at: "2026-07-31T12:00:00Z",
      started_at: "2026-07-31T12:00:01Z",
      terminal_at: "2026-07-31T12:00:04Z",
      last_event_sequence: 4,
    };
    detail.run_events.push({
      run_id: "run-1",
      sequence: 4,
      type: "status",
      payload: { status: "completed" },
      created_at: "2026-07-31T12:00:04Z",
    });

    expect(isStandaloneRunReconciled(detail, "run-1")).toBe(false);

    detail.messages.push({
      id: "assistant-1",
      role: "assistant",
      content: "Revenue increased.",
      sequence: 2,
      created_at: 125,
      metadata: { run_id: "run-1", status: "completed" },
    });

    expect(isStandaloneRunReconciled(detail, "run-1")).toBe(true);
  });

  it("keeps runtime identities stable when optimistic messages become durable", () => {
    expect(
      standaloneMessageKey("conversation-1", {
        id: "optimistic-user",
        role: "user",
        sequence: 3,
        metadata: { optimistic: true },
      }),
    ).toBe(
      standaloneMessageKey("conversation-1", {
        id: "durable-user",
        role: "user",
        sequence: 3,
        metadata: {},
      }),
    );
    expect(
      standaloneMessageKey("conversation-1", {
        id: "run-run-1",
        role: "assistant",
        sequence: Number.MAX_SAFE_INTEGER,
        metadata: { run_id: "run-1", optimistic: true },
      }),
    ).toBe(
      standaloneMessageKey("conversation-1", {
        id: "durable-assistant",
        role: "assistant",
        sequence: 4,
        metadata: { run_id: "run-1", status: "completed" },
      }),
    );
  });
});
