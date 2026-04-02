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
  rate_limit_resets_at: number | null;
  github_repo: string | null;
  custom_prompt: string | null;
  duration_minutes: number | null;
  base_branch: string | null;
}

export interface RepoInfo {
  repo: string;
  run_count: number;
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
  agent_role: "worker" | "ceo";
  tool_use_id: string | null;
  session_id: string | null;
  agent_id: string | null;
}

export interface AuditEvent {
  id: number;
  run_id: string;
  ts: string;
  event_type: string;
  details: Record<string, unknown>;
}

export interface UsageEvent {
  input_tokens: number;
  output_tokens: number;
  total_input_tokens: number;
  total_output_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  ts: string;
}

export type FeedEvent =
  | { _kind: "tool"; data: ToolCall }
  | { _kind: "audit"; data: AuditEvent }
  | { _kind: "llm_text"; text: string; ts: string; agent_role?: "worker" | "ceo" }
  | { _kind: "llm_thinking"; text: string; ts: string; agent_role?: "worker" | "ceo" }
  | { _kind: "control"; text: string; ts: string }
  | { _kind: "usage"; data: UsageEvent };

export const STATUS_META: Record<
  RunStatus,
  { label: string; color: string; bg: string; dot: string; pulse: boolean }
> = {
  running: {
    label: "Running",
    color: "text-[#00ff88]",
    bg: "bg-[#00ff88]/10",
    dot: "bg-[#00ff88]",
    pulse: true,
  },
  paused: {
    label: "Paused",
    color: "text-[#ffaa00]",
    bg: "bg-[#ffaa00]/10",
    dot: "bg-[#ffaa00]",
    pulse: false,
  },
  stopped: {
    label: "Stopped",
    color: "text-[#777]",
    bg: "bg-[#777]/10",
    dot: "bg-[#777]",
    pulse: false,
  },
  completed: {
    label: "Completed",
    color: "text-[#88ccff]",
    bg: "bg-[#88ccff]/10",
    dot: "bg-[#88ccff]",
    pulse: false,
  },
  error: {
    label: "Error",
    color: "text-[#ff4444]",
    bg: "bg-[#ff4444]/10",
    dot: "bg-[#ff4444]",
    pulse: false,
  },
  crashed: {
    label: "Crashed",
    color: "text-[#ff8844]",
    bg: "bg-[#ff8844]/10",
    dot: "bg-[#ff8844]",
    pulse: false,
  },
  killed: {
    label: "Killed",
    color: "text-[#ff4444]",
    bg: "bg-[#ff4444]/10",
    dot: "bg-[#ff4444]",
    pulse: false,
  },
  rate_limited: {
    label: "Rate Limited",
    color: "text-[#ffaa00]",
    bg: "bg-[#ffaa00]/10",
    dot: "bg-[#ffaa00]",
    pulse: true,
  },
};

/* ── Tool Categories ── */
// All 20 tool types from the database, mapped to visual categories
export type ToolCategory =
  | "bash"
  | "read"
  | "write"
  | "edit"
  | "glob"
  | "grep"
  | "agent"
  | "web_search"
  | "web_fetch"
  | "todo"
  | "tool_search"
  | "skill"
  | "playwright_navigate"
  | "playwright_screenshot"
  | "playwright_snapshot"
  | "playwright_click"
  | "playwright_form"
  | "playwright_type"
  | "playwright_evaluate"
  | "session_gate"
  | "default";

export function getToolCategory(toolName: string): ToolCategory {
  const name = toolName.toLowerCase();
  // Exact matches first
  if (name === "bash") return "bash";
  if (name === "read") return "read";
  if (name === "write") return "write";
  if (name === "edit") return "edit";
  if (name === "glob") return "glob";
  if (name === "grep") return "grep";
  if (name === "agent") return "agent";
  if (name === "websearch") return "web_search";
  if (name === "webfetch") return "web_fetch";
  if (name === "todowrite") return "todo";
  if (name === "toolsearch") return "tool_search";
  if (name === "skill") return "skill";
  // MCP Playwright tools
  if (name.includes("browser_navigate")) return "playwright_navigate";
  if (name.includes("browser_take_screenshot")) return "playwright_screenshot";
  if (name.includes("browser_snapshot")) return "playwright_snapshot";
  if (name.includes("browser_click")) return "playwright_click";
  if (name.includes("browser_fill_form") || name.includes("browser_type")) return "playwright_form";
  if (name.includes("browser_evaluate")) return "playwright_evaluate";
  // MCP Session Gate
  if (name.includes("end_session") || name.includes("session_gate")) return "session_gate";
  return "default";
}

export interface ToolMeta {
  label: string;
  border: string;
  bg: string;
  text: string;
  iconColor: string;
}

