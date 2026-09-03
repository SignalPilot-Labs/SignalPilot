"use client";

import { Activity, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type {
  StandaloneChatEvent,
  StandaloneChatMessage,
  StandaloneChatRun,
} from "~/lib/api";
import {
  deriveChatTelemetry,
  formatTelemetryClock,
  formatTelemetryDuration,
  formatTokenCount,
  type ChatEventArrival,
} from "~/lib/chat-telemetry";
import { ChatTelemetryContext } from "~/components/chat/chat-telemetry-context";

const CHAT_TELEMETRY_ENABLED =
  process.env.NEXT_PUBLIC_CHAT_TELEMETRY_ENABLED === "true";

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-[var(--color-text-dim)]">{label}</div>
      <div className="mt-0.5 font-mono text-sm tabular-nums text-[var(--color-text)]">{value}</div>
      {detail && <div className="mt-0.5 text-[10px] text-[var(--color-text-dim)]">{detail}</div>}
    </div>
  );
}

function ChatTelemetryPanel({
  messages,
  events,
  currentRun,
  arrivals,
  nowMs,
}: {
  messages: StandaloneChatMessage[];
  events: StandaloneChatEvent[];
  currentRun: StandaloneChatRun | null;
  arrivals: ChatEventArrival[];
  nowMs: number;
}) {
  const [open, setOpen] = useState(false);
  const metrics = useMemo(
    () => deriveChatTelemetry(messages, events, currentRun, arrivals, nowMs),
    [messages, events, currentRun, arrivals, nowMs],
  );
  return (
    <>
      <button
        type="button"
        data-testid="chat-telemetry-toggle"
        aria-label="Open chat telemetry"
        title="Open staging chat telemetry"
        onClick={() => setOpen((value) => !value)}
        className="fixed right-6 top-20 z-40 flex h-9 items-center gap-1.5 rounded-lg border border-cyan-400/25 bg-[var(--color-bg-card)] px-2.5 font-mono text-[11px] tabular-nums text-cyan-300 shadow-lg shadow-black/20 hover:bg-[var(--color-bg-hover)]"
      >
        <Activity className="h-3.5 w-3.5" />
        {formatTelemetryDuration(metrics.currentRunMs)}
      </button>
      {open && (
        <aside
          data-testid="chat-telemetry-panel"
          className="fixed bottom-4 right-4 top-32 z-50 flex w-[430px] max-w-[calc(100%-2rem)] flex-col overflow-hidden rounded-xl border border-cyan-400/20 bg-[var(--color-bg-card)] shadow-2xl shadow-black/50"
        >
          <header className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-medium text-[var(--color-text)]">
                <Activity className="h-4 w-4 text-cyan-300" /> Chat telemetry
              </div>
              <p className="mt-0.5 text-[10px] text-[var(--color-text-dim)]">Staging diagnostics · server and browser timing</p>
            </div>
            <button type="button" aria-label="Close chat telemetry" onClick={() => setOpen(false)} className="rounded-md p-1 text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]">
              <X className="h-4 w-4" />
            </button>
          </header>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
            <section>
              <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Overview</h3>
              <div className="grid grid-cols-2 gap-2">
                <Metric label="Current run" value={formatTelemetryDuration(metrics.currentRunMs)} />
                <Metric label="Conversation" value={formatTelemetryDuration(metrics.conversationMs)} />
                <Metric label="Messages" value={String(metrics.messageCount)} detail={`${metrics.userMessageCount} user · ${metrics.assistantMessageCount} agent`} />
                <Metric label="Tool calls" value={String(metrics.toolCallCount)} detail={`${metrics.completedToolCallCount} completed · ${metrics.failedToolCallCount} failed`} />
              </div>
            </section>
            <section>
              <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Agent pacing</h3>
              <div className="grid grid-cols-2 gap-2">
                <Metric label="Avg response" value={formatTelemetryDuration(metrics.averageAssistantResponseMs)} detail="user prompt → agent message" />
                <Metric label="Agent msg gap" value={formatTelemetryDuration(metrics.averageAssistantMessageGapMs)} />
                <Metric label="First text" value={formatTelemetryDuration(metrics.firstTextMs)} detail="run event → first text" />
                <Metric label="Tool → text" value={formatTelemetryDuration(metrics.averageToolToTextMs)} />
              </div>
            </section>
            <section>
              <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Tokens</h3>
              <div className="grid grid-cols-2 gap-2">
                <Metric label="Total processed" value={formatTokenCount(metrics.totalTokens)} detail={`exact SDK usage · ${metrics.runsWithUsage} runs`} />
                <Metric label="Visible text" value={`~${formatTokenCount(metrics.estimatedVisibleTokens)}`} detail="estimated from transcript text" />
                <Metric label="Input" value={formatTokenCount(metrics.inputTokens)} />
                <Metric label="Output" value={formatTokenCount(metrics.outputTokens)} />
                <Metric label="Cache read" value={formatTokenCount(metrics.cacheReadTokens)} />
                <Metric label="Cache write" value={formatTokenCount(metrics.cacheCreationTokens)} />
              </div>
            </section>
            <section>
              <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Tools</h3>
              <div className="grid grid-cols-2 gap-2">
                <Metric label="Avg start gap" value={formatTelemetryDuration(metrics.averageToolStartGapMs)} />
                <Metric label="Avg duration" value={formatTelemetryDuration(metrics.averageToolDurationMs)} />
              </div>
            </section>
            <section>
              <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Text chunks</h3>
              <div className="grid grid-cols-2 gap-2">
                <Metric label="Chunks" value={String(metrics.textChunkCount)} detail={`${Math.round(metrics.averageChunkCharacters ?? 0)} avg chars`} />
                <Metric label="Server avg gap" value={formatTelemetryDuration(metrics.averageChunkGapMs)} />
                <Metric label="Server p95 gap" value={formatTelemetryDuration(metrics.p95ChunkGapMs)} detail={`max ${formatTelemetryDuration(metrics.longestChunkGapMs)}`} />
                <Metric label="Browser avg gap" value={formatTelemetryDuration(metrics.averageBrowserArrivalGapMs)} detail={`p95 ${formatTelemetryDuration(metrics.p95BrowserArrivalGapMs)} · live only`} />
              </div>
            </section>
            <section>
              <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[var(--color-text-muted)]">Latest events</h3>
              <div className="overflow-hidden rounded-lg border border-[var(--color-border)]">
                <div className="grid grid-cols-[1fr_70px_64px_64px] gap-2 bg-[var(--color-bg-input)] px-2 py-1.5 text-[9px] uppercase tracking-wide text-[var(--color-text-dim)]">
                  <span>Event</span><span>Time</span><span>Server Δ</span><span>Browser Δ</span>
                </div>
                {metrics.recentEvents.map((event) => (
                  <div key={event.key} className="grid grid-cols-[1fr_70px_64px_64px] gap-2 border-t border-[var(--color-border)] px-2 py-1.5 font-mono text-[10px] tabular-nums text-[var(--color-text-muted)]">
                    <span className="truncate" title={event.type}>{event.type}</span>
                    <span>{formatTelemetryClock(event.at)}</span>
                    <span>{formatTelemetryDuration(event.serverGapMs)}</span>
                    <span>{formatTelemetryDuration(event.browserGapMs)}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </aside>
      )}
    </>
  );
}

export function ChatTelemetryBoundary({
  children,
  messages,
  events,
  currentRun,
  arrivals,
  running,
}: {
  children: ReactNode;
  messages: StandaloneChatMessage[];
  events: StandaloneChatEvent[];
  currentRun: StandaloneChatRun | null;
  arrivals: ChatEventArrival[];
  running: boolean;
}) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!CHAT_TELEMETRY_ENABLED || !running) return;
    const timer = window.setInterval(() => setNowMs(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [running]);
  if (!CHAT_TELEMETRY_ENABLED) return children;
  return (
    <ChatTelemetryContext.Provider value={{ enabled: true, nowMs }}>
      {children}
      <ChatTelemetryPanel
        messages={messages}
        events={events}
        currentRun={currentRun}
        arrivals={arrivals}
        nowMs={nowMs}
      />
    </ChatTelemetryContext.Provider>
  );
}
