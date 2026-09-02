"use client";

import type { RunLiveInfo, RunLiveState } from "~/lib/chat-run-steps";

/** Footer text per live state; tool work shows the running step's label. */
export function livePillText(live: RunLiveInfo): string {
  switch (live.state) {
    case "booting":
      return "Starting runtime…";
    case "writing":
      return "Writing…";
    case "tool":
      return `${live.label || "Running a tool"}…`;
    case "thinking":
      return `${live.label || "Thinking"}…`;
    default:
      return "";
  }
}

const DOT_CLASS: Record<Exclude<RunLiveState, "idle">, string> = {
  booting: "chat-dot-live bg-[var(--color-success)]",
  tool: "chat-dot-live bg-[var(--color-success)]",
  writing: "bg-[var(--color-accent)]",
  thinking: "bg-[var(--color-text-dim)]",
};

/**
 * Quiet one-line status in a running message's footer: a coloured dot and
 * what the agent is doing right now. Sits before the Stop button so the
 * eye lands on the state, then the control.
 */
export function LivePill({ live }: { live: RunLiveInfo }) {
  if (live.state === "idle") return null;
  return (
    <span
      data-testid="chat-live-pill"
      data-state={live.state}
      role="status"
      className="inline-flex max-w-[24rem] items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-[var(--color-text-dim)]"
    >
      <span
        aria-hidden
        className={`h-1.5 w-1.5 flex-none rounded-full ${DOT_CLASS[live.state]}`}
      />
      <span className="chat-live-label truncate">{livePillText(live)}</span>
    </span>
  );
}