export const TOOL_COLORS: Record<ToolCategory, ToolMeta> = {
  bash:                  { label: "Bash",          border: "border-l-[#00ff88]",  bg: "bg-[#00ff88]/[0.03]",  text: "text-[#00ff88]",  iconColor: "#00ff88" },
  read:                  { label: "Read",          border: "border-l-[#88ccff]",  bg: "bg-[#88ccff]/[0.03]",  text: "text-[#88ccff]",  iconColor: "#88ccff" },
  write:                 { label: "Write",         border: "border-l-[#cc88ff]",  bg: "bg-[#cc88ff]/[0.03]",  text: "text-[#cc88ff]",  iconColor: "#cc88ff" },
  edit:                  { label: "Edit",          border: "border-l-[#ffcc44]",  bg: "bg-[#ffcc44]/[0.03]",  text: "text-[#ffcc44]",  iconColor: "#ffcc44" },
  glob:                  { label: "Glob",          border: "border-l-[#ff88aa]",  bg: "bg-[#ff88aa]/[0.03]",  text: "text-[#ff88aa]",  iconColor: "#ff88aa" },
  grep:                  { label: "Grep",          border: "border-l-[#88ffcc]",  bg: "bg-[#88ffcc]/[0.03]",  text: "text-[#88ffcc]",  iconColor: "#88ffcc" },
  agent:                 { label: "Agent",         border: "border-l-[#ff8844]",  bg: "bg-[#ff8844]/[0.03]",  text: "text-[#ff8844]",  iconColor: "#ff8844" },
  web_search:            { label: "WebSearch",     border: "border-l-[#44aaff]",  bg: "bg-[#44aaff]/[0.03]",  text: "text-[#44aaff]",  iconColor: "#44aaff" },
  web_fetch:             { label: "WebFetch",      border: "border-l-[#44ccdd]",  bg: "bg-[#44ccdd]/[0.03]",  text: "text-[#44ccdd]",  iconColor: "#44ccdd" },
  todo:                  { label: "Todo",          border: "border-l-[#aabb44]",  bg: "bg-[#aabb44]/[0.03]",  text: "text-[#aabb44]",  iconColor: "#aabb44" },
  tool_search:           { label: "ToolSearch",    border: "border-l-[#aa88ff]",  bg: "bg-[#aa88ff]/[0.03]",  text: "text-[#aa88ff]",  iconColor: "#aa88ff" },
  skill:                 { label: "Skill",         border: "border-l-[#ff66cc]",  bg: "bg-[#ff66cc]/[0.03]",  text: "text-[#ff66cc]",  iconColor: "#ff66cc" },
  playwright_navigate:   { label: "Navigate",      border: "border-l-[#66bbff]",  bg: "bg-[#66bbff]/[0.03]",  text: "text-[#66bbff]",  iconColor: "#66bbff" },
  playwright_screenshot: { label: "Screenshot",    border: "border-l-[#ff99aa]",  bg: "bg-[#ff99aa]/[0.03]",  text: "text-[#ff99aa]",  iconColor: "#ff99aa" },
  playwright_snapshot:   { label: "Snapshot",      border: "border-l-[#ddaa66]",  bg: "bg-[#ddaa66]/[0.03]",  text: "text-[#ddaa66]",  iconColor: "#ddaa66" },
  playwright_click:      { label: "Click",         border: "border-l-[#ff7766]",  bg: "bg-[#ff7766]/[0.03]",  text: "text-[#ff7766]",  iconColor: "#ff7766" },
  playwright_form:       { label: "Form Input",    border: "border-l-[#77ccaa]",  bg: "bg-[#77ccaa]/[0.03]",  text: "text-[#77ccaa]",  iconColor: "#77ccaa" },
  playwright_type:       { label: "Type",          border: "border-l-[#77ccaa]",  bg: "bg-[#77ccaa]/[0.03]",  text: "text-[#77ccaa]",  iconColor: "#77ccaa" },
  playwright_evaluate:   { label: "Evaluate",      border: "border-l-[#bbaa55]",  bg: "bg-[#bbaa55]/[0.03]",  text: "text-[#bbaa55]",  iconColor: "#bbaa55" },
  session_gate:          { label: "Session",       border: "border-l-[#ffffff]",  bg: "bg-[#ffffff]/[0.03]",  text: "text-[#cccccc]",  iconColor: "#ffffff" },
  default:               { label: "Tool",          border: "border-l-[#555]",     bg: "bg-[#555]/[0.03]",     text: "text-[#888]",     iconColor: "#888888" },
};

