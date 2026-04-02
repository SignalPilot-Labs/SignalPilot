import type { Run, ToolCall, AuditEvent } from "./types";

// FastAPI backend runs on port 3401.
// On localhost: call port 3401 directly.
// Via tunnel/remote: use relative URLs so Next.js rewrites proxy to the backend.
function getApiBase(): string {
  if (typeof window === "undefined") return "http://localhost:3401";
  const host = window.location.hostname;
  if (host === "localhost" || host === "127.0.0.1") {
    return `${window.location.protocol}//${host}:3401`;
  }
  // Remote access — use relative URL, Next.js rewrite proxies to backend
  return "";
}

export async function fetchRuns(): Promise<Run[]> {
  const res = await fetch(`${getApiBase()}/api/runs`);
  if (!res.ok) throw new Error("Failed to fetch runs");
  return res.json();
}

export async function fetchRun(id: string): Promise<Run> {
  const res = await fetch(`${getApiBase()}/api/runs/${id}`);
  if (!res.ok) throw new Error("Failed to fetch run");
  return res.json();
}

export async function fetchToolCalls(
  runId: string,
  limit = 500
): Promise<ToolCall[]> {
  const res = await fetch(`${getApiBase()}/api/runs/${runId}/tools?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch tool calls");
  return res.json();
}

export async function fetchAuditLog(
  runId: string,
  limit = 500
): Promise<AuditEvent[]> {
  const res = await fetch(`${getApiBase()}/api/runs/${runId}/audit?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch audit log");
  return res.json();
}

export async function sendSignal(
  runId: string,
  signal: "pause" | "resume" | "stop",
  payload?: string
): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiBase()}/api/runs/${runId}/${signal}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payload: payload || null }),
  });
  return res.json();
}

export async function injectPrompt(
  runId: string,
  prompt: string
): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiBase()}/api/runs/${runId}/inject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payload: prompt }),
  });
  return res.json();
}

export function createSSE(runId: string): EventSource {
  return new EventSource(`${getApiBase()}/api/stream/${runId}`);
}

export interface AgentHealth {
  status: "idle" | "running" | "unreachable";
  current_run_id: string | null;
  elapsed_minutes?: number | null;
  time_remaining?: string | null;
  session_unlocked?: boolean | null;
  error?: string;
}

export async function fetchAgentHealth(): Promise<AgentHealth> {
  try {
    const res = await fetch(`${getApiBase()}/api/agent/health`);
    return res.json();
  } catch {
    return { status: "unreachable", current_run_id: null };
  }
}

export async function startRun(
  prompt?: string,
  maxBudgetUsd = 0,
  durationMinutes = 0,
  baseBranch = "main"
): Promise<{ ok: boolean; run_id?: string }> {
  const res = await fetch(`${getApiBase()}/api/agent/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt: prompt || null,
      max_budget_usd: maxBudgetUsd,
      duration_minutes: durationMinutes,
      base_branch: baseBranch,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function resumeRun(
  runId: string,
  maxBudgetUsd = 0
): Promise<{ ok: boolean; run_id?: string }> {
  const res = await fetch(`${getApiBase()}/api/agent/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId, max_budget_usd: maxBudgetUsd }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function stopAgentInstant(): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiBase()}/api/agent/stop`, { method: "POST" });
  return res.json();
}

export async function killAgent(): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiBase()}/api/agent/kill`, { method: "POST" });
  return res.json();
}

export async function unlockSession(
  runId: string
): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiBase()}/api/runs/${runId}/unlock`, {
    method: "POST",
  });
  return res.json();
}

export interface DiffFile {
  path: string;
  added: number;
  removed: number;
  status: "added" | "modified" | "deleted" | "renamed";
}

export interface DiffStats {
  files: DiffFile[];
  total_files: number;
  total_added: number;
  total_removed: number;
  source: "stored" | "live" | "agent" | "unavailable";
}

export async function fetchRunDiff(runId: string): Promise<DiffStats> {
  try {
    const res = await fetch(`${getApiBase()}/api/runs/${runId}/diff`);
    if (!res.ok) return { files: [], total_files: 0, total_added: 0, total_removed: 0, source: "unavailable" };
    return res.json();
  } catch {
    return { files: [], total_files: 0, total_added: 0, total_removed: 0, source: "unavailable" };
  }
}

export async function fetchBranches(): Promise<string[]> {
  try {
    const res = await fetch(`${getApiBase()}/api/agent/branches`);
    if (!res.ok) return ["main", "staging"];
    return res.json();
  } catch {
    return ["main", "staging"];
  }
}
