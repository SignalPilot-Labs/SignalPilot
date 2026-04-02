import type { Run, ToolCall, AuditEvent, RepoInfo } from "./types";

// All /api/* requests are routed to FastAPI by nginx on the same port.
function getApiBase(): string {
  if (typeof window === "undefined") return "http://localhost:3401";
  return "";
}

export async function fetchRuns(repo?: string): Promise<Run[]> {
  const params = repo ? `?repo=${encodeURIComponent(repo)}` : "";
  const res = await fetch(`${getApiBase()}/api/runs${params}`);
  if (!res.ok) throw new Error("Failed to fetch runs");
  return res.json();
}

export async function fetchRepos(): Promise<RepoInfo[]> {
  try {
    const res = await fetch(`${getApiBase()}/api/repos`);
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

export async function setActiveRepo(repo: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiBase()}/api/repos/active`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo }),
  });
  return res.json();
}

export async function fetchRun(id: string): Promise<Run> {
  const res = await fetch(`${getApiBase()}/api/runs/${id}`);
  if (!res.ok) throw new Error("Failed to fetch run");
  return res.json();
}

export async function fetchToolCalls(
  runId: string,
  limit = 500,
): Promise<ToolCall[]> {
  const res = await fetch(
    `${getApiBase()}/api/runs/${runId}/tools?limit=${limit}`,
  );
  if (!res.ok) throw new Error("Failed to fetch tool calls");
  return res.json();
}

export async function fetchAuditLog(
  runId: string,
  limit = 500,
): Promise<AuditEvent[]> {
  const res = await fetch(
    `${getApiBase()}/api/runs/${runId}/audit?limit=${limit}`,
  );
  if (!res.ok) throw new Error("Failed to fetch audit log");
  return res.json();
}

export function createSSE(runId: string): EventSource {
  return new EventSource(`${getApiBase()}/api/stream/${runId}`);
}

export interface PollResult {
  tool_calls: ToolCall[];
  audit_events: AuditEvent[];
}

export async function pollEvents(
  runId: string,
  afterTool: number,
  afterAudit: number,
): Promise<PollResult> {
  const res = await fetch(
    `${getApiBase()}/api/poll/${runId}?after_tool=${afterTool}&after_audit=${afterAudit}`,
  );
  if (!res.ok) throw new Error("Failed to poll events");
  return res.json();
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
    if (!res.ok)
      return {
        files: [],
        total_files: 0,
        total_added: 0,
        total_removed: 0,
        source: "unavailable",
      };
    return res.json();
  } catch {
    return {
      files: [],
      total_files: 0,
      total_added: 0,
      total_removed: 0,
      source: "unavailable",
    };
  }
}

export async function fetchBranches(repo?: string): Promise<string[]> {
  try {
    const params = repo ? `?repo=${encodeURIComponent(repo)}` : "";
    const res = await fetch(`${getApiBase()}/api/agent/branches${params}`);
    if (!res.ok) return ["main"];
    return res.json();
  } catch {
    return ["main"];
  }
}