/* ── Audit Event Types ── */
// All 19 event_types from the database
export type AuditEventType =
  | "usage"
  | "llm_text"
  | "llm_thinking"
  | "round_complete"
  | "rate_limit"
  | "run_started"
  | "sdk_config"
  | "agent_stop"
  | "pr_failed"
  | "session_ended"
  | "pr_created"
  | "killed"
  | "ceo_continuation"
  | "end_session_denied"
  | "worker_assignment"
  | "session_unlocked"
  | "fatal_error"
  | "rate_limit_paused"
  | "stop_requested"
  | "subagent_start"
  | "subagent_complete"
  | "prompt_injected";

export interface AuditEventMeta {
  label: string;
  color: string;
  bg: string;
  iconColor: string;
}

export const AUDIT_EVENT_META: Record<string, AuditEventMeta> = {
  round_complete:      { label: "Round Complete",    color: "text-[#00ff88]",  bg: "bg-[#00ff88]/[0.04]", iconColor: "#00ff88" },
  rate_limit:          { label: "Rate Limit",        color: "text-[#ffaa00]",  bg: "bg-[#ffaa00]/[0.04]", iconColor: "#ffaa00" },
  run_started:         { label: "Run Started",       color: "text-[#88ccff]",  bg: "bg-[#88ccff]/[0.04]", iconColor: "#88ccff" },
  sdk_config:          { label: "SDK Config",        color: "text-[#777]",     bg: "bg-[#777]/[0.04]",    iconColor: "#777777" },
  agent_stop:          { label: "Agent Stopped",     color: "text-[#ff8844]",  bg: "bg-[#ff8844]/[0.04]", iconColor: "#ff8844" },
  pr_failed:           { label: "PR Failed",         color: "text-[#ff4444]",  bg: "bg-[#ff4444]/[0.04]", iconColor: "#ff4444" },
  session_ended:       { label: "Session Ended",     color: "text-[#88ccff]",  bg: "bg-[#88ccff]/[0.04]", iconColor: "#88ccff" },
  pr_created:          { label: "PR Created",        color: "text-[#00ff88]",  bg: "bg-[#00ff88]/[0.04]", iconColor: "#00ff88" },
  killed:              { label: "Killed",            color: "text-[#ff4444]",  bg: "bg-[#ff4444]/[0.04]", iconColor: "#ff4444" },
  ceo_continuation:    { label: "CEO Continuation",  color: "text-[#ff8844]",  bg: "bg-[#ff8844]/[0.04]", iconColor: "#ff8844" },
  end_session_denied:  { label: "Session Denied",    color: "text-[#ffaa00]",  bg: "bg-[#ffaa00]/[0.04]", iconColor: "#ffaa00" },
  worker_assignment:   { label: "Worker Assignment", color: "text-[#cc88ff]",  bg: "bg-[#cc88ff]/[0.04]", iconColor: "#cc88ff" },
  session_unlocked:    { label: "Session Unlocked",  color: "text-[#00ff88]",  bg: "bg-[#00ff88]/[0.04]", iconColor: "#00ff88" },
  fatal_error:         { label: "Fatal Error",       color: "text-[#ff4444]",  bg: "bg-[#ff4444]/[0.04]", iconColor: "#ff4444" },
  rate_limit_paused:   { label: "Rate Limit Paused", color: "text-[#ffaa00]",  bg: "bg-[#ffaa00]/[0.04]", iconColor: "#ffaa00" },
  stop_requested:      { label: "Stop Requested",    color: "text-[#ff8844]",  bg: "bg-[#ff8844]/[0.04]", iconColor: "#ff8844" },
};

/* ── WorkTree Types ── */
export interface FileChange {
  path: string;
  action: "read" | "write" | "edit" | "create" | "delete" | "exec" | "navigate" | "search";
  linesAdded?: number;
  linesRemoved?: number;
  timestamp: string;
  toolCallId?: number;
  toolName?: string;
}

export interface WorkTreeNode {
  name: string;
  path: string;
  type: "file" | "directory";
  children?: WorkTreeNode[];
  changes: FileChange[];
  depth: number;
}

/* ── Settings Types ── */
export interface SettingsStatus {
  configured: boolean;
  has_claude_token: boolean;
  has_git_token: boolean;
  has_github_repo: boolean;
}

export interface Settings {
  claude_token?: string;
  git_token?: string;
  github_repo?: string;
  max_budget_usd?: string;
}

/* ── Parallel Run Types ── */
export interface ParallelRunSlot {
  run_id: string | null;
  container_id: string;
  container_name: string;
  status: "starting" | "running" | "completed" | "stopped" | "error" | "killed";
  prompt: string | null;
  max_budget_usd: number;
  duration_minutes: number;
  base_branch: string;
  started_at: number;
  error_message: string | null;
}

export interface ParallelStatus {
  total_slots: number;
  active: number;
  max_concurrent: number;
  slots: ParallelRunSlot[];
}
