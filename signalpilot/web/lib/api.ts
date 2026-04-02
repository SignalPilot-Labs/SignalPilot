function getGatewayUrl(): string {
  // Server-side (SSR): always use the env var or Docker internal URL
  if (typeof window === "undefined") {
    return process.env.NEXT_PUBLIC_GATEWAY_URL || "http://gateway:3300";
  }
  // Client-side on localhost: call gateway directly
  const host = window.location.hostname;
  if (host === "localhost" || host === "127.0.0.1") {
    return process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300";
  }
  // Client-side via tunnel/remote: use relative URL so Next.js rewrites proxy to gateway
  return "";
}

const GATEWAY_URL = getGatewayUrl();

function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("sp_api_key");
}

export function setApiKey(key: string | null) {
  if (key) {
    localStorage.setItem("sp_api_key", key);
  } else {
    localStorage.removeItem("sp_api_key");
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const apiKey = getApiKey();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };
  if (apiKey) {
    headers["Authorization"] = `Bearer ${apiKey}`;
  }
  const res = await fetch(`${GATEWAY_URL}${path}`, {
    ...options,
    headers,
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
  request<{ status: string; message: string }>(`/api/connections/${name}/test`, { method: "POST" });
export const getConnectionSchema = (name: string) =>
  request<{
    connection_name: string;
    db_type: string;
    table_count: number;
    tables: Record<string, { schema: string; name: string; columns: { name: string; type: string; nullable: boolean; primary_key?: boolean }[] }>;
  }>(`/api/connections/${name}/schema`);

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

// Audit export
export function getAuditExportUrl(format: "json" | "csv" = "json", eventType?: string, connectionName?: string): string {
  const params = new URLSearchParams({ format });
  if (eventType) params.set("event_type", eventType);
  if (connectionName) params.set("connection_name", connectionName);
  return `${GATEWAY_URL}/api/audit/export?${params}`;
}

// Query
export const executeQuery = (connection_name: string, sql: string, row_limit = 1000) =>
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

// Budget
export const getBudgets = () =>
  request<{ sessions: Record<string, unknown>[]; total_spent_usd: number }>("/api/budget");
export const createBudget = (session_id: string, budget_usd: number) =>
  request<Record<string, unknown>>("/api/budget", {
    method: "POST",
    body: JSON.stringify({ session_id, budget_usd }),
  });
export const getBudget = (session_id: string) =>
  request<Record<string, unknown>>(`/api/budget/${session_id}`);

// Health
export const getHealth = () => request<Record<string, unknown>>("/health");

// Connection Health
export const getConnectionsHealth = () =>
  request<{ connections: import("./types").ConnectionHealthStats[] }>("/api/connections/health");
export const getConnectionHealth = (name: string) =>
  request<import("./types").ConnectionHealthStats>(`/api/connections/${name}/health`);

// Cache
export const getCacheStats = () =>
  request<{ entries: number; max_entries: number; ttl_seconds: number; hits: number; misses: number; hit_rate: number }>("/api/cache/stats");
export const invalidateCache = (connection_name?: string) =>
  request<{ invalidated: number; connection_name: string | null }>(
    `/api/cache/invalidate${connection_name ? `?connection_name=${encodeURIComponent(connection_name)}` : ""}`,
    { method: "POST" },
  );

// PII Detection
export const detectPII = (name: string) =>
  request<{
    connection_name: string;
    tables_scanned: number;
    tables_with_pii: number;
    detections: Record<string, Record<string, string>>;
  }>(`/api/connections/${name}/detect-pii`, { method: "POST" });

// Schema Cache
export const getSchemaCache = () =>
  request<{ cached_connections: number; total_entries: number; ttl_seconds: number }>("/api/schema-cache/stats");
export const invalidateSchemaCache = (name?: string) =>
  request<{ invalidated: number }>(`/api/schema-cache/invalidate${name ? `?connection_name=${encodeURIComponent(name)}` : ""}`, { method: "POST" });

// Tunnels
export const getTunnels = () => request<import("./types").TunnelInfo[]>("/api/tunnels");
export const createTunnel = (t: { local_port: number; label?: string }) =>
  request<import("./types").TunnelInfo>("/api/tunnels", { method: "POST", body: JSON.stringify(t) });
export const getTunnel = (id: string) => request<import("./types").TunnelInfo>(`/api/tunnels/${id}`);
export const deleteTunnel = (id: string) => request<void>(`/api/tunnels/${id}`, { method: "DELETE" });
export const stopTunnel = (id: string) => request<import("./types").TunnelInfo>(`/api/tunnels/${id}/stop`, { method: "POST" });
export const startTunnel = (id: string) => request<import("./types").TunnelInfo>(`/api/tunnels/${id}/start`, { method: "POST" });

// Metrics SSE
export function subscribeMetrics(cb: (data: import("./types").MetricsSnapshot) => void): () => void {
  const es = new EventSource(`${GATEWAY_URL}/api/metrics`);
  es.onmessage = (e) => {
    try { cb(JSON.parse(e.data)); } catch {}
  };
  return () => es.close();
}
