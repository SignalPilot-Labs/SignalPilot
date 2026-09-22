import type { Thought } from "./thoughts";

export type RunStatus = "queued" | "running" | "completed" | "input_required" | "cancelled" | "failed";

export type RunEvent = {
  run_id: string;
  sequence: number;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type Message = {
  id: string;
  role: string;
  content: string;
  run_id?: string | null;
  sequence: number;
};

/** The `read_signalpilot_chat_view` page after the client merged its cursors. */
export type View = {
  thread_id: string;
  run_id: string;
  chat_url: string;
  status: RunStatus;
  events: RunEvent[];
  messages: Message[];
  next_sequence: number;
  next_message_sequence: number;
  has_more: boolean;
  has_more_messages: boolean;
  error?: string | null;
  question?: string | null;
  raw_error?: string | null;
  stderr?: string | null;
  full_trace?: string | null;
  elapsed_seconds?: number;
  /** Client clock when this page arrived; drives the local elapsed timer. */
  received_at: number;
};

export type Phase = "booting" | "thinking" | "tool" | "writing" | "waiting" | "completed" | "failed" | "cancelled";

export type ToolKind =
  | "table"
  | "table_list"
  | "schema"
  | "validation"
  | "dbt_run"
  | "terminal"
  | "knowledge"
  | "file"
  | "plan"
  | "web"
  | "subagent"
  | "generic";

export type ChipStatus = "running" | "done" | "failed";

export type Chip = {
  id: string;
  kind: ToolKind;
  tool: string;
  /** Short chip text. */
  label: string;
  /** Full present-tense description shown in the Now line on hover. */
  detail: string;
  stat: string;
  status: ChipStatus;
  startedAt: string;
  endedAt: string | null;
};

export type Plan = { done: number; total: number };

export type PlanItemStatus = "pending" | "in_progress" | "completed";

export type PlanItem = { content: string; status: PlanItemStatus; active: string | null };

export type Counts = { queries: number; checks: number; files: number; errors: number; tools: number; rows: number };

export type PulseState = {
  phase: Phase;
  now: string;
  thoughts: Thought[];
  chips: Chip[];
  plan: Plan | null;
  /** The agent's own plan steps from its latest TodoWrite, in order. */
  planItems: PlanItem[];
  counts: Counts;
  question: string | null;
  error: string | null;
  errorDetail: string | null;
  headline: string | null;
  chatUrl: string;
  /** ISO timestamp of the first event, or null before any event. */
  startedAt: string | null;
  /** ISO timestamp of the last event when the run is over. */
  endedAt: string | null;
};

export const ACTIVE_STATUSES: ReadonlySet<string> = new Set(["queued", "running"]);
export const TERMINAL_STATUSES: ReadonlySet<string> = new Set(["completed", "failed", "cancelled"]);

export const isActive = (status: string) => ACTIVE_STATUSES.has(status);
export const isTerminal = (status: string) => TERMINAL_STATUSES.has(status);
