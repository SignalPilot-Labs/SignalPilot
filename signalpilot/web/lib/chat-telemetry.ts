import type {
  StandaloneChatEvent,
  StandaloneChatMessage,
  StandaloneChatRun,
  ChatTokenUsage,
} from "~/lib/api";

export type ChatEventArrival = {
  runId: string;
  sequence: number;
  type: StandaloneChatEvent["type"];
  receivedAt: number;
};

export type ChatTelemetryMetrics = {
  currentRunMs: number | null;
  conversationMs: number | null;
  messageCount: number;
  userMessageCount: number;
  assistantMessageCount: number;
  averageAssistantResponseMs: number | null;
  averageAssistantMessageGapMs: number | null;
  toolCallCount: number;
  completedToolCallCount: number;
  failedToolCallCount: number;
  averageToolStartGapMs: number | null;
  averageToolDurationMs: number | null;
  averageToolToTextMs: number | null;
  textChunkCount: number;
  averageChunkGapMs: number | null;
  p95ChunkGapMs: number | null;
  longestChunkGapMs: number | null;
  averageChunkCharacters: number | null;
  averageBrowserArrivalGapMs: number | null;
  p95BrowserArrivalGapMs: number | null;
  firstTextMs: number | null;
  totalTokens: number;
  inputTokens: number;
  outputTokens: number;
  cacheCreationTokens: number;
  cacheReadTokens: number;
  runsWithUsage: number;
  estimatedVisibleTokens: number;
  recentEvents: Array<{
    key: string;
    type: string;
    at: string;
    serverGapMs: number | null;
    browserGapMs: number | null;
  }>;
};

const eventMs = (event: StandaloneChatEvent) => Date.parse(event.created_at);
const messageMs = (message: StandaloneChatMessage) => message.created_at * 1_000;

const tokenValue = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? Math.max(0, value) : 0;

export function parseChatTokenUsage(value: unknown): ChatTokenUsage | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const usage = {
    input_tokens: tokenValue(raw.input_tokens),
    output_tokens: tokenValue(raw.output_tokens),
    cache_creation_input_tokens: tokenValue(raw.cache_creation_input_tokens),
    cache_read_input_tokens: tokenValue(raw.cache_read_input_tokens),
  };
  return Object.values(usage).some((count) => count > 0) ? usage : null;
}

export function totalChatTokens(usage: ChatTokenUsage | null): number {
  if (!usage) return 0;
  return (
    tokenValue(usage.input_tokens) +
    tokenValue(usage.output_tokens) +
    tokenValue(usage.cache_creation_input_tokens) +
    tokenValue(usage.cache_read_input_tokens)
  );
}

/** Claude does not expose message-level tokenization; this is display-only. */
export function estimateMessageTokens(content: string): number {
  const text = content.trim();
  return text ? Math.max(1, Math.ceil(text.length / 4)) : 0;
}

