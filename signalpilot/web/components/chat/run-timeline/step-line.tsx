"use client";

import { ChevronRight, type LucideIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import { formatStepDuration, type RunStep } from "~/lib/chat-run-steps";
import { FAILED_TONE_CLASS } from "~/components/chat/tool-cards/card-primitives";

/**
 * The one-line row every timeline step renders as, running, done or failed.
 *
 * Its height never changes with the step's status: a status change only
 * swaps the glyph (crossfade), the label shimmer and the stat at the end.
 * A failure shows as a one-line amber reason in the stat slot. The body
 * (result, SQL, output) opens below only on a click, with the shared height
 * transition, and mounts on first open so collapsed rows stay cheap.
 */
export function StepLine({
  step,
  Icon,
  iconClassName = "text-[var(--color-text-dim)]",
  title,
  stat,
  failure,
  open,
  onToggle,
  trailing,
  testId = "chat-step-line",
  kind,
  ok,
  children,
}: {
  step: RunStep;
  Icon: LucideIcon;
  iconClassName?: string;
  title: string;
  stat?: string | null;
  /** One-line failure reason shown in place of the stat. */
  failure?: string | null;
  open: boolean;
  onToggle: () => void;
  /** Extra end-of-row content (telemetry time). */
  trailing?: ReactNode;
  testId?: string;
  /** Card kind, for tests and styling hooks. */
  kind?: string;
  /** False when the call's outcome was not ok (for tests and styling). */
  ok?: boolean;
  /** The body; null when the step has nothing to expand. */
  children?: ReactNode;
}) {
  const [mounted, setMounted] = useState(open);
  if (open && !mounted) setMounted(true);
  const running = step.status === "running";
  const failed = step.status === "failed";
  const expandable = children != null;
  const duration = running ? null : formatStepDuration(step.durationMs);
  const end = failed ? failure : stat;
  return (
    <div className="min-w-0 flex-1">
      <button
        type="button"
        data-testid={testId}
        data-status={step.status}
        data-kind={kind}
        data-ok={ok === undefined ? undefined : String(ok)}
        disabled={!expandable}
        aria-expanded={expandable ? open : undefined}
        onClick={onToggle}
        className={`group flex h-6 w-full min-w-0 items-center gap-2 rounded-md px-1 text-left text-[12px] ${
          expandable ? "cursor-pointer hover:bg-[var(--color-bg-hover)]" : "cursor-default"
        }`}
      >
        <Icon className={`h-3.5 w-3.5 flex-none ${iconClassName}`} />
        <span
          className={`min-w-0 flex-none truncate ${
            running ? "chat-live-label font-medium" : "text-[var(--color-text)]"
          }`}
          style={{ maxWidth: "70%" }}
        >
          {title}
        </span>
        {end && (
          <span
            key={`${step.status}-${end}`}
            className={`chat-state-in min-w-0 truncate text-[11px] ${
              failed
                ? FAILED_TONE_CLASS
                : "font-mono tabular-nums text-[var(--color-text-dim)]"
            }`}
          >
            {end}
          </span>
        )}
        <span className="ml-auto flex flex-none items-center gap-2">
          {trailing}
          {duration && (
            <span className="chat-state-in text-[10px] tabular-nums text-[var(--color-text-dim)]">
              {duration}
            </span>
          )}
          {expandable && (
            <ChevronRight
              className={`h-3 w-3 text-[var(--color-text-dim)] transition-transform duration-[var(--chat-motion-state)] ${
                open ? "rotate-90" : ""
              }`}
            />
          )}
        </span>
      </button>
      {expandable && (
        <div className="chat-collapse" data-open={open}>
          <div>{mounted && <div className="mt-1.5 pl-6 pr-1">{children}</div>}</div>
        </div>
      )}
    </div>
  );
}

/** First line of a failure message, trimmed for the row. */
export function failureLine(message: string | null | undefined): string | null {
  const line = (message ?? "").split("\n").map((part) => part.trim()).find(Boolean);
  if (!line) return null;
  return line.length > 120 ? `${line.slice(0, 119)}…` : line;
}
