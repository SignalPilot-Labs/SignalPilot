"use client";

import { Check, ChevronDown, ListTodo } from "lucide-react";
import { memo, useState } from "react";
import type { PlanItem, RunPlan } from "~/lib/chat-run-steps";

/**
 * The agent's published plan (TodoWrite) as a first-class card in the main
 * chat window. While the run streams it renders expanded (its wrapper pins
 * it to the top of the viewport); once the run finishes it stays in the
 * transcript folded to its one-line summary. Purely presentational — state
 * comes from the event stream so it survives reloads and replays for free.
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
                : "bg-[var(--color-border-active)]"
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
   * run finishes. The user's own toggle always wins. */
  running?: boolean;
}) {
  const [userToggle, setUserToggle] = useState<boolean | null>(null);
  const open = userToggle ?? running;
  const done = plan.completed === plan.items.length;
  return (
    <section
      data-testid="chat-plan-tracker"
      aria-label="Agent plan"
      className="chat-boot-in overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]/95 shadow-lg shadow-black/20 backdrop-blur"
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setUserToggle(!open)}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-[var(--color-bg-hover)]"
      >
        <ListTodo className="h-3.5 w-3.5 flex-none text-[var(--color-text-dim)]" />
        <span className="flex-none text-[10px] font-medium uppercase tracking-[0.14em] text-[var(--color-text-dim)]">
          Plan
        </span>
        <span className="flex-none text-[11px] tabular-nums text-[var(--color-text-muted)]">
          {plan.completed}/{plan.items.length}
        </span>
        <SegmentBar items={plan.items} />
        {done ? (
          <span className="flex min-w-0 items-center gap-1.5 text-[12px] text-[var(--color-text-muted)]">
            <Check className="chat-boot-check h-3.5 w-3.5 flex-none text-[var(--color-success)]" />
            All steps complete
          </span>
        ) : plan.currentLabel ? (
          <span className="chat-live-label min-w-0 truncate text-[12px] font-medium">
            {plan.currentLabel}
          </span>
        ) : null}
        <ChevronDown
          className={`ml-auto h-3.5 w-3.5 flex-none text-[var(--color-text-dim)] transition-transform ${
            open ? "" : "rotate-180"
          }`}
        />
      </button>
      <div className="chat-collapse" data-open={open}>
        <div>
          <ul className="space-y-1 border-t border-[var(--color-border)]/60 px-3 py-2.5">
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
    </section>
  );
});
