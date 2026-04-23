const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300";
const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";

// ─── Cloud mode: Clerk token getter ─────────────────────────────────────────
// Set by auth-context when Clerk is loaded so gateway requests use JWT auth.
// _clerkReadyPromise lets early requests wait for Clerk to initialize instead
// of firing without auth and failing with 401.
let _clerkGetToken: (() => Promise<string | null>) | null = null;
let _resolveClerkReady: (() => void) | null = null;
const _clerkReadyPromise: Promise<void> | null = IS_CLOUD_MODE
  ? new Promise<void>((resolve) => { _resolveClerkReady = resolve; })
  : null;

export function setClerkTokenGetter(getter: () => Promise<string | null>) {
  _clerkGetToken = getter;
  if (_resolveClerkReady) {
    _resolveClerkReady();
    _resolveClerkReady = null;
  }
}

// ─── Local mode: auto-fetch local API key ───────────────────────────────────
let _localKeyPromise: Promise<string | null> | null = null;

function _fetchLocalKey(): Promise<string | null> {
  if (typeof window === "undefined") return Promise.resolve(null);
  return fetch("/api/local-key")
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      if (data?.key) {
        localStorage.setItem("sp_api_key", data.key);
        return data.key as string;
      }
      return null;
    })
    .catch(() => null);
}

function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  const stored = localStorage.getItem("sp_api_key");
  if (stored) return stored;
  if (!_localKeyPromise) {
    _localKeyPromise = _fetchLocalKey();
  }
  return null;
}

export function setApiKey(key: string | null) {
  if (key) {
    localStorage.setItem("sp_api_key", key);
  } else {
    localStorage.removeItem("sp_api_key");
  }
}

// ─── Unified request function ───────────────────────────────────────────────

async function _getAuthHeader(): Promise<string | null> {
  // Cloud mode: wait for Clerk to initialize, then use JWT
  if (IS_CLOUD_MODE) {
    if (_clerkReadyPromise && !_clerkGetToken) {
      // Wait up to 10s for Clerk to load — avoids firing unauthenticated requests
      await Promise.race([_clerkReadyPromise, new Promise((r) => setTimeout(r, 10_000))]);
    }
    if (_clerkGetToken) {
      const token = await _clerkGetToken();
      if (token) return `Bearer ${token}`;
    }
    return null;
  }
  // Local mode: use sp_ API key
  let apiKey = getApiKey();
  if (!apiKey && _localKeyPromise) {
    apiKey = await _localKeyPromise;
  }
  if (apiKey) return `Bearer ${apiKey}`;
  return null;
}

async function request<T>(path: string, options?: RequestInit, _retried = false): Promise<T> {
  const authHeader = await _getAuthHeader();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };
  if (authHeader) {
    headers["Authorization"] = authHeader;
  }
  const res = await fetch(`${GATEWAY_URL}${path}`, {
    ...options,
    headers,
  });
  // On 401/403, clear stale credentials and retry once
  if ((res.status === 401 || res.status === 403) && !_retried) {
    localStorage.removeItem("sp_api_key");
    _localKeyPromise = null;
    // In cloud mode, the Clerk token getter will provide a fresh token on retry
    // In local mode, re-fetch the local key
    if (!IS_CLOUD_MODE) {
      _localKeyPromise = _fetchLocalKey();
      await _localKeyPromise;
    }
    return request<T>(path, options, true);
  }
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
export const updateConnection = (name: string, updates: Record<string, unknown>) =>
  request<import("./types").ConnectionInfo>(`/api/connections/${name}`, { method: "PUT", body: JSON.stringify(updates) });
export const deleteConnection = (name: string) =>
  request<void>(`/api/connections/${name}`, { method: "DELETE" });
export const refreshConnectionSchema = (name: string) =>
  request<{ connection_name: string; table_count: number; message: string; refreshed_at?: number; next_refresh_in?: number | null }>(
    `/api/connections/${name}/schema/refresh`, { method: "POST" }
  );
export const getSchemaRefreshStatus = (name: string) =>
  request<{
    connection_name: string;
    schema_refresh_interval: number | null;
    last_schema_refresh: number | null;
    next_refresh_at: number | null;
    cached: boolean;
    cached_table_count: number;
    fingerprint: string | null;
  }>(`/api/connections/${name}/schema/refresh-status`);
