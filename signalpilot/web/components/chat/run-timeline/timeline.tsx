"use client";

import { Fragment, useState } from "react";
import type { RunStep } from "~/lib/chat-run-steps";
import { useRevealCount } from "~/components/chat/use-reveal-count";
import { StepRow } from "./step-row";
import { StepArtifactCards } from "./step-artifact-cards";
import { SubagentRow } from "./subagent-row";

/** Rows a live group shows before folding older ones into "+N earlier". */
export const LIVE_WINDOW = 3;

/**
 * The ordered step list of one activity group, one line per step. While
 * the group is live, new rows pace in one at a time and only the latest
 * LIVE_WINDOW show, older ones folding into a "+N earlier steps" line, so
 * a long chain never grows into a wall. A focus request (chip click)
 * opens that step's row and shows every row.
 */
export function RunTimeline({
  steps,
  groupLive = false,
  focusStepKey = null,
  focusNonce = 0,
}: {
  steps: RunStep[];
  groupLive?: boolean;
  /** Step to expand (chip click). */
  focusStepKey?: string | null;
  /** Bumped per request so the same step can be re-focused. */
  focusNonce?: number;
}) {
  const [showAll, setShowAll] = useState(false);
  const revealed = useRevealCount(steps.length, groupLive);
  if (!steps.length) {
    return (
      <p className="px-1 py-1 text-xs text-[var(--color-text-dim)]">
        Work details will appear as the analysis progresses.
      </p>
    );
  }
  const visible = steps.slice(0, revealed);
  const windowed = groupLive && !showAll && focusStepKey === null;
  const hidden = windowed ? Math.max(0, visible.length - LIVE_WINDOW) : 0;
  const shown = visible.slice(hidden);
  return (
    <ol className="chat-step-rail space-y-1" aria-label="Agent activity">
      {hidden > 0 && (
        <li>
          <button
            type="button"
            data-testid="chat-timeline-earlier"
            onClick={() => setShowAll(true)}
            className="ml-[26px] rounded-md px-1 text-[11px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-muted)]"
          >
            +{hidden} earlier {hidden === 1 ? "step" : "steps"}
          </button>
        </li>
      )}
      {shown.map((step) => (
        <Fragment key={step.key}>
          {step.category === "subagent" ? (
            <SubagentRow
              step={step}
              childTimeline={<RunTimeline steps={step.children} groupLive={groupLive} />}
            />
          ) : (
            <StepRow
              step={step}
              focusRequested={
                focusStepKey === step.key ? Math.max(1, focusNonce) : undefined
              }
            />
          )}
          <StepArtifactCards sequence={step.sequence} />
        </Fragment>
      ))}
    </ol>
  );
}
