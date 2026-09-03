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
import { CardFrame, ErrorBanner, RawResultTab } from "./card-primitives";
import { resolveToolCard, type ToolCardContext } from "./registry";
import { ToolChip } from "./tool-chip";
import { useCardDensity } from "./use-card-density";

const noop = () => undefined;

/**
 * One tool step at its current density. Owns the density policy and
 * renders either the compact chip or the framed card with the
 * definition's Running / Expanded body, plus the failure banner and the
 * raw-output toggle. Rendered by `StepRow` whenever a card resolves.
 */
export const ToolCard = memo(function ToolCard({
  step,
  isLastInGroup = false,
  groupLive = false,
  focusRequested,
}: {
  step: RunStep;
  isLastInGroup?: boolean;
  groupLive?: boolean;
  focusRequested?: boolean | number;
}) {
  const def = resolveToolCard(step);
  const ui = useContext(ChatUiContext);
  // Hooks run unconditionally; a null definition is a caller error handled
  // below by rendering nothing rather than a broken frame.
  const fallbackDef = def ?? FALLBACK_DEF;
  const { density, open, toggle } = useCardDensity({
    step,
    def: fallbackDef,
    isLastInGroup,
    groupLive,
    focusRequested,
  });
  if (!def) return null;

  const running = step.status === "running";
  const failed = step.status === "failed";
  const summary = def.summarize(step);
  const context: ToolCardContext = {
    step,
    result: step.result,
    conversationId: ui?.conversationId ?? null,
    openArtifact: ui?.openArtifact ?? noop,
    isLastInGroup,
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
    >
      <div className="flex items-start gap-2.5">
        <StatusDot status={step.status} />
        <div className="min-w-0 flex-1 pb-1">
          {density === "compact" ? (
            <div className="flex items-center gap-2 pt-px">
              <ToolChip step={step} def={def} onClick={toggle} />
              <ToolTelemetryTime step={step} />
            </div>
          ) : (
            <>
              <CardFrame
                Icon={def.Icon}
                accent={def.accent}
                summary={summary}
                step={step}
                running={running}
                failed={failed}
                open={open}
                onToggle={toggle}
                testId={`chat-tool-card-${def.kind}`}
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
              </CardFrame>
              <div className="mt-1 flex justify-end pr-1">
                <ToolTelemetryTime step={step} />
              </div>
            </>
          )}
          {step.sources.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
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
        </div>
      </div>
    </li>
  );
});

/** Placeholder so hook order is stable when no definition resolves. */
const FALLBACK_DEF = {
  kind: "legacy" as const,
  Icon: Waypoints,
  accent: "neutral" as const,
  summarize: (step: RunStep) => ({ title: step.title, stat: null, ok: true }),
  Running: () => null,
  Expanded: () => null,
};
