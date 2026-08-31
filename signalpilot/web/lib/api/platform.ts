// Settings, API keys, sandboxes, audit, query, budgets, notebook sessions,
// plan usage, health, and metrics.

import { GATEWAY_URL, _getAuthHeader, request } from "./client";

// Settings
export const getSettings = () =>
  request<import("../types").GatewaySettings>("/api/settings");
export const updateSettings = (s: import("../types").GatewaySettings) =>
  request<import("../types").GatewaySettings>("/api/settings", {
    method: "PUT",
    body: JSON.stringify(s),
  });

// The following functions support organization API keys.
export const getApiKeys = () =>
  request<
    {
      id: string;
      name: string;
      prefix: string;
      scopes: string[];
      created_at: string;
      last_used_at: string | null;
    }[]
  >("/api/keys");
export const createApiKey = (name: string, scopes: string[]) =>
  request<{
    id: string;
    name: string;
    prefix: string;
    scopes: string[];
    created_at: string;
    last_used_at: string | null;
    raw_key: string;
  }>("/api/keys", {
    method: "POST",
    body: JSON.stringify({ name, scopes }),
  });
export const deleteApiKey = (keyId: string) =>
  request<void>(`/api/keys/${keyId}`, { method: "DELETE" });

// Sandboxes
export const getSandboxes = () =>
  request<import("../types").SandboxInfo[]>("/api/sandboxes");
export const createSandbox = (s: Record<string, unknown>) =>
  request<import("../types").SandboxInfo>("/api/sandboxes", {
    method: "POST",
    body: JSON.stringify(s),
  });
export const getSandbox = (id: string) =>
  request<import("../types").SandboxInfo>(`/api/sandboxes/${id}`);
export const deleteSandbox = (id: string) =>
  request<void>(`/api/sandboxes/${id}`, { method: "DELETE" });
export const executeSandbox = (id: string, code: string, timeout = 30) =>
  request<import("../types").ExecuteResult>(`/api/sandboxes/${id}/execute`, {
    method: "POST",
    body: JSON.stringify({ code, timeout }),
  });

// The following functions support audit records.
export const getAudit = (params?: Record<string, string | number>) => {
  const qs = params
    ? "?" +
      new URLSearchParams(
        Object.entries(params).map(([k, v]) => [k, String(v)]),
      ).toString()
    : "";
  return request<{ entries: import("../types").AuditEntry[]; total: number }>(
    `/api/audit${qs}`,
  );
};

// Audit export
export function getAuditExportUrl(
  format: "json" | "csv" = "json",
  eventType?: string,
  connectionName?: string,
): string {
  const params = new URLSearchParams({ format });
  if (eventType) params.set("event_type", eventType);
  if (connectionName) params.set("connection_name", connectionName);
  return `${GATEWAY_URL}/api/audit/export?${params}`;
}

// Query
export const executeQuery = (
  connection_name: string,
  sql: string,
  row_limit = 1000,
) =>
  request<{
    rows: Record<string, unknown>[];
    row_count: number;
    tables: string[];
    execution_ms: number;
    sql_executed: string;
  }>("/api/query", {
    method: "POST",
    body: JSON.stringify({ connection_name, sql, row_limit }),
  });

// The following functions support budgets.
export const getBudgets = () =>
  request<{ sessions: Record<string, unknown>[]; total_spent_usd: number }>(
    "/api/budget",
  );
export const createBudget = (session_id: string, budget_usd: number) =>
  request<Record<string, unknown>>("/api/budget", {
    method: "POST",
    body: JSON.stringify({ session_id, budget_usd }),
  });
export const getBudget = (session_id: string) =>
  request<Record<string, unknown>>(`/api/budget/${session_id}`);

// The following functions support notebook sessions (Runtime v2: compute is a
// sandbox behind the gateway proxy; the browser only ever sees the proxy path).
// Credentials and upstream URLs are absent from frontend JavaScript.
export type NotebookSession = {
  id: string;
  status: string; // creating | running | snapshotted | stopped | error
  project_id: string | null;
  branch: string | null;
  backend: string;
  notebook_url: string | null;
  last_ping: number | null;
  created_at: number;
};

export const createNotebookSession = (
  body: { project_id?: string | null; branch?: string } = {},
) =>
  request<NotebookSession>("/api/notebook-sessions", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getNotebookSession = () =>
  request<NotebookSession | null>("/api/notebook-sessions");

export const deleteNotebookSession = () =>
  request<void>("/api/notebook-sessions", { method: "DELETE" });

export const pingNotebookSession = (sessionId: string) =>
  request<void>(
    `/api/notebook-sessions/${encodeURIComponent(sessionId)}/ping`,
    {
      method: "POST",
    },
  );

export type AnalysisTrail = {
  id: string;
  org_id: string;
  source: string;
  request_id: string;
  thread_id: string;
  runtime_session_id: string | null;
  project_id: string;
  branch: string;
  default_branch: string;
  notebook_path: string;
  status: string;
  latest_commit_sha: string | null;
  source_url: string | null;
  source_thread_id: string | null;
  source_request_id: string | null;
  analysis_user_id: string | null;
  metadata: Record<string, unknown>;
  created_at: number;
  updated_at: number;
};

export const resolveAnalysisTrail = (params: {
  session_id?: string;
  file?: string;
}) => {
  const qs = new URLSearchParams();
  if (params.session_id) qs.set("session_id", params.session_id);
  if (params.file) qs.set("file", params.file);
  return request<AnalysisTrail>(
    `/api/analysis-trails/resolve?${qs.toString()}`,
  );
};

// The following function returns gateway health.
export const getHealth = () => request<Record<string, unknown>>("/health");

// The following functions support plan limits and usage.
export interface PlanUsage {
  tier: string;
  limits: {
    connections: number | "unlimited";
    users: number | "unlimited";
    api_keys: number | "unlimited";
    queries_per_day: number | "unlimited";
    audit_retention_days: number | "unlimited";
  };
  usage: {
    connections: number;
    api_keys: number;
    queries_today: number;
  };
  features: {
    pii_redaction: boolean;
    byok: boolean;
    sso: boolean;
    budget_controls: boolean;
    audit_export: boolean;
  };
}
export const getPlan = () => request<PlanUsage>("/api/plan");

// Metrics SSE (uses fetch instead of EventSource so we can send auth headers)
export function subscribeMetrics(
  cb: (data: import("../types").MetricsSnapshot) => void,
): () => void {
  let aborted = false;
  const controller = new AbortController();

  (async () => {
    // Wait for authentication before each connection attempt.
    for (let attempt = 0; attempt < 10 && !aborted; attempt++) {
      const authHeader = await _getAuthHeader();
      if (!authHeader) {
        // Wait and retry while Clerk loads.
        await new Promise((r) => setTimeout(r, 1000));
        continue;
      }

      try {
        const res = await fetch(`${GATEWAY_URL}/api/metrics`, {
          headers: { Accept: "text/event-stream", Authorization: authHeader },
          signal: controller.signal,
        });
        if (res.status === 401 || res.status === 403) {
          // Retry when the token is expired or unavailable.
          await new Promise((r) => setTimeout(r, 2000));
          continue;
        }
        if (!res.ok || !res.body) return;

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";

        while (!aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";
          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                cb(JSON.parse(line.slice(6)) as any);
              } catch {}
            }
          }
        }
        return; // Clean exit
      } catch {
        if (aborted) return;
        await new Promise((r) => setTimeout(r, 2000));
      }
    }
  })();

  return () => {
    aborted = true;
    controller.abort();
  };
}
