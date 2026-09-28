"use client";

import { Waypoints } from "lucide-react";
import { memo, useContext } from "react";
import { ChatUiContext } from "~/components/chat/chat-ui-context";
import {
  StatusDot,
  ToolTelemetryTime,
} from "~/components/chat/run-timeline/step-row";
import type { RunStep } from "~/lib/chat-run-steps";
import "./tool-cards.css";
// Registers every card definition (side effect) before the first resolve.
import "./cards";
import { failureLine, StepLine } from "~/components/chat/run-timeline/step-line";
import { ErrorBanner, RawResultTab } from "./card-primitives";
import { resolveToolCard, type ToolCardContext } from "./registry";
import { useCardDensity } from "./use-card-density";

const noop = () => undefined;

/**
 * One tool step: the shared one-line `StepLine` (icon, the agent's
 * description or the tool name, stat, time) with the definition's body
 * below it. The body opens only when the user clicks the row or picks the
 * step's chip in the group header; the row itself keeps one height while
 * the step runs, finishes or fails. Rendered by `StepRow` whenever a card
 * definition resolves.
 */
export const ToolCard = memo(function ToolCard({
  step,
  focusRequested,
}: {
  step: RunStep;
  /** Kept for callers; the density policy no longer depends on them. */
  isLastInGroup?: boolean;
  groupLive?: boolean;
  focusRequested?: boolean | number;
}) {
  const def = resolveToolCard(step);
  const ui = useContext(ChatUiContext);
  const { density, open, toggle } = useCardDensity({ step, focusRequested });
  if (!def) return null;

  const running = step.status === "running";
  const failed = step.status === "failed";
  const summary = def.summarize(step);
  const context: ToolCardContext = {
    step,
    result: step.result,
    conversationId: ui?.conversationId ?? null,
    openArtifact: ui?.openArtifact ?? noop,
    isLastInGroup: false,
  };
  const errorMessage = step.result?.errorMessage ?? step.detail;
  // The text card's body IS the raw output; do not show it twice.
  const showRaw = step.result?.kind !== "text";

  return (
    <li
      data-testid="chat-tool-card"
      data-kind={def.kind}
      data-density={density}
      data-tool={step.tool ?? undefined}
      className="chat-step-in relative"
      data-accent={def.accent}
    >
      <div className="flex items-start gap-2.5">
        <StatusDot key={step.status} status={step.status} />
        <StepLine
          step={step}
          Icon={def.Icon}
          iconClassName="chat-tool-accent-text"
          title={summary.title}
          stat={running ? null : summary.stat}
          failure={failureLine(errorMessage) ?? "Failed"}
          open={open}
          onToggle={toggle}
          trailing={<ToolTelemetryTime step={step} />}
          testId="chat-tool-chip"
          kind={def.kind}
          ok={!failed && summary.ok}
        >
          <div
            data-testid={`chat-tool-card-${def.kind}`}
            className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)]"
          >
            {running ? (
              <def.Running {...context} />
            ) : (
              <>
                <def.Expanded {...context} />
                {failed && <ErrorBanner message={errorMessage} />}
                {showRaw && <RawResultTab result={step.result} />}
              </>
            )}
          </div>
        </StepLine>
      </div>
      {step.sources.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1.5 pl-[34px]">
          {step.sources.map((source) => (
            <span
              key={source}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-text-muted)]"
            >
              <Waypoints className="h-2.5 w-2.5 text-[var(--color-text-dim)]" />
              {source}
            </span>
          ))}
        </div>
      )}
    </li>
  );
});
