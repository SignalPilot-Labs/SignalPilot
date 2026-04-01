const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${GATEWAY_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// Settings
export const getSettings = () => request<import("./types").GatewaySettings>("/api/settings");
export const updateSettings = (s: import("./types").GatewaySettings) =>
  request<import("./types").GatewaySettings>("/api/settings", { method: "PUT", body: JSON.stringify(s) });

// Connections
export const getConnections = () => request<import("./types").ConnectionInfo[]>("/api/connections");
export const createConnection = (c: Record<string, unknown>) =>
  request<import("./types").ConnectionInfo>("/api/connections", { method: "POST", body: JSON.stringify(c) });
export const deleteConnection = (name: string) =>
  request<void>(`/api/connections/${name}`, { method: "DELETE" });
export const testConnection = (name: string) =>
  request<Record<string, unknown>>(`/api/connections/${name}/test`, { method: "POST" });

// Database type metadata
export const getDbTypes = () =>
  request<Array<Record<string, unknown>>>("/api/db-types");

// Schema
export const getConnectionSchema = (name: string, refresh = false) =>
  request<Record<string, unknown>>(`/api/connections/${name}/schema${refresh ? "?refresh=true" : ""}`);

// Sandboxes
export const getSandboxes = () => request<import("./types").SandboxInfo[]>("/api/sandboxes");
export const createSandbox = (s: Record<string, unknown>) =>
  request<import("./types").SandboxInfo>("/api/sandboxes", { method: "POST", body: JSON.stringify(s) });
export const getSandbox = (id: string) => request<import("./types").SandboxInfo>(`/api/sandboxes/${id}`);
export const deleteSandbox = (id: string) =>
  request<void>(`/api/sandboxes/${id}`, { method: "DELETE" });
export const executeSandbox = (id: string, code: string, timeout = 30) =>
  request<import("./types").ExecuteResult>(`/api/sandboxes/${id}/execute`, {
    method: "POST",
    body: JSON.stringify({ code, timeout }),
  });

// Audit
export const getAudit = (params?: Record<string, string | number>) => {
  const qs = params ? "?" + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString() : "";
  return request<{ entries: import("./types").AuditEntry[]; total: number }>(`/api/audit${qs}`);
};

// Health
export const getHealth = () => request<Record<string, unknown>>("/health");

// Metrics SSE
export function subscribeMetrics(cb: (data: import("./types").MetricsSnapshot) => void): () => void {
  const es = new EventSource(`${GATEWAY_URL}/api/metrics`);
  es.onmessage = (e) => {
    try { cb(JSON.parse(e.data)); } catch {}
  };
  return () => es.close();
}