export const testConnection = (name: string) =>
  request<{
    status: string;
    message: string;
    phases?: { phase: string; status: string; message: string; duration_ms?: number }[];
    total_duration_ms?: number;
  }>(`/api/connections/${name}/test`, { method: "POST" });
export const getConnectionSchema = (name: string) =>
  request<{
    connection_name: string;
    db_type: string;
    table_count: number;
    tables: Record<string, {
      schema: string;
      name: string;
      columns: { name: string; type: string; nullable: boolean; primary_key?: boolean; comment?: string; stats?: { distinct_count?: number; distinct_fraction?: number } }[];
      foreign_keys?: { column: string; references_schema?: string; references_table: string; references_column: string }[];
      indexes?: { name: string; definition?: string; columns?: string; unique?: boolean }[];
      row_count?: number;
      description?: string;
      engine?: string;
      sorting_key?: string;
    }>;
  }>(`/api/connections/${name}/schema`);

export const cloneConnection = (name: string, newName: string) =>
  request<import("./types").ConnectionInfo>(`/api/connections/${name}/clone?new_name=${encodeURIComponent(newName)}`, { method: "POST" });
export const explainQuery = (connection_name: string, sql: string, row_limit = 1000) =>
  request<{
    connection_name: string;
    sql: string;
    tables: string[];
    estimated_rows: number;
    estimated_usd: number;
    is_expensive: boolean;
    warning: string | null;
    plan: string | null;
  }>("/api/query/explain", {
    method: "POST",
    body: JSON.stringify({ connection_name, sql, row_limit }),
  });
export const searchConnectionSchema = (name: string, query: string) =>
  request<{
    connection_name: string;
    query: string;
    result_count: number;
    total_tables: number;
    tables: Record<string, {
      schema: string;
      name: string;
      columns: { name: string; type: string; nullable: boolean; primary_key?: boolean }[];
      foreign_keys?: { column: string; references_table: string; references_column: string }[];
      _matched_columns?: string[];
      _relevance_score?: number;
    }>;
  }>(`/api/connections/${name}/schema/search?q=${encodeURIComponent(query)}`);

// Column Exploration (ReFoRCE Spider2.0 pattern)
export const exploreColumns = (name: string, table: string, columns?: string[], options?: { include_stats?: boolean; include_values?: boolean; value_limit?: number }) =>
  request<{
    table: string;
    table_type: string;
    row_count: number;
    columns_explored: number;
    columns: {
      name: string;
      type: string;
      nullable: boolean;
      primary_key: boolean;
      comment?: string;
      schema_stats?: { distinct_count?: number; distinct_fraction?: number };
      value_stats?: { min: unknown; max: unknown; avg: number | null };
      sample_values?: string[];
    }[];
  }>(`/api/connections/${name}/schema/explore-columns`, {
    method: "POST",
    body: JSON.stringify({
      table,
      columns: columns || [],
      include_stats: options?.include_stats ?? true,
      include_values: options?.include_values ?? true,
      value_limit: options?.value_limit ?? 10,
    }),
  });

// Column Name Correction
export const correctColumns = (name: string, table: string, columns: string[], threshold = 0.5) =>
  request<{
    table: string;
    corrections: Record<string, { suggestion: string | null; distance: number; confidence: number }>;
    total_columns: number;
  }>(`/api/connections/${name}/schema/correct-columns`, {
    method: "POST",
    body: JSON.stringify({ table, columns, threshold }),
  });

// Schema Endorsements
export const getSchemaEndorsements = (name: string) =>
  request<{ endorsed: string[]; hidden: string[]; mode: "all" | "endorsed_only" }>(
    `/api/connections/${name}/schema/endorsements`
  );
export const setSchemaEndorsements = (name: string, endorsements: { endorsed: string[]; hidden: string[]; mode: "all" | "endorsed_only" }) =>
  request<{ endorsed: string[]; hidden: string[]; mode: "all" | "endorsed_only" }>(
    `/api/connections/${name}/schema/endorsements`,
    { method: "PUT", body: JSON.stringify(endorsements) }
  );

