"use client";

import { Fragment } from "react";
import type { RunStep } from "~/lib/chat-run-steps";
import { StepRow } from "./step-row";
import { StepArtifactCards } from "./step-artifact-cards";
import { SubagentRow } from "./subagent-row";

/**
 * The ordered step list of one activity group. `groupLive` and the focus
 * request flow down to each `ToolCard` so density policy (hold-then-fold,
 * pinned trailing table) and chip-click expansion work per step. A step
 * that produced files gets its artifact cards as the next row.
 */
export function RunTimeline({
  steps,
  groupLive = false,
  focusStepKey = null,
  focusNonce = 0,
}: {
  steps: RunStep[];
  groupLive?: boolean;
  /** Step to expand (chip click or the pinned final table). */
  focusStepKey?: string | null;
  /** Bumped per request so the same step can be re-focused. */
  focusNonce?: number;
}) {
  if (!steps.length) {
    return (
      <p className="px-1 py-1 text-xs text-[var(--color-text-dim)]">
        Work details will appear as the analysis progresses.
      </p>
    );
  }
  const lastIndex = steps.length - 1;
  return (
    <ol className="chat-step-rail space-y-1.5" aria-label="Agent activity">
      {steps.map((step, index) => (
        <Fragment key={step.key}>
          {step.category === "subagent" ? (
            <SubagentRow
              step={step}
              childTimeline={<RunTimeline steps={step.children} groupLive={groupLive} />}
            />
          ) : (
            <StepRow
              step={step}
              isLastInGroup={index === lastIndex}
              groupLive={groupLive}
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
