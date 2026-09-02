import type { StandaloneChatEvent, StandaloneChatRunStatus } from "~/lib/api";
import { foldRunBlocks } from "./fold-blocks";
import { extractRuntimeBoot } from "./run-extras";
import type { RunBlock, RunStep, RuntimeBootState } from "./types";

/**
 * What the agent is doing right now, derived from the folded run blocks.
 * Drives the live indicator, the composer ring and the typing caret; it is
 * a pure function of the event stream so replayed frames are deterministic.
 */

export type RunLiveState = "booting" | "thinking" | "tool" | "writing" | "idle";

export type RunLiveInfo = {
  state: RunLiveState;
  /** Short present-tense label for the indicator. */
  label: string;
  /** The deepest running tool step while `state === "tool"`; null otherwise. */
  step: RunStep | null;
};

const IDLE: RunLiveInfo = { state: "idle", label: "", step: null };

const isActive = (status: StandaloneChatRunStatus) =>
  status === "queued" || status === "running";

/** The deepest running step: a running subagent's running child wins. */
function deepestRunningStep(steps: RunStep[]): RunStep | null {
  let found: RunStep | null = null;
  for (const step of steps) {
    if (step.status !== "running") continue;
    found = deepestRunningStep(step.children) ?? step;
  }
  return found;
}

export function deriveLiveStateFromBlocks(
  blocks: RunBlock[],
  boot: RuntimeBootState | null,
  status: StandaloneChatRunStatus,
): RunLiveInfo {
  if (!isActive(status)) return IDLE;
  if (boot && boot.phase !== "ready") {
    return { state: "booting", label: "Starting secure runtime", step: null };
  }
  const trailing = blocks.at(-1);
  if (!trailing) {
    return {
      state: "thinking",
      label: status === "queued" ? "Picking up your question" : "Thinking",
      step: null,
    };
  }
  if (trailing.kind === "text") {
    return { state: "writing", label: "Writing", step: null };
  }
  if (trailing.kind === "thinking") {
    return { state: "thinking", label: "Thinking", step: null };
  }
  const step = deepestRunningStep(trailing.steps);
  if (step) {
    return { state: "tool", label: step.detail ?? step.title, step };
  }
  return { state: "thinking", label: "Thinking", step: null };
}

/** Convenience wrapper that folds the events first (memoise in components). */
export function deriveLiveState(
  events: StandaloneChatEvent[],
  runId: string | null | undefined,
  status: StandaloneChatRunStatus,
): RunLiveInfo {
  if (!runId || !isActive(status)) return IDLE;
  return deriveLiveStateFromBlocks(
    foldRunBlocks(events, runId),
    extractRuntimeBoot(events, runId),
    status,
  );
}
