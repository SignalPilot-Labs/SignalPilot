"use client";

import { AlertCircle, Check, ChevronRight, LayoutDashboard } from "lucide-react";
import { useContext, useEffect, useState } from "react";
import { summarizeRunSteps, type RunStep } from "~/lib/chat-run-steps";
import { DashboardPreviewDetails } from "./step-body";
import {
  ArtifactCardBlock,
  StepArtifactCardsContext,
  collectGroupArtifactCards,
} from "./step-artifact-cards";
import { cardKindForStep } from "~/components/chat/tool-cards/registry-tools";
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

export function DashboardPreviewActivityCard({
  step,
  live,
}: {
  step: RunStep;
  live: boolean;
}) {
  const [userToggle, setUserToggle] = useState<boolean | null>(null);
  const active = live || step.status === "running";
  useEffect(() => {
    if (active) setUserToggle(null);
  }, [active]);
  const open = userToggle ?? active;
  const failed = step.status === "failed";
  const phase = active
    ? (step.detail ?? "Preparing governed dashboard preview…")
    : failed
      ? (step.detail ?? "Dashboard preview could not be created")
      : "Governed preview ready for review";

  return (
    <section
      data-testid="dashboard-preview-activity"
      className={`my-3 overflow-hidden rounded-xl border bg-[var(--color-bg-card)]/60 ${
        active
          ? "border-[var(--color-success)]/25"
          : failed
            ? "border-[var(--color-error)]/30"
            : "border-[var(--color-border)]"
      }`}
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setUserToggle(!open)}
        className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left hover:bg-[var(--color-bg-hover)]"
      >
        <span
          className={`flex h-8 w-8 flex-none items-center justify-center rounded-lg border bg-[var(--color-bg-input)] ${
            active
              ? "border-[var(--color-success)]/30"
              : failed
                ? "border-[var(--color-error)]/30"
                : "border-[var(--color-border)]"
          }`}
        >
          <LayoutDashboard
            className={`h-4 w-4 ${
              active
                ? "text-[var(--color-success)]"
                : failed
                  ? "text-[var(--color-error)]"
                  : "text-[var(--color-text-muted)]"
            }`}
          />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[9px] font-medium uppercase tracking-[0.16em] text-[var(--color-text-dim)]">
            Dashboard preview
          </span>
          <span
            className={`block truncate text-[12px] font-medium ${
              active
                ? "chat-live-label"
                : failed
                  ? "text-[var(--color-error)]"
                  : "text-[var(--color-text)]"
            }`}
          >
            {phase}
          </span>
        </span>
        <span className="ml-auto flex flex-none items-center gap-1.5 text-[10px] text-[var(--color-text-dim)]">
          {active ? (
            <>
              <span className="chat-dot-live h-1.5 w-1.5 rounded-full bg-[var(--color-success)]" />
              <span>Live</span>
            </>
          ) : failed ? (
            <>
              <AlertCircle className="h-3 w-3 text-[var(--color-error)]" />
              <span>Failed</span>
            </>
          ) : (
            <>
              <Check className="h-3 w-3 text-[var(--color-success)]/80" />
              <span>Ready</span>
            </>
          )}
          <ChevronRight
            className={`ml-0.5 h-3 w-3 transition-transform ${
              open ? "rotate-90" : ""
            }`}
          />
        </span>
      </button>
      <div className="chat-collapse" data-open={open}>
        <div>
          <div className="border-t border-[var(--color-border)]">
            <DashboardPreviewDetails step={step} />
          </div>
        </div>
      </div>
    </section>
  );
}

/** The last step of a group whose result is (or will be) a table. */
function lastTableStep(steps: RunStep[]): RunStep | null {
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    if (cardKindForStep(steps[index]) === "table") return steps[index];
  }
  return null;
}

/**
 * One tool chain rendered as a collapsible group: expanded with a live
 * shimmer header while any of its steps run, collapsing to a chip strip
 * (one merged pill per kind of work) once the chain completes and the
 * agent moves on. Picking a chip reopens the group with that card
 * expanded. The final group of a completed run that ends in a table stays
 * open with the table expanded and the other cards compact.
 */
export function StandardActivityGroup({
  steps,
  live,
  isFinalGroup = false,
  runCompleted = false,
}: {
  steps: RunStep[];
  live: boolean;
  /** This group is the last steps block of its run. */
  isFinalGroup?: boolean;
  /** The run has reached a terminal status. */
  runCompleted?: boolean;
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
  const pinnedTable =
    !active && isFinalGroup && runCompleted ? lastTableStep(steps) : null;
  const open = userToggle ?? (active || pinnedTable !== null);
  // A collapsed group hides its step rows, so the files it produced move
  // to a footer under the header until the group is reopened. The inner
  // rows get no cards meanwhile, so a file never renders twice.
  const hoistedCards = open ? [] : collectGroupArtifactCards(steps, cardsByStep);
  const focusStepKey = focus?.key ?? pinnedTable?.key ?? null;
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
          <div className="border-t border-[var(--color-border)] px-3 py-3">
            <StepArtifactCardsContext.Provider value={open ? cardsByStep : null}>
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
        cards={hoistedCards}
        testId="chat-group-artifact-cards"
        className="border-t border-[var(--color-border)] px-3 py-3"
      />
    </section>
  );
}

export function ActivityGroup({
  steps,
  live,
  isFinalGroup = false,
  runCompleted = false,
}: {
  steps: RunStep[];
  live: boolean;
  isFinalGroup?: boolean;
  runCompleted?: boolean;
}) {
  const dashboardStep =
    steps.length === 1 && steps[0]?.category === "dashboard" ? steps[0] : null;
  return dashboardStep ? (
    <DashboardPreviewActivityCard step={dashboardStep} live={live} />
  ) : (
    <StandardActivityGroup
      steps={steps}
      live={live}
      isFinalGroup={isFinalGroup}
      runCompleted={runCompleted}
    />
  );
}
