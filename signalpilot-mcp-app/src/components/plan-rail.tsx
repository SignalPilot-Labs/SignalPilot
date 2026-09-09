import { Check } from "lucide-react";
import type { PlanItem } from "../types";

/**
 * The agent's plan on the right: a five-row window over the step list that
 * scrolls so the current step stays near the top, with a mint bar marking
 * it. Completed steps dim with a check; pending steps wait as hollow dots.
 * Nothing here scrolls by hand; the window follows the run.
 */

export const RAIL_ROWS = 5;
export const RAIL_ROW_PX = 26;

/** Index of the step the rail should centre on. */
export function currentPlanIndex(items: PlanItem[]): number {
  const active = items.findIndex((item) => item.status === "in_progress");
  if (active >= 0) return active;
  const pending = items.findIndex((item) => item.status === "pending");
  if (pending >= 0) return pending;
  return Math.max(0, items.length - 1);
}

/** First visible row so the current step sits on the second line when possible. */
export function railOffset(items: PlanItem[], rows = RAIL_ROWS): number {
  const current = currentPlanIndex(items);
  return Math.max(0, Math.min(current - 1, items.length - rows));
}

export function PlanRail({ items }: { items: PlanItem[] }) {
  if (!items.length) return null;
  const current = currentPlanIndex(items);
  const offset = railOffset(items);
  const done = items.filter((item) => item.status === "completed").length;
  return (
    <aside className="rail" aria-label="Plan">
      <div className="rail-head">
        <span>Plan</span>
        <span className="rail-count">{done}/{items.length}</span>
      </div>
      <div className="rail-window" style={{ height: RAIL_ROWS * RAIL_ROW_PX }}>
        <ol className="rail-list" style={{ transform: `translateY(${-offset * RAIL_ROW_PX}px)` }}>
          {items.map((item, index) => {
            const state = index === current && item.status !== "completed" ? "current" : item.status;
            return (
              <li key={`${index}-${item.content}`} className="rail-row" data-state={state} aria-current={state === "current" ? "step" : undefined}>
                <span className="rail-mark" aria-hidden>
                  {item.status === "completed" ? <Check /> : null}
                </span>
                <span className="rail-text">{state === "current" && item.active ? item.active : item.content}</span>
              </li>
            );
          })}
        </ol>
      </div>
    </aside>
  );
}
