"use client";

import { Check, ChevronRight } from "lucide-react";
import { useContext, useEffect, useState } from "react";
import { summarizeRunSteps, type RunStep } from "~/lib/chat-run-steps";
import {
  ArtifactCardBlock,
  StepArtifactCardsContext,
  collectGroupArtifactCards,
} from "./step-artifact-cards";
import { ToolChipStrip } from "~/components/chat/tool-cards/tool-chip";
import { RunTimeline } from "./timeline";

export function describeRunWork(steps: RunStep[]): string {
  const summary = summarizeRunSteps(steps);
  const parts: string[] = [];
  if (summary.queries) {
    parts.push(`${summary.queries} ${summary.queries === 1 ? "query" : "queries"}`);
  }
  if (summary.codeRuns) {
    parts.push(`${summary.codeRuns} code ${summary.codeRuns === 1 ? "run" : "runs"}`);
  }
  if (summary.files) {
    parts.push(`${summary.files} ${summary.files === 1 ? "file" : "files"}`);
  }
  if (summary.errors) {
    parts.push(`${summary.errors} ${summary.errors === 1 ? "error" : "errors"}`);
  }
  const detail = parts.length ? ` · ${parts.join(" · ")}` : "";
  return `${summary.total} ${summary.total === 1 ? "step" : "steps"}${detail}`;
}

/**
 * One tool chain rendered as a collapsible group. While any step runs it
 * shows a live header and its latest one-line rows (see RunTimeline's live
 * window); once the chain completes it settles to the chip strip (one
 * merged pill per kind of work). Nothing inside opens by itself: picking a
 * chip reopens the group with that step expanded. Files the chain produced
 * always render once, in the group footer, so they never move when the
 * group opens or closes.
 */
export function StandardActivityGroup({
  steps,
  live,
}: {
  steps: RunStep[];
  live: boolean;
}) {
  const [userToggle, setUserToggle] = useState<boolean | null>(null);
  const [focus, setFocus] = useState<{ key: string; nonce: number } | null>(null);
  const cardsByStep = useContext(StepArtifactCardsContext);
  const active = live || steps.some((step) => step.status === "running");
  // Reopen automatically if this group starts working again (e.g. retry).
  useEffect(() => {
    if (active) {
      setUserToggle(null);
      setFocus(null);
    }
  }, [active]);
  const open = userToggle ?? active;
  const groupCards = collectGroupArtifactCards(steps, cardsByStep);
  const focusStepKey = focus?.key ?? null;
  const latest = steps[steps.length - 1] ?? null;
  const pick = (key: string) => {
    setUserToggle(true);
    setFocus((previous) => ({ key, nonce: (previous?.nonce ?? 0) + 1 }));
  };
  if (!steps.length && !active) return null;
  return (
    <section
      data-testid="chat-activity-group"
      className="my-3 overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]/60"
    >
      {active ? (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setUserToggle(!open)}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-[var(--color-bg-hover)]"
        >
          <span className="chat-dot-live h-1.5 w-1.5 flex-none rounded-full bg-[var(--color-success)]" />
          <span className="chat-live-label font-medium">
            {latest && latest.status === "running"
              ? (latest.detail ?? latest.title)
              : "Working…"}
          </span>
          <ChevronRight
            className={`ml-auto h-3 w-3 flex-none text-[var(--color-text-dim)] transition-transform ${
              open ? "rotate-90" : ""
            }`}
          />
        </button>
      ) : (
        <div className="relative flex items-center gap-2 px-3 py-2 text-xs hover:bg-[var(--color-bg-hover)]">
          {/* The toggle stretches over the whole header (see
              chat-artifact-card.tsx); the chips sit above it. */}
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setUserToggle(!open)}
            className="flex flex-none cursor-pointer items-center active:transform-none!"
          >
            <Check className="h-3.5 w-3.5 flex-none text-[var(--color-success)]/80" />
            <span className="sr-only">Worked through {describeRunWork(steps)}</span>
            <span aria-hidden="true" className="absolute inset-0 cursor-pointer" />
          </button>
          <ToolChipStrip steps={steps} onPick={pick} className="relative z-[1] flex-1" />
          <ChevronRight
            aria-hidden="true"
            className={`pointer-events-none ml-auto h-3 w-3 flex-none text-[var(--color-text-dim)] transition-transform ${
              open ? "rotate-90" : ""
            }`}
          />
        </div>
      )}
      <div className="chat-collapse" data-open={open}>
        <div>
          <div className="border-t border-[var(--color-border)] px-3 py-2">
            <StepArtifactCardsContext.Provider value={null}>
              <RunTimeline
                steps={steps}
                groupLive={active}
                focusStepKey={focusStepKey}
                focusNonce={focus?.nonce ?? 0}
              />
            </StepArtifactCardsContext.Provider>
          </div>
        </div>
      </div>
      <ArtifactCardBlock
        cards={groupCards}
        testId="chat-group-artifact-cards"
        className="border-t border-[var(--color-border)] px-3 py-3"
      />
    </section>
  );
}

export function ActivityGroup({ steps, live }: { steps: RunStep[]; live: boolean }) {
  return <StandardActivityGroup steps={steps} live={live} />;
}
