export interface GatewaySettings {
  sandbox_provider: "local" | "remote";
  sandbox_manager_url: string;
  sandbox_api_key: string | null;
  default_row_limit: number;
  default_budget_usd: number;
  default_timeout_seconds: number;
  max_concurrent_sandboxes: number;
  blocked_tables: string[];
  gateway_url: string;
  api_key: string | null;
}

export type DBType =
  | "postgres"
  | "duckdb"
  | "mysql"
  | "snowflake"
  | "bigquery"
  | "redshift"
  | "clickhouse"
  | "databricks"
  | "mssql"
  | "trino"
  | "sqlite";

export interface SSHTunnelConfig {
  enabled: boolean;
  host: string | null;
  port: number;
  username: string | null;
  auth_method: "password" | "key";
  password: string | null;
  private_key: string | null;
  private_key_passphrase: string | null;
}

export interface SSLConfig {
  enabled: boolean;
  mode: "disable" | "allow" | "prefer" | "require" | "verify-ca" | "verify-full";
  ca_cert: string | null;
  client_cert: string | null;
  client_key: string | null;
}

export interface ConnectionInfo {
  id: string;
  name: string;
  db_type: DBType;
  host: string | null;
  port: number | null;
  database: string | null;
  username: string | null;
  ssl: boolean;
  ssl_config: SSLConfig | null;
  ssh_tunnel: SSHTunnelConfig | null;
  // Snowflake
  account: string | null;
  warehouse: string | null;
  schema_name: string | null;
  role: string | null;
  // BigQuery
  project: string | null;
  dataset: string | null;
  // Databricks
  http_path: string | null;
  catalog: string | null;
  // Meta
  description: string;
  tags: string[];
  schema_refresh_interval: number | null;
  last_schema_refresh: number | null;
  created_at: number;
  last_used: number | null;
  status: string;
}

export interface SandboxInfo {
  id: string;
  vm_id: string | null;
  connection_name: string | null;
  label: string;
  status: "ready" | "starting" | "running" | "stopped" | "error";
  created_at: number;
  boot_ms: number | null;
  uptime_sec: number | null;
  budget_usd: number;
  budget_used: number;
  row_limit: number;
}

export interface ExecuteResult {
  success: boolean;
  output: string;
  error: string | null;
  execution_ms: number | null;
  vm_id: string | null;
}

export interface AuditEntry {
  id: string;
  timestamp: number;
  event_type: "query" | "execute" | "connect" | "block";
  connection_name: string | null;
  sandbox_id: string | null;
  sql: string | null;
  tables: string[];
  rows_returned: number | null;
  cost_usd: number | null;
  blocked: boolean;
  block_reason: string | null;
  duration_ms: number | null;
  agent_id: string | null;
  metadata: Record<string, unknown>;
}

export interface ConnectionHealthStats {
  connection_name: string;
  db_type: string;
  status: "healthy" | "warning" | "degraded" | "unhealthy" | "unknown";
  sample_count: number;
  window_seconds: number;
  successes?: number;
  failures?: number;
  error_rate?: number;
  consecutive_failures?: number;
  last_check: number | null;
  last_error: string | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  latency_p99_ms: number | null;
  latency_avg_ms: number | null;
}

export interface MetricsSnapshot {
  timestamp: number;
  sandbox_manager: string;
  sandbox_health: string;
  kvm_available: boolean;
  active_sandboxes: number;
  running_sandboxes: number;
  active_vms: number;
  max_vms: number;
  connections: number;
  query_cache?: {
    entries: number;
    max_entries: number;
    ttl_seconds: number;
    hits: number;
    misses: number;
    hit_rate: number;
  };
}
