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
  knowledge_history_versions_override: number | null;
}

export interface KnowledgeDoc {
  id: string;
  org_id: string;
  scope: "org" | "project" | "connection";
  scope_ref: string | null;
  category: "understanding" | "conventions" | "decisions" | "domain-rules" | "debugging" | "quirks";
  title: string;
  body: string | null;
  status: "active" | "pending" | "archived";
  bytes: number;
  view_count: number;
  created_at: number;
  updated_at: number;
  created_by: string | null;
  updated_by: string | null;
  proposed_by_agent: string | null;
}

export interface KnowledgeEdit {
  id: string;
  doc_id: string;
  org_id: string;
  body_before: string;
  bytes_before: number;
  edited_at: number;
  edited_by: string | null;
  edit_kind: string;
}

export interface KnowledgeUsage {
  org_id: string;
  active_docs: number;
  active_bytes: number;
  storage_limit_bytes: number;
  storage_limit_mb: number;
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
  location: string | null;
  maximum_bytes_billed: number | null;
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
  // Timeouts
  connection_timeout: number | null;
  query_timeout: number | null;
  keepalive_interval: number | null;
  // Schema filtering
  schema_filter_include: string[] | null;
  schema_filter_exclude: string[] | null;
}

export interface ProjectInfo {
  id: string;
  name: string;
  connection_name: string;
  project_dir: string;
  storage: "managed" | "linked";
  source: "new" | "local" | "github" | "dbt-cloud";
  db_type: string;
  dbt_version: string;
  model_count: number;
  status: "active" | "error" | "archived";
  created_at: number;
  last_scanned_at: number | null;
  git_remote: string | null;
  git_branch: string | null;
  description: string;
  tags: string[];
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
  event_type: "query" | "execute" | "connect" | "block" | "mcp_tool" | "mcp_sql" | "sql";
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
  parent_id: string | null;
  client_ip: string | null;
  user_agent: string | null;
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

export interface NotebookInfo {
  id: string;
  name: string;
  description: string;
  tags: string[];
  cell_count: number;
  code_cell_count: number;
  markdown_cell_count: number;
  kernel_name: string | null;
  created_at: number;
  updated_at: number;
  analyzed_at: number | null;
  quality_score: number | null;
}

export interface NotebookAnalysis {
  notebook_id: string;
  cell_counts: Record<string, number>;
  imports: string[];
  execution_order_gaps: number[];
  error_cells: number[];
  output_summary: Record<string, number>;
  total_code_lines: number;
  functions_defined: string[];
  kernel_info: Record<string, unknown> | null;
  analyzed_at: number;
  quality_score?: number | null;
}

export interface NotebookCell {
  index: number;
  cell_type: string;
  source: string | string[];
  outputs?: unknown[];
  execution_count?: number | null;
  metadata?: Record<string, unknown>;
}

export interface ImportCount {
  name: string;
  count: number;
}

export interface NotebookSummary {
  total_notebooks: number;
  total_cells: number;
  total_code_cells: number;
  total_markdown_cells: number;
  total_code_lines: number;
  analyzed_count: number;
  pending_count: number;
  notebooks_with_errors: number;
  total_error_cells: number;
  top_imports: ImportCount[];
}

export interface BatchResultItem {
  notebook_id: string;
  success: boolean;
  error: string | null;
}

export interface BatchResult {
  results: BatchResultItem[];
  succeeded: number;
  failed: number;
}

export interface NotebookReportCell {
  index: number;
  cell_type: string;
  source_line_count: number;
  has_output: boolean;
  execution_count: number | null;
}

export interface NotebookReportOutputsSummary {
  total_outputs: number;
  by_type: Record<string, number>;
}

export interface NotebookReportMetadata {
  nbformat: number | null;
  nbformat_minor: number | null;
  kernel_info: Record<string, unknown> | null;
}

export interface NotebookReport {
  report_version: string;
  generated_at: number;
  notebook: NotebookInfo;
  analysis: NotebookAnalysis | null;
  cell_details: NotebookReportCell[];
  outputs_summary: NotebookReportOutputsSummary;
  metadata: NotebookReportMetadata;
}

export interface CellDiff {
  index: number;
  status: "unchanged" | "modified" | "added" | "removed";
  left_type: string | null;
  right_type: string | null;
  left_source_lines: number | null;
  right_source_lines: number | null;
}

export interface ComparisonSummary {
  added: number;
  removed: number;
  modified: number;
  unchanged: number;
}

export interface AnalysisComparison {
  left_imports: string[];
  right_imports: string[];
  added_imports: string[];
  removed_imports: string[];
  left_functions: string[];
  right_functions: string[];
  added_functions: string[];
  removed_functions: string[];
  left_error_cells: number[];
  right_error_cells: number[];
  left_code_lines: number;
  right_code_lines: number;
}

export interface NotebookComparison {
  left_notebook: NotebookInfo;
  right_notebook: NotebookInfo;
  analysis: AnalysisComparison | null;
  cell_diffs: CellDiff[];
  summary: ComparisonSummary;
}

export interface NotebookActivity {
  id: string;
  notebook_id: string;
  action: string;
  user_id: string | null;
  details: Record<string, unknown> | null;
  created_at: number;
}

export interface NotebookVersionInfo {
  id: string;
  notebook_id: string;
  version_number: number;
  total_cells: number;
  code_cells: number;
  markdown_cells: number;
  error_cells: number;
  total_code_lines: number;
  functions_count: number;
  imports_count: number;
  analyzed_at: number;
  created_at: number;
}

export interface MetricsSnapshot {
  timestamp: number;
  sandbox_manager: string;
  sandbox_health: string;
  sandbox_available: boolean;
  active_sandboxes: number;
  running_sandboxes: number;
  active_sandbox_instances: number;
  max_sandbox_instances: number;
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
