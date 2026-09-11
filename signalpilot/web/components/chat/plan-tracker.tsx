"use client";

import { Check, ChevronDown, ListTodo } from "lucide-react";
import { memo, useState } from "react";
import { composerPlanSummary } from "~/lib/chat-composer-plan";
import type { PlanItem, RunPlan } from "~/lib/chat-run-steps";

/**
 * The agent's published plan (TodoWrite), docked directly above the
 * composer input. The header sits against the input; the checklist opens
 * ABOVE the header, so the dock grows upward from the input. Expanded while
 * the run streams, folded to the one-line summary once it settles; the
 * user's toggle wins until the run state changes again. Purely
 * presentational: state comes from the event stream, so it survives
 * reloads and fixture replays.
 *
 * Surface styling lives in `.chat-plan*` (globals.css). The dock deliberately
 * does NOT share the border/bg-card treatment of the transcript cards, so it
 * reads as part of the input control, not the conversation.
 */

function SegmentBar({ items }: { items: PlanItem[] }) {
  return (
    <div
      aria-hidden
      className="flex h-1 w-24 flex-none gap-px overflow-hidden rounded-full"
    >
      {items.map((item, index) => (
        <span
          key={index}
          className={`h-full flex-1 transition-colors duration-500 ${
            item.status === "completed"
              ? "bg-[var(--color-success)]"
              : item.status === "in_progress"
                ? "chat-dot-live bg-[var(--color-success)]/45"
                : "chat-plan__segment-pending"
          }`}
        />
      ))}
    </div>
  );
}

function ItemMarker({ status }: { status: PlanItem["status"] }) {
  if (status === "completed") {
    return (
      <span className="flex h-4 w-4 flex-none items-center justify-center">
        <Check className="chat-boot-check h-3.5 w-3.5 text-[var(--color-success)]" />
      </span>
    );
  }
  if (status === "in_progress") {
    return (
      <span className="flex h-4 w-4 flex-none items-center justify-center">
        <span className="chat-dot-live h-2 w-2 rounded-full bg-[var(--color-success)]" />
      </span>
    );
  }
  return (
    <span className="flex h-4 w-4 flex-none items-center justify-center">
      <span className="h-2 w-2 rounded-full border border-[var(--color-border-active)]" />
    </span>
  );
}

export const PlanTracker = memo(function PlanTracker({
  plan,
  running = true,
}: {
  plan: RunPlan;
  /** Expanded by default while true; folds to the summary line when the
   * run finishes. The user's own toggle wins until `running` changes. */
  running?: boolean;
}) {
  const [userToggle, setUserToggle] = useState<boolean | null>(null);
  // Reset the manual toggle when the run state flips, so a new run opens
  // the dock and a finished run folds it (React's render-time state reset).
  const [seenRunning, setSeenRunning] = useState(running);
  if (seenRunning !== running) {
    setSeenRunning(running);
    setUserToggle(null);
  }
  const open = userToggle ?? running;
  const done = plan.completed === plan.items.length;
  return (
    <section
      data-testid="chat-plan-tracker"
      data-open={open}
      aria-label="Agent plan"
      className="chat-plan chat-plan--docked chat-boot-in"
    >
      <div className="chat-collapse" data-open={open}>
        <div>
          <ul className="chat-plan__body space-y-1 px-3 py-2.5">
            {plan.items.map((item, index) => (
              <li
                key={`${index}-${item.status}`}
                className="chat-step-in flex items-start gap-2 rounded-md px-1 py-0.5 text-[12px] leading-5"
              >
                <span className="mt-0.5">
                  <ItemMarker status={item.status} />
                </span>
                <span
                  className={
                    item.status === "completed"
                      ? "text-[var(--color-text-dim)] line-through decoration-[var(--color-border-active)] transition-colors duration-300"
                      : item.status === "in_progress"
                        ? "chat-live-label font-medium"
                        : "text-[var(--color-text-muted)] transition-colors duration-300"
                  }
                >
                  {item.status === "in_progress" && item.activeForm
                    ? item.activeForm
                    : item.content}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <button
        type="button"
        aria-expanded={open}
        aria-label={open ? "Collapse the agent plan" : "Expand the agent plan"}
        onClick={() => setUserToggle(!open)}
        className="chat-plan__header flex w-full items-center gap-2.5 px-3 py-2 text-left"
      >
        <ListTodo className="h-3.5 w-3.5 flex-none text-[var(--color-text-dim)]" />
        <span className="chat-plan__eyebrow flex-none text-[10px] font-semibold uppercase tracking-[0.14em]">
          Plan
        </span>
        <span aria-hidden className="flex-none text-[11px] text-[var(--color-text-dim)]">
          ·
        </span>
        <span className="flex-none text-[11px] tabular-nums text-[var(--color-text-muted)]">
          {composerPlanSummary(plan)}
        </span>
        <SegmentBar items={plan.items} />
        {done ? (
          <span className="flex min-w-0 items-center gap-1.5 text-[12px] text-[var(--color-text-muted)]">
            <Check className="chat-boot-check h-3.5 w-3.5 flex-none text-[var(--color-success)]" />
            All steps complete
          </span>
        ) : plan.currentLabel ? (
          <span
            className={`min-w-0 truncate text-[12px] font-medium ${
              running ? "chat-live-label" : "text-[var(--color-text-muted)]"
            }`}
          >
            {plan.currentLabel}
          </span>
        ) : null}
        <ChevronDown
          className={`ml-auto h-3.5 w-3.5 flex-none text-[var(--color-text-dim)] transition-transform ${
            open ? "" : "rotate-180"
          }`}
        />
      </button>
    </section>
  );
});
