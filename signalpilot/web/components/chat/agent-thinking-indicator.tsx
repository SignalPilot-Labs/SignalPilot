"use client";

import { Brain } from "lucide-react";

/**
 * Shows that an active agent is deciding what to do next without implying
 * that private chain-of-thought content is available to the application.
 */
export function AgentThinkingIndicator() {
  return (
    <div
      data-testid="chat-agent-thinking"
      role="status"
      aria-label="Agent is thinking"
      className="chat-step-in my-3 flex items-center gap-2.5 px-1 py-1 text-[12px] text-[var(--color-text-muted)]"
    >
      <span className="relative flex h-7 w-7 flex-none items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        <Brain className="h-3.5 w-3.5 text-[var(--color-success)]/80" aria-hidden />
        <span className="chat-thinking-pulse absolute inset-0 rounded-lg border border-[var(--color-success)]/30" />
      </span>
      <span className="chat-live-label font-medium">Thinking</span>
      <span className="flex items-end gap-1" aria-hidden>
        <span className="chat-thinking-dot h-1 w-1 rounded-full bg-[var(--color-text-dim)]" />
        <span className="chat-thinking-dot h-1 w-1 rounded-full bg-[var(--color-text-dim)]" />
        <span className="chat-thinking-dot h-1 w-1 rounded-full bg-[var(--color-text-dim)]" />
      </span>
      <span className="text-[11px] text-[var(--color-text-dim)]">
        Deciding what to do next
      </span>
    </div>
  );
}
