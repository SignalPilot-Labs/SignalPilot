// Connection management and schema exploration.

import { request } from "./client";

// Connections
export const getConnections = () =>
  request<import("../types").ConnectionInfo[]>("/api/connections");
export const createConnection = (c: Record<string, unknown>) =>
  request<import("../types").ConnectionInfo>("/api/connections", {
    method: "POST",
    body: JSON.stringify(c),
  });
export const updateConnection = (
  name: string,
  updates: Record<string, unknown>,
) =>
  request<import("../types").ConnectionInfo>(`/api/connections/${name}`, {
    method: "PUT",
    body: JSON.stringify(updates),
  });
export const deleteConnection = (name: string) =>
  request<void>(`/api/connections/${name}`, { method: "DELETE" });

// The following functions support the /demo-db page.
export const getDemoConnector = () =>
  request<import("../types").DemoConnectorStatus>("/api/demo/connector");
export const createDemoConnector = (demo: string) =>
  request<import("../types").DemoConnectorCreated>("/api/demo/connector", {
    method: "POST",
    body: JSON.stringify({ demo }),
  });
export const refreshConnectionSchema = (name: string) =>
  request<{
    connection_name: string;
    table_count: number;
    message: string;
    refreshed_at?: number;
    next_refresh_in?: number | null;
  }>(`/api/connections/${name}/schema/refresh`, { method: "POST" });
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
    phases?: {
      phase: string;
      status: string;
      message: string;
      duration_ms?: number;
    }[];
    total_duration_ms?: number;
  }>(`/api/connections/${name}/test`, { method: "POST" });
export const getConnectionSchema = (name: string) =>
  request<{
    connection_name: string;
    db_type: string;
    table_count: number;
    tables: Record<
      string,
      {
        schema: string;
        name: string;
        columns: {
          name: string;
          type: string;
          nullable: boolean;
          primary_key?: boolean;
          comment?: string;
          stats?: { distinct_count?: number; distinct_fraction?: number };
        }[];
        foreign_keys?: {
          column: string;
          references_schema?: string;
          references_table: string;
          references_column: string;
        }[];
        indexes?: {
          name: string;
          definition?: string;
          columns?: string;
          unique?: boolean;
        }[];
        row_count?: number;
        description?: string;
        engine?: string;
        sorting_key?: string;
      }
    >;
  }>(`/api/connections/${name}/schema`);

export const cloneConnection = (name: string, newName: string) =>
  request<import("../types").ConnectionInfo>(
    `/api/connections/${name}/clone?new_name=${encodeURIComponent(newName)}`,
    { method: "POST" },
  );
export const explainQuery = (
  connection_name: string,
  sql: string,
  row_limit = 1000,
) =>
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
    tables: Record<
      string,
      {
        schema: string;
        name: string;
        columns: {
          name: string;
          type: string;
          nullable: boolean;
          primary_key?: boolean;
        }[];
        foreign_keys?: {
          column: string;
          references_table: string;
          references_column: string;
        }[];
        _matched_columns?: string[];
        _relevance_score?: number;
      }
    >;
  }>(`/api/connections/${name}/schema/search?q=${encodeURIComponent(query)}`);

// Column Exploration (ReFoRCE Spider2.0 pattern)
export const exploreColumns = (
  name: string,
  table: string,
  columns?: string[],
  options?: {
    include_stats?: boolean;
    include_values?: boolean;
    value_limit?: number;
  },
) =>
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
export const correctColumns = (
  name: string,
  table: string,
  columns: string[],
  threshold = 0.5,
) =>
  request<{
    table: string;
    corrections: Record<
      string,
      { suggestion: string | null; distance: number; confidence: number }
    >;
    total_columns: number;
  }>(`/api/connections/${name}/schema/correct-columns`, {
    method: "POST",
    body: JSON.stringify({ table, columns, threshold }),
  });

// The following functions support schema endorsements.
export const getSchemaEndorsements = (name: string) =>
  request<{
    endorsed: string[];
    hidden: string[];
    mode: "all" | "endorsed_only";
  }>(`/api/connections/${name}/schema/endorsements`);
export const setSchemaEndorsements = (
  name: string,
  endorsements: {
    endorsed: string[];
    hidden: string[];
    mode: "all" | "endorsed_only";
  },
) =>
  request<{
    endorsed: string[];
    hidden: string[];
    mode: "all" | "endorsed_only";
  }>(`/api/connections/${name}/schema/endorsements`, {
    method: "PUT",
    body: JSON.stringify(endorsements),
  });

// The following functions support connection export and import.
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
  }>("/api/connections/import", {
    method: "POST",
    body: JSON.stringify(manifest),
  });
