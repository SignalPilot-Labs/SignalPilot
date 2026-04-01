export interface Run {
  id: string;
  started_at: string;
  ended_at: string | null;
  branch_name: string;
  status: RunStatus;
  pr_url: string | null;
  total_tool_calls: number;
  total_cost_usd: number | null;
  total_input_tokens: number | null;
  total_output_tokens: number | null;
  error_message: string | null;
}

export type RunStatus =
  | "running"
  | "paused"
  | "stopped"
  | "completed"
  | "error"
  | "crashed"
  | "killed"
  | "rate_limited";

export interface ToolCall {
  id: number;
  run_id: string;
  ts: string;
  phase: "pre" | "post";
  tool_name: string;
  input_data: Record<string, unknown> | null;
  output_data: Record<string, unknown> | null;
  duration_ms: number | null;
  permitted: boolean;
  deny_reason: string | null;
}

export interface AuditEvent {
  id: number;
  run_id: string;
  ts: string;
  event_type: string;
  details: Record<string, unknown>;
}

export type FeedEvent =
  | { _kind: "tool"; data: ToolCall }
  | { _kind: "audit"; data: AuditEvent }
  | { _kind: "llm_text"; text: string; ts: string }
  | { _kind: "llm_thinking"; text: string; ts: string }
  | { _kind: "control"; text: string; ts: string };

export const STATUS_META: Record<
  RunStatus,
  { label: string; color: string; bg: string; pulse: boolean }
> = {
  running: {
    label: "Running",
    color: "text-emerald-400",
    bg: "bg-emerald-500/15",
    pulse: true,
  },
  paused: {
    label: "Paused",
    color: "text-amber-400",
    bg: "bg-amber-500/15",
    pulse: false,
  },
  stopped: {
    label: "Stopped",
    color: "text-zinc-400",
    bg: "bg-zinc-500/15",
    pulse: false,
  },
  completed: {
    label: "Completed",
    color: "text-sky-400",
    bg: "bg-sky-500/15",
    pulse: false,
  },
  error: {
    label: "Error",
    color: "text-red-400",
    bg: "bg-red-500/15",
    pulse: false,
  },
  crashed: {
    label: "Crashed",
    color: "text-orange-400",
    bg: "bg-orange-500/15",
    pulse: false,
  },
  killed: {
    label: "Killed",
    color: "text-red-400",
    bg: "bg-red-500/15",
    pulse: false,
  },
  rate_limited: {
    label: "Rate Limited",
    color: "text-yellow-400",
    bg: "bg-yellow-500/15",
    pulse: true,
  },
};
