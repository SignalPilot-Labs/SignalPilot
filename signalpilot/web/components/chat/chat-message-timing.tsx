"use client";

// Telemetry footer for one transcript message: wall-clock, response
// duration and token counts. Renders nothing unless telemetry is enabled.

import type { UiMessage } from "~/components/chat/chat-ui-context";
import {
  formatTelemetryClock,
  formatTelemetryDuration,
  formatTokenCount,
  estimateMessageTokens,
  parseChatTokenUsage,
  totalChatTokens,
} from "~/lib/chat-telemetry";
import { useChatTelemetryContext } from "~/components/chat/chat-telemetry-context";

export function MessageTiming({
  message,
  previousMessageAt,
  running,
}: {
  message: UiMessage;
  previousMessageAt?: number;
  running?: boolean;
}) {
  const telemetry = useChatTelemetryContext();
  if (!telemetry.enabled) return null;
  const recordedAt = message.created_at * 1_000;
  const endAt = running ? telemetry.nowMs : recordedAt;
  const duration =
    message.role === "assistant" && previousMessageAt != null
      ? Math.max(0, endAt - previousMessageAt * 1_000)
      : null;
  const exact = new Date(recordedAt).toLocaleString();
  const estimatedTextTokens = estimateMessageTokens(message.content);
  const usage = parseChatTokenUsage(message.metadata.token_usage);
  const runTokens = totalChatTokens(usage);
  const usageTitle = usage
    ? [
        `Exact SDK run usage: ${runTokens.toLocaleString("en-US")} tokens`,
        `${(usage.input_tokens ?? 0).toLocaleString("en-US")} input`,
        `${(usage.output_tokens ?? 0).toLocaleString("en-US")} output`,
        `${(usage.cache_creation_input_tokens ?? 0).toLocaleString("en-US")} cache write`,
        `${(usage.cache_read_input_tokens ?? 0).toLocaleString("en-US")} cache read`,
      ].join(" · ")
    : "Estimated visible-text tokens; exact usage is only available at run completion";
  return (
    <span
      data-testid="chat-message-timing"
      className="inline-flex flex-wrap items-center gap-1.5 font-mono text-[10px] tabular-nums text-[var(--color-text-dim)] opacity-60 transition-opacity group-hover:opacity-100"
    >
      <span
        title={
          duration == null
            ? exact
            : `${exact} · response ${formatTelemetryDuration(duration)}`
        }
      >
        {formatTelemetryClock(recordedAt)}
        {duration != null ? ` · ${formatTelemetryDuration(duration)}` : ""}
      </span>
      <span aria-hidden>·</span>
      <span data-testid="chat-message-token-count" title={usageTitle}>
        ~{formatTokenCount(estimatedTextTokens)} text
        {usage ? ` · ${formatTokenCount(runTokens)} run tokens` : " tokens"}
      </span>
    </span>
  );
}
