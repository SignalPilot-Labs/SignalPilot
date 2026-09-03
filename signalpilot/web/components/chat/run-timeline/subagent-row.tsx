"use client";

import { Bot, ChevronRight } from "lucide-react";
import { memo, useEffect, useState, type ReactNode } from "react";
import { ChatMarkdown } from "~/components/chat/chat-markdown";
import {
  describeSubagentWork,
  formatStepDuration,
  type RunStep,
} from "~/lib/chat-run-steps";
import { StatusDot } from "./step-row";

/** Elapsed time for a live subagent from its OWN event clock (latest child
 * activity minus spawn start) — correct under replay and clock skew, where
 * wall-clock deltas are nonsense. */
export function subagentElapsedMs(step: RunStep): number | null {
  const start = Date.parse(step.startedAt);
  if (!Number.isFinite(start)) return null;
  let latest = start;
  for (const child of step.children) {
    for (const stamp of [child.startedAt, child.endedAt]) {
      const parsed = stamp ? Date.parse(stamp) : Number.NaN;
      if (Number.isFinite(parsed) && parsed > latest) latest = parsed;
    }
  }
  return latest > start ? latest - start : null;
}

export function lastNarrationLine(liveText: string): string | null {
  const lines = liveText
    .split("\n")
    // Strip markdown emphasis/heading markers but keep identifier
    // characters like the underscores in column names.
    .map((line) => line.replace(/[*`]/g, "").replace(/^[#>\s-]+/, "").trim())
    .filter(Boolean);
  const last = lines[lines.length - 1];
  if (!last) return null;
  return last.length > 110 ? `${last.slice(0, 110)}…` : last;
}

/**
 * One subagent spawn rendered as its own live card: an autonomous worker
 * with a mission, a heartbeat, and a report. While it runs the card shows
 * the exact tool it is on plus a running tally; expanded, the full child
 * timeline and the final report are inspectable.
 *
 * `childTimeline` is the rendered child step list (a `RunTimeline` over
 * `step.children`), passed in by the timeline so this module never imports
 * the timeline back.
 */
export const SubagentRow = memo(function SubagentRow({
  step,
  childTimeline,
}: {
  step: RunStep;
  childTimeline: ReactNode;
}) {
  const running = step.status === "running";
  const [userToggle, setUserToggle] = useState<boolean | null>(null);
  // Reopen if it starts working again; collapse once the report lands.
  useEffect(() => {
    if (running) setUserToggle(null);
  }, [running]);
  const open = userToggle ?? running;
  const currentChild = [...step.children]
    .reverse()
    .find((child) => child.status === "running");
  const narration = lastNarrationLine(step.liveText);
  const tally = describeSubagentWork(step);
  const elapsed = formatStepDuration(
    running ? subagentElapsedMs(step) : step.durationMs,
  );
  return (
    <li className="chat-step-in relative">
      <div className="flex items-start gap-2.5">
        <StatusDot status={step.status} />
        <div className="min-w-0 flex-1 pb-1">
          <section
            data-testid="chat-subagent-card"
            className={`overflow-hidden rounded-lg border bg-[var(--color-bg-card)]/70 ${
              running
                ? "border-[var(--color-success)]/25"
                : step.status === "failed"
                  ? "border-[var(--color-error)]/30"
                  : "border-[var(--color-border)]"
            }`}
          >
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setUserToggle(!open)}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-[var(--color-bg-hover)]"
            >
              <span className="relative h-7 w-7 flex-none" aria-hidden>
                <span className="absolute inset-0 rounded-lg border border-[var(--color-border)]" />
                {running && (
                  <span
                    className="chat-boot-orbit absolute inset-0"
                    style={{ borderRadius: "0.5rem" }}
                  />
                )}
                <span className="absolute inset-0 flex items-center justify-center">
                  <Bot
                    className={`h-3.5 w-3.5 ${
                      running
                        ? "text-[var(--color-success)]"
                        : "text-[var(--color-text-muted)]"
                    }`}
                  />
                </span>
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className="text-[9px] font-medium uppercase tracking-[0.16em] text-[var(--color-text-dim)]">
                    Subagent
                  </span>
                  {step.subagentType && (
                    <span className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-input)] px-1.5 py-px font-mono text-[9px] text-[var(--color-text-muted)]">
                      {step.subagentType}
                    </span>
                  )}
                </span>
                <span
                  className={`block truncate text-[12px] font-medium ${
                    running
                      ? "chat-live-label"
                      : step.status === "failed"
                        ? "text-[var(--color-error)]"
                        : "text-[var(--color-text)]"
                  }`}
                >
                  {step.title}
                </span>
              </span>
              <span className="ml-auto flex flex-none items-center gap-2 text-[10px] text-[var(--color-text-dim)]">
                <span className="hidden tabular-nums sm:inline">{tally}</span>
                {elapsed && <span className="tabular-nums">{elapsed}</span>}
                <ChevronRight
                  className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`}
                />
              </span>
            </button>
            {running && (currentChild || narration) && (
              <div className="flex items-center gap-2 border-t border-[var(--color-border)]/60 px-3 py-1.5 text-[11px] text-[var(--color-text-muted)]">
                <span className="chat-dot-live h-1.5 w-1.5 flex-none rounded-full bg-[var(--color-success)]" />
                {currentChild ? (
                  <span className="truncate">
                    {currentChild.title}
                    {currentChild.file && (
                      <span className="font-mono text-[var(--color-text-dim)]">
                        {" "}
                        {currentChild.file}
                      </span>
                    )}
                  </span>
                ) : (
                  <span className="truncate italic">{narration}</span>
                )}
              </div>
            )}
            <div className="chat-collapse" data-open={open}>
              <div>
                <div className="border-t border-[var(--color-border)]/60 px-3 py-2.5">
                  {step.children.length ? (
                    childTimeline
                  ) : (
                    <p className="px-1 text-[11px] text-[var(--color-text-dim)]">
                      The subagent is reading its instructions.
                    </p>
                  )}
                  {step.report && (
                    <div className="mt-2.5 border-t border-[var(--color-border)]/60 pt-2.5">
                      <p className="mb-1 text-[9px] font-medium uppercase tracking-[0.16em] text-[var(--color-text-dim)]">
                        Report
                      </p>
                      <ChatMarkdown
                        markdown={step.report}
                        className="chat-markdown-compact"
                      />
                    </div>
                  )}
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </li>
  );
});
