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

export type StandaloneRunActivity = {
  phase: "starting_runtime" | "analyzing" | "running_cells" | "fixing_query";
  label: string;
  detail: string;
};

const DEFAULT_RUN_ACTIVITY: StandaloneRunActivity = {
  phase: "analyzing",
  label: "Analyzing project",
  detail: "Finding the relevant models and data",
};

function eventString(event: StandaloneChatEvent, key: string): string {
  const value = event.payload[key];
  return typeof value === "string" ? value : "";
}

function toolSuffix(tool: string): string {
  return tool.split("__").at(-1) ?? tool;
}

/**
 * Convert low-level runtime events into the small set of stages shown in the
 * live assistant bubble. The full event payload remains available in View work.
 */
export function deriveStandaloneRunActivity(
  events: StandaloneChatEvent[],
  runId: string,
): StandaloneRunActivity {
  let activity = DEFAULT_RUN_ACTIVITY;
  let repairing = false;

  for (const event of events
    .filter((candidate) => candidate.run_id === runId)
    .sort((left, right) => left.sequence - right.sequence)) {
    if (
      (event.type === "cell_executed" &&
        eventString(event, "status") === "failed") ||
      (event.type === "tool_completed" && event.payload.error === true)
    ) {
      repairing = true;
      activity = {
        phase: "fixing_query",
        label: "Fixing query",
        detail: "Reviewing an execution error",
      };
      continue;
    }

    if (event.type === "runtime_boot") {
      const phase = eventString(event, "phase");
      activity =
        phase === "ready"
          ? DEFAULT_RUN_ACTIVITY
          : {
              phase: "starting_runtime",
              label:
                phase === "resuming"
                  ? "Waking your workspace"
                  : "Starting secure runtime",
              detail: "Preparing an isolated sandbox for this conversation",
            };
      continue;
    }

    if (event.type === "progress") {
      const progress = eventString(event, "label");
      if (/reconnect|restart|recover|repair|fix/i.test(progress)) {
        repairing = true;
        activity = {
          phase: "fixing_query",
          label: "Fixing query",
          detail: progress,
        };
      }
      continue;
    }

    if (event.type === "cell_executed") {
      repairing = false;
      activity = {
        phase: "running_cells",
        label: "Running cells",
        detail: "Notebook analysis completed",
      };
      continue;
    }

    if (event.type === "notebook_started") {
      activity = {
        phase: "running_cells",
        label: "Running cells",
        detail: repairing
          ? "Restarting notebook analysis"
          : "Starting notebook analysis",
      };
      continue;
    }

    if (event.type !== "tool_started") continue;
    const tool = toolSuffix(eventString(event, "tool"));

    if (tool === "run_cells") {
      activity = repairing
        ? {
            phase: "fixing_query",
            label: "Fixing query",
            detail: "Retrying notebook cells",
          }
        : {
            phase: "running_cells",
            label: "Running cells",
            detail: "Executing notebook analysis",
          };
      continue;
    }

    if (tool === "edit_notebook") {
      activity = repairing
        ? {
            phase: "fixing_query",
            label: "Fixing query",
            detail: "Updating notebook analysis",
          }
        : {
            phase: "running_cells",
            label: "Running cells",
            detail: "Preparing notebook analysis",
          };
      continue;
    }

    if (tool === "get_notebook_errors") {
      activity = repairing
        ? {
            phase: "fixing_query",
            label: "Fixing query",
            detail: "Checking the notebook error",
          }
        : {
            phase: "running_cells",
            label: "Running cells",
            detail: "Checking notebook output",
          };
      continue;
    }

    if (
      tool === "start_analysis_notebook" ||
      tool === "get_lightweight_cell_map"
    ) {
      activity = {
        phase: "running_cells",
        label: "Running cells",
        detail:
          tool === "start_analysis_notebook"
            ? "Starting notebook analysis"
            : "Inspecting notebook cells",
      };
      continue;
    }

    if (
      repairing &&
      /debug|validate|explain|plan_query|query_database/.test(tool)
    ) {
      activity = {
        phase: "fixing_query",
        label: "Fixing query",
        detail: "Validating the revised query",
      };
      continue;
    }

    const analysisDetails: Record<string, string> = {
      inspect_dbt: "Inspecting dbt metadata",
      list_tables: "Reviewing available tables",
      list_semantic_metrics: "Reviewing available metrics",
      schema_overview: "Reviewing the project schema",
      schema_ddl: "Inspecting table definitions",
      schema_link: "Tracing project relationships",
      schema_statistics: "Reviewing schema statistics",
      describe_table: "Inspecting relevant fields",
      explore_table: "Exploring relevant data",
      explore_column: "Inspecting relevant fields",
      explore_columns: "Inspecting relevant fields",
      get_relationships: "Tracing data relationships",
      find_join_path: "Finding the right data relationships",
      verify_metric_conformance: "Checking metric definitions",
      get_date_boundaries: "Checking data freshness",
      plan_query: "Planning a governed query",
      estimate_query_cost: "Checking query scope",
      explain_query: "Checking the query plan",
      validate_sql: "Validating the query",
      debug_cte_query: "Checking the query",
      query_database: "Querying relevant data",
    };
    activity = {
      phase: "analyzing",
      label: "Analyzing project",
      detail: analysisDetails[tool] ?? "Working with the relevant data",
    };
  }

  return activity;
}

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

export function markStandaloneRunStopped(
  detail: StandaloneConversationDetail,
  runId: string,
  stoppedAt = new Date().toISOString(),
): StandaloneConversationDetail {
  if (detail.current_run?.id !== runId) return detail;
  return {
    ...detail,
    conversation: {
      ...detail.conversation,
      run_status: "cancelled",
      updated_at: Date.parse(stoppedAt) / 1_000,
    },
    current_run: {
      ...detail.current_run,
      status: "cancelled",
      cancellation_requested_at: stoppedAt,
      terminal_at: stoppedAt,
    },
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
  const steeringMessageId =
    event.type === "steering_queued" ||
    event.type === "steering_picked_up" ||
    event.type === "steering_not_delivered"
      ? event.payload.message_id
      : null;
  const steeringStatus =
    event.type === "steering_queued"
      ? "queued"
      : event.type === "steering_picked_up"
        ? "picked_up"
        : event.type === "steering_not_delivered"
          ? "not_delivered"
        : null;
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
    messages:
      typeof steeringMessageId === "string" && steeringStatus
        ? detail.messages.map((message) =>
            message.id === steeringMessageId
              ? {
                  ...message,
                  metadata: {
                    ...message.metadata,
                    steering_status: steeringStatus,
                  },
                }
              : message,
          )
        : detail.messages,
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