// Connection Export/Import
export const exportConnections = (includeCredentials = false) =>
  request<{
    version: string;
    exported_at: number;
    connection_count: number;
    includes_credentials: boolean;
    connections: Record<string, unknown>[];
  }>(`/api/connections/export?include_credentials=${includeCredentials}`);

export const importConnections = (manifest: Record<string, unknown>) =>
  request<{
    imported: number;
    skipped: string[];
    errors: { name: string; error: string }[];
  }>("/api/connections/import", { method: "POST", body: JSON.stringify(manifest) });

// Projects
export const getProjects = () => request<import("./types").ProjectInfo[]>("/api/projects");
export const getProject = (name: string) => request<import("./types").ProjectInfo>(`/api/projects/${name}`);
export const createProject = (p: Record<string, unknown>) =>
  request<import("./types").ProjectInfo>("/api/projects", { method: "POST", body: JSON.stringify(p) });
export const deleteProject = (name: string) =>
  request<void>(`/api/projects/${name}`, { method: "DELETE" });
export const scanProject = (name: string) =>
  request<{ message: string; model_count: number }>(`/api/projects/${name}/scan`, { method: "POST" });

// API Keys (local mode — gateway-managed)
export const getGatewayApiKeys = () =>
  request<{ id: string; name: string; prefix: string; scopes: string[]; created_at: string; last_used_at: string | null }[]>("/api/keys");
export const createGatewayApiKey = (name: string, scopes: string[]) =>
  request<{ id: string; name: string; prefix: string; scopes: string[]; created_at: string; last_used_at: string | null; raw_key: string }>("/api/keys", {
    method: "POST",
    body: JSON.stringify({ name, scopes }),
  });
export const deleteGatewayApiKey = (keyId: string) =>
  request<void>(`/api/keys/${keyId}`, { method: "DELETE" });

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
export const getConnectionHealthHistory = (name: string, window: number = 3600, bucket: number = 60) =>
  request<{ connection_name: string; window_seconds: number; bucket_seconds: number; buckets: { timestamp: number; avg_latency_ms: number | null; max_latency_ms: number | null; successes: number; failures: number; total: number }[] }>(`/api/connections/${name}/health/history?window=${window}&bucket=${bucket}`);

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

// Schema Warmup (parallel across all connections)
export const warmupSchemas = () =>
  request<{
    warmed: number;
    total_connections: number;
    total_tables: number;
    results: { name: string; status: string; table_count?: number; error?: string }[];
    duration_ms: number;
  }>("/api/connections/schema/warmup", { method: "POST" });

// Connection URL Validation
export const validateConnectionUrl = (connection_string: string, db_type: string) =>
  request<{ valid: boolean; parsed?: Record<string, unknown>; warnings?: string[]; error?: string }>(
    "/api/connections/validate-url", { method: "POST", body: JSON.stringify({ connection_string, db_type }) }
  );

// Pre-save Connection Test (HEX pattern: test before saving)
export const testCredentials = (payload: Record<string, unknown>) =>
  request<{
    status: string;
    message: string;
    phases: { phase: string; status: string; message: string; hint?: string; duration_ms: number }[];
    total_duration_ms?: number;
  }>("/api/connections/test-credentials", { method: "POST", body: JSON.stringify(payload) });

// Parse Connection URL into credential fields (HEX paste-and-parse pattern)
export const parseConnectionUrl = (url: string, db_type?: string) =>
  request<Record<string, string | number | boolean>>(
    "/api/connections/parse-url",
    { method: "POST", body: JSON.stringify({ url, db_type }) },
  );

// Connector Capabilities
export const getConnectorCapabilities = (dbType?: string) =>
  request<{
    tier_1?: { db_type: string; tier: number; label: string; feature_score: number }[];
    tier_2?: { db_type: string; tier: number; label: string; feature_score: number }[];
    tier_3?: { db_type: string; tier: number; label: string; feature_score: number }[];
    total_connectors?: number;
    db_type?: string; tier?: number; label?: string; feature_score?: number;
    features?: Record<string, boolean>;
  }>(dbType ? `/api/connectors/capabilities?db_type=${encodeURIComponent(dbType)}` : "/api/connectors/capabilities");

