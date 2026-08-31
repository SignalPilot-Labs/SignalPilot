// Connection health, caches, PII, BYOK, diagnostics, and semantic models.

import { request } from "./client";

// The following functions support connection health.
export const getConnectionsHealth = () =>
  request<{ connections: import("../types").ConnectionHealthStats[] }>(
    "/api/connections/health",
  );
export const getConnectionHealth = (name: string) =>
  request<import("../types").ConnectionHealthStats>(
    `/api/connections/${name}/health`,
  );
export const getConnectionHealthHistory = (
  name: string,
  window: number = 3600,
  bucket: number = 60,
) =>
  request<{
    connection_name: string;
    window_seconds: number;
    bucket_seconds: number;
    buckets: {
      timestamp: number;
      avg_latency_ms: number | null;
      max_latency_ms: number | null;
      successes: number;
      failures: number;
      total: number;
    }[];
  }>(
    `/api/connections/${name}/health/history?window=${window}&bucket=${bucket}`,
  );

// The following functions support the query and schema caches.
export const getCacheStats = () =>
  request<{
    entries: number;
    max_entries: number;
    ttl_seconds: number;
    hits: number;
    misses: number;
    hit_rate: number;
  }>("/api/cache/stats");
export const invalidateCache = (connection_name?: string) =>
  request<{ invalidated: number; connection_name: string | null }>(
    `/api/cache/invalidate${connection_name ? `?connection_name=${encodeURIComponent(connection_name)}` : ""}`,
    { method: "POST" },
  );

// The following function detects PII.
export const detectPII = (name: string) =>
  request<{
    connection_name: string;
    tables_scanned: number;
    tables_with_pii: number;
    detections: Record<string, Record<string, string>>;
  }>(`/api/connections/${name}/detect-pii`, { method: "POST" });

// The following functions configure PII redaction.
export const getPIIConfig = (name: string) =>
  request<{ enabled: boolean; rules: Record<string, string> }>(
    `/api/connections/${name}/pii`,
  );
export const setPIIConfig = (
  name: string,
  config: { enabled: boolean; rules: Record<string, string> },
) =>
  request<{ enabled: boolean; rules: Record<string, string> }>(
    `/api/connections/${name}/pii`,
    { method: "PUT", body: JSON.stringify(config) },
  );
export const detectAndSavePII = (name: string) =>
  request<{
    connection_name: string;
    columns_flagged: number;
    rules: Record<string, string>;
    enabled: boolean;
  }>(`/api/connections/${name}/detect-and-save-pii`, { method: "POST" });

