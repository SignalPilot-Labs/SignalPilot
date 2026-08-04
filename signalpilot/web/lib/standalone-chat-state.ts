import type {
  StandaloneChatEvent,
  StandaloneChatMessage,
  StandaloneChatRunStatus,
  StandaloneConversation,
  StandaloneConversationDetail,
} from "~/lib/api";

export type OptimisticUserMessage = {
  id: string;
  content: string;
  createdAt: number;
};

export function appendOptimisticUserMessage(
  detail: StandaloneConversationDetail,
  optimistic: OptimisticUserMessage,
): StandaloneConversationDetail {
  const message: StandaloneChatMessage = {
    id: optimistic.id,
    role: "user",
    content: optimistic.content,
    sequence:
      detail.messages.reduce(
        (maximum, current) => Math.max(maximum, current.sequence),
        0,
      ) + 1,
    created_at: optimistic.createdAt,
    metadata: { optimistic: true },
  };
  return {
    ...detail,
    messages: [...detail.messages, message],
  };
}

export function containsStandaloneSubmission(
  messages: StandaloneChatMessage[],
  submission: OptimisticUserMessage,
  durableOnly = false,
): boolean {
  return messages.some(
    (message) =>
      (!durableOnly || message.metadata.optimistic !== true) &&
      (message.id === submission.id ||
        (message.role === "user" &&
          message.content === submission.content &&
          Math.abs(message.created_at - submission.createdAt) < 60)),
  );
}

const runStatuses = new Set<StandaloneChatRunStatus>([
  "queued",
  "running",
  "waiting_for_user",
  "waiting_for_query_approval",
  "completed",
  "failed",
  "cancelled",
]);

function eventRunStatus(
  event: StandaloneChatEvent,
): StandaloneChatRunStatus | null {
  const status = event.payload.status;
  return typeof status === "string" &&
    runStatuses.has(status as StandaloneChatRunStatus)
    ? (status as StandaloneChatRunStatus)
    : null;
}

export function mergeStandaloneChatEvents(
  current: StandaloneChatEvent[],
  incoming: StandaloneChatEvent[],
): StandaloneChatEvent[] {
  const byId = new Map(
    current.map((event) => [`${event.run_id}:${event.sequence}`, event]),
  );
  for (const event of incoming) {
    byId.set(`${event.run_id}:${event.sequence}`, event);
  }
  return [...byId.values()].sort((left, right) => {
    const timestamp =
      Date.parse(left.created_at) - Date.parse(right.created_at);
    return timestamp || left.sequence - right.sequence;
  });
}

const textBlockBoundaryTypes = new Set<StandaloneChatEvent["type"]>([
  "tool_started",
  "tool_completed",
  "sql",
  "source",
  "intermediate_result",
  "artifact_created",
  "query_proposed",
  "query_estimated",
  "query_approval_requested",
  "query_approved",
  "query_declined",
  "query_started",
  "query_progress",
  "query_completed",
  "query_cancelled",
]);

function appendTextBlock(current: string, delta: string): string {
  const trailingNewlines = current.length - current.replace(/\n+$/, "").length;
  const leadingNewlines = delta.length - delta.replace(/^\n+/, "").length;
  return `${current}${"\n".repeat(
    Math.max(0, 2 - trailingNewlines - leadingNewlines),
  )}${delta}`;
}

export function assembleStandaloneRunText(
  events: StandaloneChatEvent[],
  runId: string,
  afterSequence = 0,
): string {
  let text = "";
  let startsNewBlock = false;
  for (const event of events
    .filter(
      (candidate) =>
        candidate.run_id === runId && candidate.sequence > afterSequence,
    )
    .sort((left, right) => left.sequence - right.sequence)) {
    if (event.type === "text_delta") {
      const delta = event.payload.delta;
      if (typeof delta !== "string" || !delta) continue;
      text =
        startsNewBlock && text ? appendTextBlock(text, delta) : text + delta;
      startsNewBlock = false;
    } else if (textBlockBoundaryTypes.has(event.type)) {
      startsNewBlock = true;
    }
  }
  return text;
}

export function applyStandaloneChatEvent(
  detail: StandaloneConversationDetail,
  event: StandaloneChatEvent,
): StandaloneConversationDetail {
  const status = event.type === "status" ? eventRunStatus(event) : null;
  const appliesToCurrentRun = detail.current_run?.id === event.run_id;
  return {
    ...detail,
    conversation:
      status && appliesToCurrentRun
        ? { ...detail.conversation, run_status: status }
        : detail.conversation,
    current_run: appliesToCurrentRun
      ? {
          ...detail.current_run!,
          ...(status ? { status } : {}),
          last_event_sequence: Math.max(
            detail.current_run!.last_event_sequence,
            event.sequence,
          ),
        }
      : detail.current_run,
    run_events: mergeStandaloneChatEvents(detail.run_events, [event]),
  };
}

export function isStandaloneRunReconciled(
  detail: StandaloneConversationDetail,
  runId: string,
): boolean {
  const run = detail.current_run;
  if (!run || run.id !== runId) return true;
  if (run.status === "queued" || run.status === "running") return false;
  if (run.status === "waiting_for_query_approval") {
    return detail.run_events.some(
      (event) =>
        event.run_id === runId && event.type === "query_approval_requested",
    );
  }
  return detail.messages.some(
    (message) =>
      message.role === "assistant" &&
      message.metadata.run_id === runId &&
      message.metadata.status === run.status,
  );
}

export function standaloneMessageKey(
  conversationId: string | undefined,
  message: Pick<StandaloneChatMessage, "id" | "role" | "sequence" | "metadata">,
): string {
  const runId =
    typeof message.metadata.run_id === "string"
      ? message.metadata.run_id
      : undefined;
  if (message.role === "assistant" && runId) return `run-${runId}`;
  if (conversationId) {
    return `${conversationId}-${message.role}-${message.sequence}`;
  }
  return message.id;
}

export function upsertStandaloneConversation(
  conversations: StandaloneConversation[],
  conversation: StandaloneConversation,
): StandaloneConversation[] {
  return [
    conversation,
    ...conversations.filter((current) => current.id !== conversation.id),
  ].sort((left, right) => right.updated_at - left.updated_at);
}
