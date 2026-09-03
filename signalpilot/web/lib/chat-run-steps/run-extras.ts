import type { StandaloneChatEvent } from "~/lib/api";
import { foldRunSteps } from "./fold-steps";
import { asRecord, text } from "./payload";
import { normalizeToolName } from "./tool-names";
import type {
  DashboardAuthoringProgress,
  PlanItem,
  RunPlan,
  RunStep,
  RunStepSummary,
  RuntimeBootPhase,
  RuntimeBootState,
} from "./types";

export function formatErrorSupportBundle(step: RunStep): string {
  const diagnostics = step.diagnostics
    ? Object.entries(step.diagnostics).map(
        ([key, value]) =>
          `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`,
      )
    : [];
  return [
    step.detail ? `Root cause: ${step.detail}` : "",
    diagnostics.length ? `Diagnostics:\n${diagnostics.join("\n")}` : "",
    step.fullTrace ? `Full trace:\n${step.fullTrace}` : "",
  ]
    .filter(Boolean)
    .join("\n\n");
}

export function activeDashboardAuthoringProgress(
  events: StandaloneChatEvent[],
  runId: string | undefined,
): DashboardAuthoringProgress | null {
  if (!runId) return null;
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.run_id !== runId || event.type !== "tool_completed") {
      continue;
    }
    const dashboard = asRecord(event.payload.dashboard_authoring);
    if (!dashboard) continue;
    const label = dashboard.label;
    if (typeof label !== "string" || !label) return null;
    const phase = dashboard.phase;
    const sessionId = dashboard.authoring_session_id;
    const draftRevision = dashboard.draft_revision;
    return {
      label,
      phase: typeof phase === "string" ? phase : "",
      sessionId: typeof sessionId === "string" && sessionId ? sessionId : null,
      draftRevision: typeof draftRevision === "number" ? draftRevision : 0,
    };
  }
  return null;
}

export function activeDashboardPreviewLabel(
  events: StandaloneChatEvent[],
  runId: string | undefined,
): string | null {
  if (!runId) return null;
  const active = [...foldRunSteps(events, runId)]
    .reverse()
    .find((step) => step.category === "dashboard" && step.status === "running");
  return active?.detail ?? active?.title ?? null;
}

/** Never leave an unresolved cold-boot card in a terminal transcript. */
export function shouldShowRuntimeBoot(
  boot: RuntimeBootState | null,
  running: boolean,
): boolean {
  return Boolean(boot && (running || boot.phase === "ready"));
}

/**
 * Extracts the sandbox boot lifecycle for a run from its `runtime_boot`
 * events. Returns null when the run reused a warm sandbox (no boot events),
 * which is exactly when the boot UI should not render.
 */
export function extractRuntimeBoot(
  events: StandaloneChatEvent[],
  runId: string,
): RuntimeBootState | null {
  let state: RuntimeBootState | null = null;
  for (const event of events) {
    if (event.run_id !== runId || event.type !== "runtime_boot") continue;
    const phase = text(event.payload.phase) as RuntimeBootPhase | null;
    if (!phase) continue;
    if (phase === "ready") {
      if (state) {
        state.phase = "ready";
        state.readyAt = event.created_at;
        const ms = event.payload.boot_ms;
        state.bootMs = typeof ms === "number" && ms >= 0 ? ms : null;
      }
      continue;
    }
    if (state) {
      // A snapshot resume can fall back to a fresh provision; keep the
      // original start time but show the latest real phase.
      state.phase = phase;
    } else {
      state = {
        phase,
        startedAt: event.created_at,
        readyAt: null,
        bootMs: null,
      };
    }
  }
  return state;
}

/**
 * The latest plan the agent published via TodoWrite, for the pinned plan
 * tracker. Subagent TodoWrites are ignored — the tracker shows the main
 * run's plan only. Returns null until the run publishes a plan.
 */
export function extractRunPlan(
  events: StandaloneChatEvent[],
  runId: string,
): RunPlan | null {
  let latest: { sequence: number; input: Record<string, unknown> } | null =
    null;
  for (const event of events) {
    if (event.run_id !== runId || event.type !== "tool_started") continue;
    if (text(event.payload.parent_tool_call_id)) continue;
    const rawTool = text(event.payload.tool);
    if (!rawTool || normalizeToolName(rawTool).tool !== "TodoWrite") continue;
    const input = asRecord(event.payload.input);
    if (!input) continue;
    if (!latest || event.sequence > latest.sequence) {
      latest = { sequence: event.sequence, input };
    }
  }
  if (!latest) return null;
  const todos = Array.isArray(latest.input.todos) ? latest.input.todos : [];
  const items: PlanItem[] = [];
  for (const todo of todos) {
    const record = asRecord(todo);
    const content = text(record?.content);
    if (!content) continue;
    const status = text(record?.status);
    items.push({
      content,
      activeForm: text(record?.activeForm),
      status:
        status === "completed" || status === "in_progress" ? status : "pending",
    });
  }
  if (!items.length) return null;
  const current = items.find((item) => item.status === "in_progress") ?? null;
  return {
    items,
    completed: items.filter((item) => item.status === "completed").length,
    currentLabel: current ? (current.activeForm ?? current.content) : null,
    sequence: latest.sequence,
  };
}

export function summarizeRunSteps(steps: RunStep[]): RunStepSummary {
  // Subagent children count toward the totals — the work happened even
  // though it renders nested under the spawn card.
  const all = steps.flatMap((step) => [step, ...step.children]);
  return {
    total: all.length,
    queries: all.filter((step) => step.category === "sql").length,
    codeRuns: all.filter(
      (step) => step.category === "python" || step.category === "terminal",
    ).length,
    files: all.filter(
      (step) =>
        step.category === "file-write" ||
        step.category === "file-edit" ||
        step.category === "artifact",
    ).length,
    errors: all.filter((step) => step.status === "failed").length,
    running: all.some((step) => step.status === "running"),
  };
}

/** Compact tally for one subagent's child work, e.g. "12 reads · 2 queries". */
export function describeSubagentWork(step: RunStep): string {
  const counts = new Map<string, number>();
  const bump = (label: string) =>
    counts.set(label, (counts.get(label) ?? 0) + 1);
  for (const child of step.children) {
    if (child.category === "sql") bump("query");
    else if (child.category === "file-read") bump("read");
    else if (child.category === "file-write" || child.category === "file-edit")
      bump("edit");
    else if (child.category === "python" || child.category === "terminal")
      bump("run");
    else bump("tool call");
  }
  if (!counts.size) return "starting";
  return [...counts.entries()]
    .map(([label, count]) => `${count} ${label}${count === 1 ? "" : "s"}`)
    .join(" · ");
}

export function formatStepDuration(durationMs: number | null): string | null {
  if (durationMs == null) return null;
  if (durationMs < 100) return "<0.1s";
  if (durationMs < 60_000) return `${(durationMs / 1000).toFixed(1)}s`;
  const minutes = Math.floor(durationMs / 60_000);
  const seconds = Math.round((durationMs % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}