export const getConnectionCapabilities = (name: string) =>
  request<{
    connection_name: string; db_type: string; tier: number; tier_label: string;
    feature_score: number; features: Record<string, boolean>;
    configured: Record<string, boolean>;
  }>(`/api/connections/${name}/capabilities`);

// Network info (IP whitelist helper)
export const getNetworkInfo = () =>
  request<{
    hostname: string; local_ips: string[]; public_ip: string | null;
    whitelist_instructions: Record<string, string>;
  }>("/api/network/info");

// Connection diagnostics (DNS, TCP, TLS, auth)
export const diagnoseConnection = (name: string) =>
  request<{
    host: string; port: number;
    diagnostics: { check: string; status: string; message: string; hint?: string; duration_ms: number }[];
  }>(`/api/connections/${name}/diagnose`, { method: "POST" });

// Semantic Model (HEX-style inline schema editing)
export const getSemanticModel = (name: string) =>
  request<{
    tables: Record<string, { description: string; columns: Record<string, { description?: string; business_name?: string; unit?: string }> }>;
    joins: { from: string; to: string; type?: string; description?: string }[];
    glossary: Record<string, string>;
  }>(`/api/connections/${name}/semantic-model`);

export const updateSemanticModel = (name: string, model: Record<string, unknown>) =>
  request<Record<string, unknown>>(`/api/connections/${name}/semantic-model`, {
    method: "PUT",
    body: JSON.stringify(model),
  });

export const generateSemanticModel = (name: string) =>
  request<{
    tables: number; joins: number; glossary_terms: number;
    generated: { tables_with_descriptions: number; joins_added: number; glossary_terms_added: number };
  }>(`/api/connections/${name}/semantic-model/generate`, { method: "POST" });

// Schema Diff
export const getConnectionSchemaDiff = (name: string) =>
  request<{
    connection_name: string; has_cached: boolean; table_count: number;
    diff?: { has_changes: boolean; added_tables: string[]; removed_tables: string[]; modified_tables: unknown[] };
    message?: string;
  }>(`/api/connections/${name}/schema/diff`);

// Schema DDL (Spider2.0 optimized format)
export const getConnectionSchemaDDL = (name: string, maxTables = 50) =>
  request<{
    connection_name: string; format: string; table_count: number;
    token_estimate: number; ddl: string;
  }>(`/api/connections/${name}/schema/ddl?max_tables=${maxTables}`);

export const getConnectionSchemaLink = (name: string, question: string, format = "ddl", maxTables = 20) =>
  request<{
    connection_name: string; question: string; format: string;
    linked_tables: number; total_tables: number;
    token_estimate?: number; ddl?: string; schema?: string;
    scores?: Record<string, number>; tables?: Record<string, unknown>;
  }>(`/api/connections/${name}/schema/link?question=${encodeURIComponent(question)}&format=${format}&max_tables=${maxTables}`);

// File Browser (for local DuckDB/SQLite — browses host filesystem via sandbox manager)
export const browseFiles = (path?: string, pattern = "*.duckdb") => {
  const params = new URLSearchParams({ pattern });
  if (path) params.set("path", path);
  return request<{
    path: string;
    files: { name: string; path: string; size_bytes: number }[];
    directories: { name: string; path: string }[];
    error?: string;
  }>(`/api/files/browse?${params}`);
};

// Metrics SSE (uses fetch instead of EventSource so we can send auth headers)
export function subscribeMetrics(cb: (data: import("./types").MetricsSnapshot) => void): () => void {
  let aborted = false;
  const controller = new AbortController();

  (async () => {
    // Retry loop: wait for auth to be ready, then connect
    for (let attempt = 0; attempt < 10 && !aborted; attempt++) {
      const authHeader = await _getAuthHeader();
      if (!authHeader) {
        // Auth not ready yet (Clerk still loading) — wait and retry
        await new Promise((r) => setTimeout(r, 1000));
        continue;
      }

      try {
        const res = await fetch(`${GATEWAY_URL}/api/metrics`, {
          headers: { Accept: "text/event-stream", Authorization: authHeader },
          signal: controller.signal,
        });
        if (res.status === 401 || res.status === 403) {
          // Token may have expired or wasn't ready — retry
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
              try { cb(JSON.parse(line.slice(6))); } catch {}
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
