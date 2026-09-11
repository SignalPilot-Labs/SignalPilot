// Pure projection from the gateway's conversation detail to the rendered
// message list. The live chat page and the read-only shared page both build
// their transcript through this one function.

import type {
  StandaloneChatEvent,
  StandaloneChatMessage,
  StandaloneChatRun,
} from "~/lib/api";
import type { UiMessage } from "~/components/chat/chat-ui-context";
import {
  assembleStandaloneRunText,
  containsStandaloneSubmission,
  deriveStandaloneRunActivity,
  type OptimisticUserMessage,
} from "~/lib/standalone-chat-state";

function eventText(
  event: StandaloneChatEvent | null | undefined,
  key: string,
): string {
  const value = event?.payload?.[key];
  return typeof value === "string" ? value : "";
}

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

/**
 * The synthetic assistant row for a run the gateway has not yet persisted a
 * final message for. Null when the transcript already carries the run's
 * terminal (or awaited clarification) message.
 */
export function syntheticRunMessage(
  currentRun: StandaloneChatRun,
  messages: StandaloneChatMessage[],
  events: StandaloneChatEvent[],
): UiMessage | null {
  const runMessages = messages.filter(
    (message) => message.metadata.run_id === currentRun.id,
  );
  const hasTerminalMessage = runMessages.some(
    (message) =>
      message.role === "assistant" &&
      TERMINAL.has(
        typeof message.metadata.status === "string"
          ? message.metadata.status
          : "",
      ),
  );
  const hasWaitingMessage = runMessages.some(
    (message) =>
      message.role === "assistant" &&
      message.metadata.status === "waiting_for_user",
  );
  if (
    hasTerminalMessage ||
    (currentRun.status === "waiting_for_user" && hasWaitingMessage)
  ) {
    return null;
  }
  const runEvents = events.filter((event) => event.run_id === currentRun.id);
  const resetSequence = runEvents.reduce(
    (latest, event) =>
      event.type === "status" && event.payload?.reset_text === true
        ? Math.max(latest, event.sequence)
        : latest,
    0,
  );
  const streamed = assembleStandaloneRunText(
    runEvents,
    currentRun.id,
    resetSequence,
  );
  const clarification = [...runEvents]
    .reverse()
    .find((event) => event.type === "clarification_requested");
  const error = [...runEvents].reverse().find((event) => event.type === "error");
  const content =
    (clarification && eventText(clarification, "message")) ||
    streamed ||
    (error && eventText(error, "message")) ||
    (currentRun.status === "cancelled"
      ? "This run was stopped."
      : currentRun.status === "completed"
        ? "Finalizing your answer…"
        : "");
  return {
    id: `run-${currentRun.id}`,
    role: "assistant",
    content,
    sequence: Number.MAX_SAFE_INTEGER,
    created_at: Date.parse(currentRun.created_at) / 1_000,
    metadata: {
      run_id: currentRun.id,
      optimistic: true,
      ...(currentRun.usage ? { token_usage: currentRun.usage } : {}),
    },
    runId: currentRun.id,
    runStatus: currentRun.status,
    activity: deriveStandaloneRunActivity(runEvents, currentRun.id),
    synthetic: true,
  };
}

/**
 * Build the rendered message list.
 *
 * Finished history is the persisted messages as they are: every assistant
 * row carries its run id in metadata and the timeline folds from `events`
 * at render time. On top of that the live page adds the current run's
 * streaming row, the optimistic user submission, and a queued placeholder.
 * The shared page passes no run and no submission and gets the history.
 */
export function buildStandaloneUiMessages({
  detailMessages,
  currentRun = null,
  events,
  isSubmitting = false,
  pendingSubmission = null,
}: {
  detailMessages: StandaloneChatMessage[] | undefined;
  currentRun?: StandaloneChatRun | null;
  events: StandaloneChatEvent[];
  isSubmitting?: boolean;
  pendingSubmission?: OptimisticUserMessage | null;
}): UiMessage[] {
  const messages: UiMessage[] = [...(detailMessages ?? [])];
  if (currentRun) {
    const synthetic = syntheticRunMessage(currentRun, messages, events);
    if (synthetic) messages.push(synthetic);
  }
  if (
    pendingSubmission &&
    !containsStandaloneSubmission(messages, pendingSubmission)
  ) {
    messages.push({
      id: pendingSubmission.id,
      role: "user",
      content: pendingSubmission.content,
      sequence: Number.MAX_SAFE_INTEGER - 1,
      created_at: pendingSubmission.createdAt,
      metadata: { optimistic: true },
    });
  }
  const streaming =
    currentRun?.status === "queued" || currentRun?.status === "running";
  if (pendingSubmission && isSubmitting && !streaming) {
    messages.push({
      id: `pending-assistant-${pendingSubmission.id}`,
      role: "assistant",
      content: "",
      sequence: Number.MAX_SAFE_INTEGER,
      created_at: pendingSubmission.createdAt,
      metadata: { optimistic: true },
      runStatus: "queued",
      activity: deriveStandaloneRunActivity([], ""),
      synthetic: true,
    });
  }
  return messages;
}
