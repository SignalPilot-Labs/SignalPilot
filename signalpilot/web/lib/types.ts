export interface GatewaySettings {
  sandbox_provider: "local" | "remote";
  sandbox_manager_url: string;
  sandbox_api_key: string | null;
  default_row_limit: number;
  default_budget_usd: number;
  default_timeout_seconds: number;
  max_concurrent_sandboxes: number;
  gateway_url: string;
  api_key: string | null;
}

export interface ConnectionInfo {
  id: string;
  name: string;
  db_type: "postgres" | "duckdb" | "mysql" | "snowflake";
  host: string | null;
  port: number | null;
  database: string | null;
  username: string | null;
  ssl: boolean;
  description: string;
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

export interface MetricsSnapshot {
  timestamp: number;
  sandbox_manager: string;
  sandbox_health: string;
  shuru_available: boolean;
  active_sandboxes: number;
  running_sandboxes: number;
  active_vms: number;
  max_vms: number;
  connections: number;
}
