/**
 * Types for the folded standalone-chat run timeline. The fold itself lives in
 * `fold-steps.ts` / `fold-blocks.ts`; this module is import-cycle free.
 */

import type { ToolResult } from "./tool-result-types";

export type RunStepCategory =
  | "sql"
  | "python"
  | "notebook"
  | "terminal"
  | "file-write"
  | "file-edit"
  | "file-read"
  | "todo"
  | "web"
  | "source"
  | "artifact"
  | "dashboard"
  | "dbt"
  | "plan"
  | "approval"
  | "progress"
  | "subagent"
  | "error"
  | "generic";

export type RunStepStatus = "running" | "succeeded" | "failed" | "info";

export type RunStep = {
  /** Stable key for React rendering. */
  key: string;
  sequence: number;
  category: RunStepCategory;
  status: RunStepStatus;
  /** Human title, e.g. "Queried the warehouse". */
  title: string;
  /** Normalized tool name without the mcp__server__ prefix, if a tool step. */
  tool: string | null;
  /** Which MCP server the tool came from, or "claude-code" for base tools. */
  toolOrigin: "signalpilot" | "notebook" | "chat" | "claude-code" | null;
  input: Record<string, unknown> | null;
  /** SQL attached via the dedicated `sql` event or found in the tool input. */
  sql: string | null;
  /** Python source when the tool executes code. */
  code: string | null;
  /** File path or artifact filename this step produced or touched. */
  file: string | null;
  /** Schema/model/metric reference chips. */
  sources: string[];
  /** Free-form detail line (progress label, completion summary, error). */
  detail: string | null;
  /** Parsed tool output once `tool_completed` lands; null while running. */
  result: ToolResult | null;
  startedAt: string;
  endedAt: string | null;
  durationMs: number | null;
  /** Subagent spawns only: the child steps executed inside the subagent. */
  children: RunStep[];
  /** Subagent spawns only: the agent type (e.g. "Explore"). */
  subagentType: string | null;
  /** Subagent spawns only: the final report the subagent returned. */
  report: string | null;
  /** Subagent spawns only: the subagent's streamed narration so far. */
  liveText: string;
  /** Sanitized support data present only on terminal run errors. */
  fullTrace?: string | null;
  diagnostics?: Record<string, unknown> | null;
};

export type RunStepSummary = {
  total: number;
  queries: number;
  codeRuns: number;
  files: number;
  errors: number;
  running: boolean;
};

export type RunBlock =
  | { kind: "text"; key: string; text: string }
  | { kind: "thinking"; key: string; text: string }
  | { kind: "steps"; key: string; steps: RunStep[] };

export type RuntimeBootPhase = "provisioning" | "resuming" | "ready";

export type RuntimeBootState = {
  phase: RuntimeBootPhase;
  startedAt: string;
  readyAt: string | null;
  bootMs: number | null;
};

export type PlanItemStatus = "pending" | "in_progress" | "completed";

export type PlanItem = {
  content: string;
  /** Present-tense label shown while the item is in progress. */
  activeForm: string | null;
  status: PlanItemStatus;
};

export type RunPlan = {
  items: PlanItem[];
  completed: number;
  /** The in-progress item, preferring its activeForm for display. */
  currentLabel: string | null;
  /** Sequence of the TodoWrite event the plan came from. */
  sequence: number;
};

/** Current real server-side phase for a running dashboard preview tool. */
export type DashboardAuthoringProgress = {
  label: string;
  phase: string;
  sessionId: string | null;
  draftRevision: number;
};