// BYOK Key Management
export type BYOKKey = {
  id: string;
  org_id: string;
  key_alias: string;
  provider_type: string;
  provider_config: Record<string, unknown> | null;
  status: string;
  created_at: number;
  revoked_at: number | null;
};
export type BYOKStatus = {
  total: number;
  byok: number;
  managed: number;
  status: "none" | "partial" | "complete";
};
export const listBYOKKeys = () => request<BYOKKey[]>("/api/byok/keys");
export const createBYOKKey = (body: {
  key_alias: string;
  provider_type: string;
  provider_config?: Record<string, unknown>;
}) =>
  request<BYOKKey>("/api/byok/keys", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const deleteBYOKKey = (keyId: string, force = false) =>
  request<void>(`/api/byok/keys/${keyId}${force ? "?force=true" : ""}`, {
    method: "DELETE",
  });
export const validateBYOKKey = (keyId: string) =>
  request<{ valid: boolean; error?: string }>(
    `/api/byok/keys/${keyId}/validate`,
    { method: "POST" },
  );
export const getBYOKStatus = () => request<BYOKStatus>("/api/byok/status");
export const migrateToBYOK = (keyId: string) =>
  request<{ migrated: number; failed: number; errors: string[] }>(
    "/api/byok/migrate",
    { method: "POST", body: JSON.stringify({ key_id: keyId }) },
  );
export const revertToManaged = () =>
  request<{ migrated: number; failed: number; errors: string[] }>(
    "/api/byok/revert",
    { method: "POST" },
  );

// The following function clears the schema cache.
export const getSchemaCache = () =>
  request<{
    cached_connections: number;
    total_entries: number;
    ttl_seconds: number;
  }>("/api/schema-cache/stats");
export const invalidateSchemaCache = (name?: string) =>
  request<{ invalidated: number }>(
    `/api/schema-cache/invalidate${name ? `?connection_name=${encodeURIComponent(name)}` : ""}`,
    { method: "POST" },
  );

// The following function warms schemas for all connections in parallel.
export const warmupSchemas = () =>
  request<{
    warmed: number;
    total_connections: number;
    total_tables: number;
    results: {
      name: string;
      status: string;
      table_count?: number;
      error?: string;
    }[];
    duration_ms: number;
  }>("/api/connections/schema/warmup", { method: "POST" });

// Connection URL Validation
export const validateConnectionUrl = (
  connection_string: string,
  db_type: string,
) =>
  request<{
    valid: boolean;
    parsed?: Record<string, unknown>;
    warnings?: string[];
    error?: string;
  }>("/api/connections/validate-url", {
    method: "POST",
    body: JSON.stringify({ connection_string, db_type }),
  });

// The following function tests a connection before save.
export const testCredentials = (payload: Record<string, unknown>) =>
  request<{
    status: string;
    message: string;
    phases: {
      phase: string;
      status: string;
      message: string;
      hint?: string;
      duration_ms: number;
    }[];
    total_duration_ms?: number;
  }>("/api/connections/test-credentials", {
    method: "POST",
    body: JSON.stringify(payload),
  });

// The following function parses a connection URL into credential fields.
export const parseConnectionUrl = (url: string, db_type?: string) =>
  request<Record<string, string | number | boolean>>(
    "/api/connections/parse-url",
    { method: "POST", body: JSON.stringify({ url, db_type }) },
  );

// The following function returns connector capabilities.
export const getConnectorCapabilities = (dbType?: string) =>
  request<{
    tier_1?: {
      db_type: string;
      tier: number;
      label: string;
      feature_score: number;
    }[];
    tier_2?: {
      db_type: string;
      tier: number;
      label: string;
      feature_score: number;
    }[];
    tier_3?: {
      db_type: string;
      tier: number;
      label: string;
      feature_score: number;
    }[];
    total_connectors?: number;
    db_type?: string;
    tier?: number;
    label?: string;
    feature_score?: number;
    features?: Record<string, boolean>;
  }>(
    dbType
      ? `/api/connectors/capabilities?db_type=${encodeURIComponent(dbType)}`
      : "/api/connectors/capabilities",
  );

export const getConnectionCapabilities = (name: string) =>
  request<{
    connection_name: string;
    db_type: string;
    tier: number;
    tier_label: string;
    feature_score: number;
    features: Record<string, boolean>;
    configured: Record<string, boolean>;
  }>(`/api/connections/${name}/capabilities`);

// The following function returns network information for IP allowlists.
export const getNetworkInfo = () =>
  request<{
    hostname: string;
    local_ips: string[];
    public_ip: string | null;
    whitelist_instructions: Record<string, string>;
  }>("/api/network/info");

// The following function returns DNS, TCP, TLS, and authentication diagnostics.
export const diagnoseConnection = (name: string) =>
  request<{
    host: string;
    port: number;
    diagnostics: {
      check: string;
      status: string;
      message: string;
      hint?: string;
      duration_ms: number;
    }[];
  }>(`/api/connections/${name}/diagnose`, { method: "POST" });

// The following functions support semantic model editing.
export const getSemanticModel = (name: string) =>
  request<{
    tables: Record<
      string,
      {
        description: string;
        columns: Record<
          string,
          { description?: string; business_name?: string; unit?: string }
        >;
      }
    >;
    joins: { from: string; to: string; type?: string; description?: string }[];
    glossary: Record<string, string>;
  }>(`/api/connections/${name}/semantic-model`);

export const updateSemanticModel = (
  name: string,
  model: Record<string, unknown>,
) =>
  request<Record<string, unknown>>(`/api/connections/${name}/semantic-model`, {
    method: "PUT",
    body: JSON.stringify(model),
  });

export const generateSemanticModel = (name: string) =>
  request<{
    tables: number;
    joins: number;
    glossary_terms: number;
    generated: {
      tables_with_descriptions: number;
      joins_added: number;
      glossary_terms_added: number;
    };
  }>(`/api/connections/${name}/semantic-model/generate`, { method: "POST" });

// The following function returns schema differences.
export const getConnectionSchemaDiff = (name: string) =>
  request<{
    connection_name: string;
    has_cached: boolean;
    table_count: number;
    diff?: {
      has_changes: boolean;
      added_tables: string[];
      removed_tables: string[];
      modified_tables: unknown[];
    };
    message?: string;
  }>(`/api/connections/${name}/schema/diff`);

// The following function returns schema DDL in the Spider 2.0 format.
export const getConnectionSchemaDDL = (name: string, maxTables = 50) =>
  request<{
    connection_name: string;
    format: string;
    table_count: number;
    token_estimate: number;
    ddl: string;
  }>(`/api/connections/${name}/schema/ddl?max_tables=${maxTables}`);

export const getConnectionSchemaLink = (
  name: string,
  question: string,
  format = "ddl",
  maxTables = 20,
) =>
  request<{
    connection_name: string;
    question: string;
    format: string;
    linked_tables: number;
    total_tables: number;
    token_estimate?: number;
    ddl?: string;
    schema?: string;
    scores?: Record<string, number>;
    tables?: Record<string, unknown>;
  }>(
    `/api/connections/${name}/schema/link?question=${encodeURIComponent(question)}&format=${format}&max_tables=${maxTables}`,
  );

// The following functions browse local DuckDB and SQLite files through the sandbox manager.
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
