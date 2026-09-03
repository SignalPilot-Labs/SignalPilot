"use client";

import { Activity, Brain, PenLine } from "lucide-react";
import { useEffect, useState } from "react";
import type { RunLiveInfo } from "~/lib/chat-run-steps";
import "./chat-live.css";

/**
 * Quiet phrases that rotate under the "Thinking" label while the agent is
 * between tool calls. They alternate between reasoning and doing so the row
 * reads as activity, not a stalled spinner. None claims to know what the
 * agent is actually deliberating.
 */
export const THINKING_PHRASES = [
  "Weighing the options",
  "Reading the results",
  "Connecting the dots",
  "Checking the numbers",
  "Lining up the next step",
  "Mulling it over",
  "Sizing up the schema",
  "Cross-checking",
  "Working through it",
  "Puzzling this out",
  "Sketching the approach",
  "Taking stock",
  "Reasoning it through",
  "Chewing on the data",
  "Plotting the next move",
  "Double-checking",
  "Turning it over",
  "Getting oriented",
] as const;

/** Dwell time per phrase; long enough to read, short enough to feel alive. */
const PHRASE_INTERVAL_MS = 2_400;

let phraseSeed = 0;

/**
 * Cycles through THINKING_PHRASES, starting from a different phrase each
 * mount so several indicators in one transcript don't move in lockstep.
 */
function useCyclingPhrase(): string {
  const [index, setIndex] = useState(() => phraseSeed++ % THINKING_PHRASES.length);
  useEffect(() => {
    const id = window.setInterval(
      () => setIndex((i) => (i + 1) % THINKING_PHRASES.length),
      PHRASE_INTERVAL_MS,
    );
    return () => window.clearInterval(id);
  }, []);
  return THINKING_PHRASES[index];
}

const ROW_CLASS =
  "chat-step-in my-3 flex items-center gap-2.5 px-1 py-1 text-[12px] text-[var(--color-text-muted)]";
const CHIP_CLASS =
  "relative flex h-7 w-7 flex-none items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)]";

/**
 * Shows that an active agent is deciding what to do next without implying
 * that private chain-of-thought content is available to the application.
 */
export function AgentThinkingIndicator({
  label = "Thinking",
}: {
  label?: string;
}) {
  const phrase = useCyclingPhrase();
  return (
    <div
      data-testid="chat-agent-thinking"
      role="status"
      aria-label="Agent is thinking"
      className={ROW_CLASS}
    >
      <span className={CHIP_CLASS}>
        <Brain className="h-3.5 w-3.5 text-[var(--color-success)]/80" aria-hidden />
        <span className="chat-thinking-pulse absolute inset-0 rounded-lg border border-[var(--color-success)]/30" />
      </span>
      <span className="chat-live-label font-medium">{label}</span>
      <span className="flex items-end gap-1" aria-hidden>
        <span className="chat-thinking-dot h-1 w-1 rounded-full bg-[var(--color-text-dim)]" />
        <span className="chat-thinking-dot h-1 w-1 rounded-full bg-[var(--color-text-dim)]" />
        <span className="chat-thinking-dot h-1 w-1 rounded-full bg-[var(--color-text-dim)]" />
      </span>
      <span
        key={phrase}
        data-testid="chat-thinking-phrase"
        className="chat-step-in text-[11px] text-[var(--color-text-dim)]"
      >
        {phrase}
      </span>
    </div>
  );
}

function ToolIndicator({ label }: { label: string }) {
  return (
    <div role="status" aria-label={`Running ${label}`} className={ROW_CLASS}>
      <span className={CHIP_CLASS}>
        <Activity className="h-3.5 w-3.5 text-[var(--color-success)]/80" aria-hidden />
        <span className="chat-boot-orbit absolute -inset-px" aria-hidden />
      </span>
      <span className="chat-live-label min-w-0 truncate font-medium">{label}</span>
    </div>
  );
}

function WritingIndicator() {
  return (
    <div role="status" aria-label="Agent is writing" className={ROW_CLASS}>
      <span className={CHIP_CLASS}>
        <PenLine className="h-3.5 w-3.5 text-[var(--color-success)]/80" aria-hidden />
      </span>
      <span className="chat-live-label font-medium">Writing</span>
      <span className="chat-token-flow" aria-hidden>
        <span />
        <span />
        <span />
        <span />
      </span>
    </div>
  );
}

/**
 * One indicator for every live state. Thinking and booting keep the
 * familiar brain row; tool work gets the orbit ring with the step's label;
 * writing gets the pen and a ripple of token bars. Idle renders nothing.
 */
export function AgentLiveIndicator({ live }: { live: RunLiveInfo }) {
  if (live.state === "idle") return null;
  return (
    <div
      data-testid="chat-live-indicator"
      data-state={live.state}
      className="contents"
    >
      {live.state === "tool" ? (
        <ToolIndicator label={live.label || "Running a tool"} />
      ) : live.state === "writing" ? (
        <WritingIndicator />
      ) : (
        <AgentThinkingIndicator label={live.label || "Thinking"} />
      )}
    </div>
  );
}
