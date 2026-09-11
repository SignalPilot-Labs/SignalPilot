import type { StandaloneChatEvent, StandaloneChatRunStatus } from "~/lib/api";
import { extractRunPlan, type RunPlan } from "~/lib/chat-run-steps";

/** The plan the composer docks above the input, for the conversation's
 * current run: the running run, or the latest run's final plan. */
export type ComposerPlan = {
  runId: string;
  plan: RunPlan;
  /** The run is still streaming: the dock opens by default. */
  running: boolean;
};

type RunLike = { id: string; status: StandaloneChatRunStatus };

export function isPlanRunStreaming(status: StandaloneChatRunStatus): boolean {
  return status === "queued" || status === "running";
}

/**
 * Selects the composer plan from the same run events the transcript folds.
 * Pure, so rehydration on refresh and fixture replay both derive the same
 * dock state. Null when there is no current run (the empty new-chat page)
 * or the run never published a TodoWrite plan.
 */
export function selectComposerPlan(
  events: StandaloneChatEvent[],
  run: RunLike | null | undefined,
): ComposerPlan | null {
  if (!run?.id) return null;
  const plan = extractRunPlan(events, run.id);
  if (!plan) return null;
  return { runId: run.id, plan, running: isPlanRunStreaming(run.status) };
}

/** One-line summary for the collapsed dock header, e.g. "6/6 done". */
export function composerPlanSummary(plan: RunPlan): string {
  const total = plan.items.length;
  return plan.completed === total
    ? `${plan.completed}/${total} done`
    : `${plan.completed}/${total}`;
}