function average(values: number[]): number | null {
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function percentile(values: number[], fraction: number): number | null {
  if (!values.length) return null;
  const ordered = [...values].sort((left, right) => left - right);
  return ordered[Math.ceil(ordered.length * fraction) - 1] ?? null;
}

function positiveGaps(values: number[]): number[] {
  return values
    .slice(1)
    .map((value, index) => value - values[index])
    .filter((value) => value >= 0);
}

function eventsByRun(events: StandaloneChatEvent[]) {
  const grouped = new Map<string, StandaloneChatEvent[]>();
  for (const event of events) {
    const runEvents = grouped.get(event.run_id) ?? [];
    runEvents.push(event);
    grouped.set(event.run_id, runEvents);
  }
  for (const runEvents of grouped.values()) {
    runEvents.sort((left, right) => left.sequence - right.sequence);
  }
  return grouped;
}

export function deriveChatTelemetry(
  messages: StandaloneChatMessage[],
  events: StandaloneChatEvent[],
  currentRun: StandaloneChatRun | null,
  arrivals: ChatEventArrival[],
  nowMs: number,
): ChatTelemetryMetrics {
  const orderedMessages = messages
    .filter((message) => message.metadata.optimistic !== true)
    .sort(
      (left, right) =>
        messageMs(left) - messageMs(right) || left.sequence - right.sequence,
    );
  const orderedEvents = [...events].sort(
    (left, right) => eventMs(left) - eventMs(right) || left.sequence - right.sequence,
  );
  const userMessages = orderedMessages.filter((message) => message.role === "user");
  const assistantMessages = orderedMessages.filter((message) => message.role === "assistant");
  const usageByRun = new Map<string, ChatTokenUsage>();
  for (const message of assistantMessages) {
    const runId = typeof message.metadata.run_id === "string" ? message.metadata.run_id : "";
    const usage = parseChatTokenUsage(message.metadata.token_usage);
    if (runId && usage) usageByRun.set(runId, usage);
  }
  if (currentRun?.usage && !usageByRun.has(currentRun.id)) {
    const usage = parseChatTokenUsage(currentRun.usage);
    if (usage) usageByRun.set(currentRun.id, usage);
  }
  const usageTotals = [...usageByRun.values()].reduce(
    (total, usage) => ({
      input: total.input + tokenValue(usage.input_tokens),
      output: total.output + tokenValue(usage.output_tokens),
      cacheCreation:
        total.cacheCreation + tokenValue(usage.cache_creation_input_tokens),
      cacheRead: total.cacheRead + tokenValue(usage.cache_read_input_tokens),
    }),
    { input: 0, output: 0, cacheCreation: 0, cacheRead: 0 },
  );
  const assistantResponseTimes: number[] = [];
  for (const assistant of assistantMessages) {
    const priorUser = [...userMessages]
      .reverse()
      .find((message) => messageMs(message) <= messageMs(assistant));
    if (priorUser) assistantResponseTimes.push(messageMs(assistant) - messageMs(priorUser));
  }

  const grouped = eventsByRun(orderedEvents);
  const toolStarts = orderedEvents.filter((event) => event.type === "tool_started");
  const toolCompletes = orderedEvents.filter((event) => event.type === "tool_completed");
  const completionById = new Map<string, StandaloneChatEvent[]>();
  for (const event of toolCompletes) {
    const id = typeof event.payload.tool_call_id === "string" ? event.payload.tool_call_id : "";
    if (!id) continue;
    const matches = completionById.get(id) ?? [];
    matches.push(event);
    completionById.set(id, matches);
  }
  const toolDurations: number[] = [];
  const toolToText: number[] = [];
  for (const start of toolStarts) {
    const id = typeof start.payload.tool_call_id === "string" ? start.payload.tool_call_id : "";
    const completion = id
      ? completionById.get(id)?.find((event) => eventMs(event) >= eventMs(start))
      : undefined;
    if (!completion) continue;
    toolDurations.push(eventMs(completion) - eventMs(start));
    const nextText = grouped
      .get(start.run_id)
      ?.find(
        (event) =>
          event.type === "text_delta" && event.sequence > completion.sequence,
      );
    if (nextText) toolToText.push(eventMs(nextText) - eventMs(completion));
  }

  const textChunks = orderedEvents.filter((event) => event.type === "text_delta");
  const chunkGaps = [...grouped.values()].flatMap((runEvents) =>
    positiveGaps(
      runEvents
        .filter((event) => event.type === "text_delta")
        .map(eventMs),
    ),
  );
  const arrivalText = arrivals
    .filter((sample) => sample.type === "text_delta")
    .sort((left, right) => left.receivedAt - right.receivedAt);
  const arrivalGaps = positiveGaps(arrivalText.map((sample) => sample.receivedAt));

  const firstTextTimes: number[] = [];
  for (const runEvents of grouped.values()) {
    const first = runEvents[0];
    const firstText = runEvents.find((event) => event.type === "text_delta");
    if (first && firstText) firstTextTimes.push(eventMs(firstText) - eventMs(first));
  }

  const arrivalByKey = new Map(
    arrivals.map((sample) => [
      `${sample.runId}:${sample.sequence}`,
      sample.receivedAt,
    ]),
  );
  const recentSource = orderedEvents.slice(-12);
  const recentEvents = recentSource.map((event, index) => {
    const prior = orderedEvents[orderedEvents.length - recentSource.length + index - 1];
    const key = `${event.run_id}:${event.sequence}`;
    const browserAt = arrivalByKey.get(key);
    const priorBrowserAt = prior
      ? arrivalByKey.get(`${prior.run_id}:${prior.sequence}`)
      : undefined;
    return {
      key,
      type: event.type,
      at: event.created_at,
      serverGapMs: prior ? Math.max(0, eventMs(event) - eventMs(prior)) : null,
      browserGapMs:
        browserAt != null && priorBrowserAt != null
          ? Math.max(0, browserAt - priorBrowserAt)
          : null,
    };
  });

  const conversationStart = orderedMessages[0]
    ? messageMs(orderedMessages[0])
    : orderedEvents[0]
      ? eventMs(orderedEvents[0])
      : null;
  const latestRecorded = Math.max(
    conversationStart ?? 0,
    orderedMessages.at(-1) ? messageMs(orderedMessages.at(-1)!) : 0,
    orderedEvents.at(-1) ? eventMs(orderedEvents.at(-1)!) : 0,
  );
  const conversationEnd =
    currentRun && ["queued", "running"].includes(currentRun.status)
      ? nowMs
      : latestRecorded;
  const runStart = currentRun
    ? Date.parse(currentRun.started_at ?? currentRun.created_at)
    : null;
  const runEnd = currentRun
    ? currentRun.terminal_at
      ? Date.parse(currentRun.terminal_at)
      : ["queued", "running"].includes(currentRun.status)
        ? nowMs
        : orderedEvents.filter((event) => event.run_id === currentRun.id).at(-1)
          ? eventMs(orderedEvents.filter((event) => event.run_id === currentRun.id).at(-1)!)
          : nowMs
    : null;

  return {
    currentRunMs:
      runStart != null && runEnd != null ? Math.max(0, runEnd - runStart) : null,
    conversationMs:
      conversationStart != null ? Math.max(0, conversationEnd - conversationStart) : null,
    messageCount: orderedMessages.length,
    userMessageCount: userMessages.length,
    assistantMessageCount: assistantMessages.length,
    averageAssistantResponseMs: average(assistantResponseTimes),
    averageAssistantMessageGapMs: average(
      positiveGaps(assistantMessages.map(messageMs)),
    ),
    toolCallCount: toolStarts.length,
    completedToolCallCount: toolCompletes.length,
    failedToolCallCount: toolCompletes.filter((event) => event.payload.error === true).length,
    averageToolStartGapMs: average(
      [...grouped.values()].flatMap((runEvents) =>
        positiveGaps(
          runEvents
            .filter((event) => event.type === "tool_started")
            .map(eventMs),
        ),
      ),
    ),
    averageToolDurationMs: average(toolDurations),
    averageToolToTextMs: average(toolToText),
    textChunkCount: textChunks.length,
    averageChunkGapMs: average(chunkGaps),
    p95ChunkGapMs: percentile(chunkGaps, 0.95),
    longestChunkGapMs: chunkGaps.length ? Math.max(...chunkGaps) : null,
    averageChunkCharacters: average(
      textChunks.map((event) =>
        typeof event.payload.delta === "string" ? event.payload.delta.length : 0,
      ),
    ),
    averageBrowserArrivalGapMs: average(arrivalGaps),
    p95BrowserArrivalGapMs: percentile(arrivalGaps, 0.95),
    firstTextMs: average(firstTextTimes),
    totalTokens:
      usageTotals.input +
      usageTotals.output +
      usageTotals.cacheCreation +
      usageTotals.cacheRead,
    inputTokens: usageTotals.input,
    outputTokens: usageTotals.output,
    cacheCreationTokens: usageTotals.cacheCreation,
    cacheReadTokens: usageTotals.cacheRead,
    runsWithUsage: usageByRun.size,
    estimatedVisibleTokens: orderedMessages.reduce(
      (total, message) => total + estimateMessageTokens(message.content),
      0,
    ),
    recentEvents,
  };
}

export function formatTelemetryDuration(ms: number | null): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms < 1_000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1_000).toFixed(ms < 10_000 ? 1 : 0)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.floor((ms % 60_000) / 1_000);
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

export function formatTelemetryClock(value: string | number): string {
  const date = new Date(typeof value === "number" ? value : Date.parse(value));
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatTokenCount(value: number): string {
  if (value < 1_000) return Math.round(value).toLocaleString("en-US");
  if (value < 1_000_000) return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)}k`;
  return `${(value / 1_000_000).toFixed(1)}m`;
}
