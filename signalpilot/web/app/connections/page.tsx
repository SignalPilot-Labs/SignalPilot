"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  Plus,
  Trash2,
  CheckCircle2,
  XCircle,
  Loader2,
  TestTube,
  ChevronDown,
  ChevronRight,
  Table2,
  Activity,
  AlertTriangle,
  Clock,
  Shield,
  Eye,
  Link2,
  Settings2,
  Lock,
  Server,
  Pencil,
  RefreshCw,
  Search,
  Copy,
  EyeOff,
  Star,
  Filter,
  Download,
  Upload,
} from "lucide-react";
import {
  getConnections,
  createConnection,
  updateConnection,
  deleteConnection,
  cloneConnection,
  testConnection,
  getConnectionSchema,
  searchConnectionSchema,
  getConnectionsHealth,
  detectPII,
  refreshConnectionSchema,
  getSchemaEndorsements,
  setSchemaEndorsements,
  exportConnections,
  importConnections,
  getNetworkInfo,
  diagnoseConnection,
  generateSemanticModel,
} from "@/lib/api";
import type { ConnectionInfo, ConnectionHealthStats, DBType, SSHTunnelConfig, SSLConfig } from "@/lib/types";
import { EmptyDatabase, EmptyState } from "@/components/ui/empty-states";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot, MiniBar } from "@/components/ui/data-viz";
import { Tooltip } from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

/* ── DB type configuration ── */
interface DBTypeConfig {
  label: string;
  shortLabel: string;
  defaultPort: number;
  category: "relational" | "warehouse" | "embedded" | "columnar";
  supportsSSH: boolean;
  supportsSSL: boolean;
  connectionModes: ("fields" | "url")[];
  fields: string[];
  description: string;
}

const DB_CONFIGS: Record<DBType, DBTypeConfig> = {
  postgres: {
    label: "PostgreSQL",
    shortLabel: "pg",
    defaultPort: 5432,
    category: "relational",
    supportsSSH: true,
    supportsSSL: true,
    connectionModes: ["fields", "url"],
    fields: ["host", "port", "database", "username", "password"],
    description: "Open-source relational database",
  },
  mysql: {
    label: "MySQL",
    shortLabel: "mysql",
    defaultPort: 3306,
    category: "relational",
    supportsSSH: true,
    supportsSSL: true,
    connectionModes: ["fields", "url"],
    fields: ["host", "port", "database", "username", "password"],
    description: "Popular open-source RDBMS",
  },
  redshift: {
    label: "Amazon Redshift",
    shortLabel: "redshift",
    defaultPort: 5439,
    category: "warehouse",
    supportsSSH: true,
    supportsSSL: true,
    connectionModes: ["fields", "url"],
    fields: ["host", "port", "database", "username", "password"],
    description: "AWS cloud data warehouse",
  },
  snowflake: {
    label: "Snowflake",
    shortLabel: "snow",
    defaultPort: 443,
    category: "warehouse",
    supportsSSH: false,
    supportsSSL: false,
    connectionModes: ["fields", "url"],
    fields: ["account", "warehouse", "database", "schema_name", "username", "password", "role"],
    description: "Cloud-native data platform",
  },
  bigquery: {
    label: "Google BigQuery",
    shortLabel: "bq",
    defaultPort: 443,
    category: "warehouse",
    supportsSSH: false,
    supportsSSL: false,
    connectionModes: ["fields"],
    fields: ["project", "dataset", "credentials_json"],
    description: "Google serverless data warehouse",
  },
  clickhouse: {
    label: "ClickHouse",
    shortLabel: "ch",
    defaultPort: 9000,
    category: "columnar",
    supportsSSH: true,
    supportsSSL: true,
    connectionModes: ["fields", "url"],
    fields: ["host", "port", "database", "username", "password", "protocol"],
    description: "Column-oriented OLAP database",
  },
  databricks: {
    label: "Databricks",
    shortLabel: "dbx",
    defaultPort: 443,
    category: "warehouse",
    supportsSSH: false,
    supportsSSL: false,
    connectionModes: ["fields", "url"],
    fields: ["host", "http_path", "access_token", "catalog", "schema_name"],
    description: "Unified analytics platform",
  },
  mssql: {
    label: "SQL Server",
    shortLabel: "mssql",
    defaultPort: 1433,
    category: "relational",
    supportsSSH: true,
    supportsSSL: true,
    connectionModes: ["fields", "url"],
    fields: ["host", "port", "database", "username", "password"],
    description: "Microsoft SQL Server / Azure SQL",
  },
  trino: {
    label: "Trino",
    shortLabel: "trino",
    defaultPort: 8080,
    category: "warehouse",
    supportsSSH: true,
    supportsSSL: true,
    connectionModes: ["fields", "url"],
    fields: ["host", "port", "username", "password", "catalog", "schema_name"],
    description: "Distributed SQL query engine",
  },
  duckdb: {
    label: "DuckDB",
    shortLabel: "duck",
    defaultPort: 0,
    category: "embedded",
    supportsSSH: false,
    supportsSSL: false,
    connectionModes: ["fields"],
    fields: ["database"],
    description: "In-process analytical database",
  },
  sqlite: {
    label: "SQLite",
    shortLabel: "sqlite",
    defaultPort: 0,
    category: "embedded",
    supportsSSH: false,
    supportsSSL: false,
    connectionModes: ["fields"],
    fields: ["database"],
    description: "Lightweight file-based database",
  },
};

const DB_TYPE_ORDER: DBType[] = [
  "postgres", "mysql", "mssql", "redshift", "snowflake", "bigquery",
  "clickhouse", "databricks", "trino", "duckdb", "sqlite",
];

/* ── Connector tier classification (HEX pattern) ── */
const CONNECTOR_TIERS: Record<DBType, { tier: number; label: string; color: string }> = {
  postgres:   { tier: 1, label: "T1", color: "text-emerald-400 border-emerald-500/30" },
  mysql:      { tier: 1, label: "T1", color: "text-emerald-400 border-emerald-500/30" },
  snowflake:  { tier: 1, label: "T1", color: "text-emerald-400 border-emerald-500/30" },
  bigquery:   { tier: 1, label: "T1", color: "text-emerald-400 border-emerald-500/30" },
  mssql:      { tier: 2, label: "T2", color: "text-sky-400 border-sky-500/30" },
  redshift:   { tier: 2, label: "T2", color: "text-sky-400 border-sky-500/30" },
  clickhouse: { tier: 2, label: "T2", color: "text-sky-400 border-sky-500/30" },
  databricks: { tier: 2, label: "T2", color: "text-sky-400 border-sky-500/30" },
  trino:      { tier: 2, label: "T2", color: "text-sky-400 border-sky-500/30" },
  duckdb:     { tier: 3, label: "T3", color: "text-zinc-400 border-zinc-500/30" },
  sqlite:     { tier: 3, label: "T3", color: "text-zinc-400 border-zinc-500/30" },
};

const CATEGORY_LABELS: Record<string, string> = {
  relational: "relational databases",
  warehouse: "data warehouses",
  columnar: "columnar databases",
  embedded: "embedded databases",
};

const dbTypeLabels: Record<string, string> = Object.fromEntries(
  Object.entries(DB_CONFIGS).map(([k, v]) => [k, v.shortLabel])
);

/* ── Database type SVG icons ── */
function DbTypeIcon({ type, size = 12 }: { type: string; size?: number }) {
  switch (type) {
    case "postgres":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <ellipse cx="6" cy="3" rx="4.5" ry="2" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <path d="M1.5 3V9C1.5 10.1 3.5 11 6 11C8.5 11 10.5 10.1 10.5 9V3" stroke="currentColor" strokeWidth="0.75" />
          <path d="M1.5 6C1.5 7.1 3.5 8 6 8C8.5 8 10.5 7.1 10.5 6" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
        </svg>
      );
    case "duckdb":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <circle cx="4.5" cy="5" r="0.8" fill="currentColor" />
          <path d="M4 7.5C4.5 8.5 7.5 8.5 8 7.5" stroke="currentColor" strokeWidth="0.75" strokeLinecap="round" fill="none" />
          <path d="M7.5 4L9 3.5" stroke="currentColor" strokeWidth="0.75" strokeLinecap="round" />
        </svg>
      );
    case "mysql":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <path d="M2 2L6 10L10 2" stroke="currentColor" strokeWidth="0.75" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          <line x1="4" y1="6" x2="8" y2="6" stroke="currentColor" strokeWidth="0.75" />
        </svg>
      );
    case "snowflake":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <line x1="6" y1="1" x2="6" y2="11" stroke="currentColor" strokeWidth="0.75" />
          <line x1="1.7" y1="3.5" x2="10.3" y2="8.5" stroke="currentColor" strokeWidth="0.75" />
          <line x1="1.7" y1="8.5" x2="10.3" y2="3.5" stroke="currentColor" strokeWidth="0.75" />
          <circle cx="6" cy="6" r="1.5" stroke="currentColor" strokeWidth="0.5" fill="none" />
        </svg>
      );
    case "bigquery":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <rect x="2" y="2" width="8" height="8" rx="1" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <path d="M4 5L6 8L8 5" stroke="currentColor" strokeWidth="0.75" fill="none" strokeLinecap="round" />
          <circle cx="6" cy="4" r="1" stroke="currentColor" strokeWidth="0.5" fill="none" />
        </svg>
      );
    case "redshift":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <path d="M6 1L10.5 3.5V8.5L6 11L1.5 8.5V3.5L6 1Z" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <line x1="6" y1="6" x2="6" y2="11" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
          <line x1="6" y1="6" x2="10.5" y2="3.5" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
          <line x1="6" y1="6" x2="1.5" y2="3.5" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
        </svg>
      );
    case "clickhouse":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <rect x="2" y="1" width="1.5" height="10" fill="currentColor" opacity="0.8" />
          <rect x="4.5" y="3" width="1.5" height="8" fill="currentColor" opacity="0.6" />
          <rect x="7" y="1" width="1.5" height="10" fill="currentColor" opacity="0.4" />
          <rect x="9.5" y="5" width="1.5" height="6" fill="currentColor" opacity="0.3" />
        </svg>
      );
    case "databricks":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <path d="M6 1L11 3.5L6 6L1 3.5L6 1Z" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <path d="M1 6L6 8.5L11 6" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <path d="M1 8.5L6 11L11 8.5" stroke="currentColor" strokeWidth="0.75" fill="none" />
        </svg>
      );
    case "mssql":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <rect x="1.5" y="2" width="9" height="8" rx="1" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <path d="M3.5 5L5 7L8.5 4" stroke="currentColor" strokeWidth="0.75" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </svg>
      );
    case "trino":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <path d="M4 4L6 8L8 4" stroke="currentColor" strokeWidth="0.75" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </svg>
      );
    case "sqlite":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <rect x="3" y="1" width="6" height="10" rx="1" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <line x1="4.5" y1="4" x2="7.5" y2="4" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
          <line x1="4.5" y1="6" x2="7.5" y2="6" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
          <line x1="4.5" y1="8" x2="7.5" y2="8" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
        </svg>
      );
    default:
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <rect x="1.5" y="1.5" width="9" height="9" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <circle cx="6" cy="6" r="2" stroke="currentColor" strokeWidth="0.5" fill="none" />
        </svg>
      );
  }
}

/* ── Form field components ── */
function FormInput({
  label, value, onChange, type = "text", placeholder, hint, required, className = "",
}: {
  label: string; value: string; onChange: (v: string) => void;
  type?: string; placeholder?: string; hint?: string; required?: boolean; className?: string;
}) {
  return (
    <div className={className}>
      <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">
        {label}{required && <span className="text-[var(--color-error)] ml-0.5">*</span>}
      </label>
      <input
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
      />
      {hint && <p className="text-[9px] text-[var(--color-text-dim)] mt-1 tracking-wider opacity-60">{hint}</p>}
    </div>
  );
}

function FormTextArea({
  label, value, onChange, placeholder, hint, rows = 4, className = "",
}: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; hint?: string; rows?: number; className?: string;
}) {
  return (
    <div className={className}>
      <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">{label}</label>
      <textarea
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide font-mono resize-y"
      />
      {hint && <p className="text-[9px] text-[var(--color-text-dim)] mt-1 tracking-wider opacity-60">{hint}</p>}
    </div>
  );
}

/* ── Connection form state ── */
interface FormState {
  name: string;
  db_type: DBType;
  connectionMode: "fields" | "url";
  connection_string: string;
  host: string;
  port: string;
  database: string;
  username: string;
  password: string;
  description: string;
  // Snowflake
  account: string;
  warehouse: string;
  schema_name: string;
  role: string;
  // BigQuery
  project: string;
  dataset: string;
  credentials_json: string;
  bq_location: string;
  bq_max_bytes_billed: string;
  // ClickHouse
  ch_protocol: "native" | "http";
  // Databricks
  http_path: string;
  access_token: string;
  catalog: string;
  databricks_auth_method: "pat" | "oauth_m2m";
  dbx_oauth_client_id: string;
  dbx_oauth_client_secret: string;
  // SSL
  ssl_enabled: boolean;
  ssl_mode: string;
  ssl_ca_cert: string;
  ssl_client_cert: string;
  ssl_client_key: string;
  // SSH
  ssh_enabled: boolean;
  ssh_host: string;
  ssh_port: string;
  ssh_username: string;
  ssh_auth_method: string;
  ssh_password: string;
  ssh_private_key: string;
  ssh_key_passphrase: string;
  // Snowflake auth method (password, key-pair, or OAuth)
  snowflake_auth_method: "password" | "key_pair" | "oauth";
  sf_private_key: string;
  sf_private_key_passphrase: string;
  sf_oauth_token: string;
  // AWS IAM auth (PostgreSQL, MySQL on RDS, Redshift)
  iam_auth: boolean;
  aws_region: string;
  aws_access_key_id: string;
  aws_secret_access_key: string;
  // Redshift IAM extras
  redshift_cluster_id: string;
  redshift_workgroup: string; // For Redshift Serverless
  // Azure AD / Entra ID auth (MSSQL / Azure SQL)
  azure_ad_auth: boolean;
  azure_tenant_id: string;
  azure_client_id: string;
  azure_client_secret: string;
  // Trino HTTPS
  trino_https: boolean;
  // DuckDB / MotherDuck
  motherduck_token: string;
  // Tags
  tags: string[];
  tagInput: string;
  // Scheduled schema refresh
  schema_refresh_enabled: boolean;
  schema_refresh_interval: string; // seconds as string for form input
  // Connection scoping (HEX pattern)
  scope: "workspace" | "project";
  read_only: boolean;
  // Schema filtering (HEX pattern)
  schema_filter_include: string; // comma-separated schema names
  schema_filter_exclude: string; // comma-separated schema names
  // Timeouts
  connection_timeout: string; // seconds
  query_timeout: string; // seconds
  keepalive_interval: string; // seconds (0 = disabled)
  // Connection pool
  pool_min_size: string;
  pool_max_size: string;
}

const defaultForm: FormState = {
  name: "", db_type: "postgres", connectionMode: "fields",
  connection_string: "", host: "localhost", port: "5432",
  database: "", username: "", password: "", description: "",
  account: "", warehouse: "", schema_name: "", role: "",
  project: "", dataset: "", credentials_json: "", bq_location: "", bq_max_bytes_billed: "",
  ch_protocol: "native",
  http_path: "", access_token: "", catalog: "",
  databricks_auth_method: "pat", dbx_oauth_client_id: "", dbx_oauth_client_secret: "",
  ssl_enabled: false, ssl_mode: "require", ssl_ca_cert: "", ssl_client_cert: "", ssl_client_key: "",
  ssh_enabled: false, ssh_host: "", ssh_port: "22", ssh_username: "", ssh_auth_method: "password",
  ssh_password: "", ssh_private_key: "", ssh_key_passphrase: "",
  snowflake_auth_method: "password", sf_private_key: "", sf_private_key_passphrase: "", sf_oauth_token: "",
  iam_auth: false, aws_region: "us-east-1", aws_access_key_id: "", aws_secret_access_key: "",
  redshift_cluster_id: "", redshift_workgroup: "",
  azure_ad_auth: false, azure_tenant_id: "", azure_client_id: "", azure_client_secret: "",
  trino_https: false, motherduck_token: "",
  tags: [], tagInput: "",
  schema_refresh_enabled: false, schema_refresh_interval: "300",
  scope: "workspace", read_only: true,
  schema_filter_include: "", schema_filter_exclude: "",
  connection_timeout: "15", query_timeout: "120", keepalive_interval: "0", pool_min_size: "1", pool_max_size: "5",
};

function buildConnectionPreview(form: FormState): string {
  const dbType = form.db_type;
  if (form.connectionMode === "url" && form.connection_string) return form.connection_string.replace(/:[^:@]*@/, ":****@");

  switch (dbType) {
    case "postgres":
      return `postgresql://${form.username || "user"}:****@${form.host || "host"}:${form.port || "5432"}/${form.database || "db"}`;
    case "mysql":
      return `mysql://${form.username || "user"}:****@${form.host || "host"}:${form.port || "3306"}/${form.database || "db"}`;
    case "redshift":
      return `redshift://${form.username || "user"}:****@${form.host || "host"}:${form.port || "5439"}/${form.database || "dev"}`;
    case "clickhouse": {
      const chScheme = form.ch_protocol === "http"
        ? (form.ssl_enabled ? "clickhouse+https" : "clickhouse+http")
        : (form.ssl_enabled ? "clickhouses" : "clickhouse");
      const chPort = form.port || (form.ch_protocol === "http" ? (form.ssl_enabled ? "8443" : "8123") : (form.ssl_enabled ? "9440" : "9000"));
      return `${chScheme}://${form.username || "default"}:****@${form.host || "host"}:${chPort}/${form.database || "default"}`;
    }
    case "snowflake":
      return `snowflake://${form.username || "user"}:****@${form.account || "account"}/${form.database || "db"}/${form.schema_name || "schema"}${form.warehouse ? `?warehouse=${form.warehouse}` : ""}`;
    case "bigquery":
      return `bigquery://${form.project || "project"}/${form.dataset || "dataset"}`;
    case "databricks":
      return `databricks://****@${form.host || "host"}/${form.http_path || "sql/..."}${form.catalog ? `?catalog=${form.catalog}` : ""}`;
    case "mssql":
      return `mssql://${form.username || "sa"}:****@${form.host || "host"}:${form.port || "1433"}/${form.database || "master"}`;
    case "trino": {
      const trinoScheme = form.trino_https ? "trino+https" : "trino";
      const trinoPort = form.port || (form.trino_https ? "443" : "8080");
      return `${trinoScheme}://${form.username || "trino"}${form.password ? ":****" : ""}@${form.host || "host"}:${trinoPort}/${form.catalog || "catalog"}${form.schema_name ? `/${form.schema_name}` : ""}`;
    }
    case "duckdb":
    case "sqlite":
      return form.database || ":memory:";
    default:
      return "";
  }
}

/** Parse a connection URL into form fields (URL → fields sync). */
function parseConnectionUrl(url: string, dbType: DBType): Partial<FormState> {
  try {
    if (dbType === "postgres" || dbType === "mysql" || dbType === "redshift" || dbType === "clickhouse" || dbType === "mssql") {
      const parsed = new URL(url.replace(/^(postgresql|redshift|clickhouse|mysql\+pymysql|mssql|mssql\+pymssql|sqlserver):/, "http:"));
      return {
        host: parsed.hostname || "",
        port: parsed.port || String(DB_CONFIGS[dbType].defaultPort),
        database: parsed.pathname.replace(/^\//, "") || "",
        username: decodeURIComponent(parsed.username || ""),
        password: decodeURIComponent(parsed.password || ""),
      };
    }
    if (dbType === "snowflake") {
      // snowflake://user:pass@account/db/schema?warehouse=WH&role=ROLE
      const parsed = new URL(url.replace(/^snowflake:/, "http:"));
      const pathParts = parsed.pathname.split("/").filter(Boolean);
      return {
        account: parsed.hostname || "",
        username: decodeURIComponent(parsed.username || ""),
        password: decodeURIComponent(parsed.password || ""),
        database: pathParts[0] || "",
        schema_name: pathParts[1] || "",
        warehouse: parsed.searchParams.get("warehouse") || "",
        role: parsed.searchParams.get("role") || "",
      };
    }
    if (dbType === "trino") {
      const isHttps = url.startsWith("trino+https://");
      const parsed = new URL(url.replace(/^trino(\+https)?:/, "http:"));
      const pathParts = parsed.pathname.split("/").filter(Boolean);
      return {
        host: parsed.hostname || "",
        port: parsed.port || (isHttps ? "443" : "8080"),
        username: decodeURIComponent(parsed.username || "trino"),
        password: decodeURIComponent(parsed.password || ""),
        catalog: pathParts[0] || "",
        schema_name: pathParts[1] || "",
        trino_https: isHttps,
      };
    }
    if (dbType === "databricks") {
      // databricks://token@host/http_path?catalog=CAT
      const parsed = new URL(url.replace(/^databricks:/, "http:"));
      return {
        host: parsed.hostname || "",
        access_token: decodeURIComponent(parsed.username || ""),
        http_path: parsed.pathname.replace(/^\//, "") || "",
        catalog: parsed.searchParams.get("catalog") || "",
        schema_name: parsed.searchParams.get("schema") || "",
      };
    }
  } catch { /* parse failed — ignore */ }
  return {};
}

function buildCreatePayload(form: FormState): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    name: form.name,
    db_type: form.db_type,
    description: form.description,
  };

  if (form.connectionMode === "url" && form.connection_string) {
    payload.connection_string = form.connection_string;
  }

  const config = DB_CONFIGS[form.db_type];

  // Common host/port fields
  if (config.fields.includes("host")) payload.host = form.host;
  if (config.fields.includes("port")) payload.port = parseInt(form.port) || config.defaultPort;
  if (config.fields.includes("database")) payload.database = form.database;
  if (config.fields.includes("username")) payload.username = form.username;
  if (config.fields.includes("password")) payload.password = form.password;

  // Snowflake
  if (config.fields.includes("account")) payload.account = form.account;
  if (config.fields.includes("warehouse")) payload.warehouse = form.warehouse;
  if (config.fields.includes("schema_name")) payload.schema_name = form.schema_name;
  if (config.fields.includes("role")) payload.role = form.role;

  // BigQuery
  if (config.fields.includes("project")) payload.project = form.project;
  if (config.fields.includes("dataset")) payload.dataset = form.dataset;
  if (config.fields.includes("credentials_json")) payload.credentials_json = form.credentials_json;
  if (form.db_type === "bigquery") {
    if (form.bq_location) payload.location = form.bq_location;
    const maxBytes = parseInt(form.bq_max_bytes_billed);
    if (maxBytes > 0) payload.maximum_bytes_billed = maxBytes;
  }

  // Databricks
  if (config.fields.includes("http_path")) payload.http_path = form.http_path;
  if (config.fields.includes("access_token")) payload.access_token = form.access_token;
  if (config.fields.includes("catalog")) payload.catalog = form.catalog;

  // Databricks auth method
  if (form.db_type === "databricks") {
    payload.auth_method = form.databricks_auth_method;
    if (form.databricks_auth_method === "oauth_m2m") {
      payload.oauth_client_id = form.dbx_oauth_client_id;
      payload.oauth_client_secret = form.dbx_oauth_client_secret;
    }
  }

  // ClickHouse protocol
  if (form.db_type === "clickhouse" && form.ch_protocol === "http") {
    payload.protocol = "http";
  }

  // Trino HTTPS — build connection string with trino+https:// scheme
  if (form.db_type === "trino" && form.trino_https && form.connectionMode !== "url") {
    const trinoPort = form.port || "443";
    const userPart = form.password
      ? `${form.username || "trino"}:${form.password}@`
      : `${form.username || "trino"}@`;
    const pathPart = form.catalog ? `/${form.catalog}${form.schema_name ? `/${form.schema_name}` : ""}` : "";
    payload.connection_string = `trino+https://${userPart}${form.host}:${trinoPort}${pathPart}`;
  }

  // Tags
  if (form.tags.length > 0) {
    payload.tags = form.tags;
  }

  // Snowflake auth method
  if (form.db_type === "snowflake") {
    payload.auth_method = form.snowflake_auth_method;
    if (form.snowflake_auth_method === "key_pair") {
      payload.private_key = form.sf_private_key;
      if (form.sf_private_key_passphrase) payload.private_key_passphrase = form.sf_private_key_passphrase;
    } else if (form.snowflake_auth_method === "oauth") {
      payload.oauth_access_token = form.sf_oauth_token;
    }
  }

  // AWS IAM auth (PostgreSQL, MySQL on RDS, Redshift)
  if (form.iam_auth && (form.db_type === "postgres" || form.db_type === "mysql" || form.db_type === "redshift")) {
    payload.auth_method = "iam";
    payload.aws_region = form.aws_region;
    if (form.aws_access_key_id) payload.aws_access_key_id = form.aws_access_key_id;
    if (form.aws_secret_access_key) payload.aws_secret_access_key = form.aws_secret_access_key;
    // Redshift-specific IAM fields
    if (form.db_type === "redshift") {
      if (form.redshift_cluster_id) payload.cluster_id = form.redshift_cluster_id;
      if (form.redshift_workgroup) payload.workgroup = form.redshift_workgroup;
    }
  }

  // Azure AD / Entra ID auth (MSSQL / Azure SQL)
  if (form.azure_ad_auth && form.db_type === "mssql") {
    payload.auth_method = "azure_ad";
    if (form.azure_tenant_id) payload.azure_tenant_id = form.azure_tenant_id;
    if (form.azure_client_id) payload.azure_client_id = form.azure_client_id;
    if (form.azure_client_secret) payload.azure_client_secret = form.azure_client_secret;
  }

  // DuckDB MotherDuck token
  if (form.db_type === "duckdb" && form.motherduck_token) {
    payload.motherduck_token = form.motherduck_token;
  }

  // Scheduled schema refresh
  if (form.schema_refresh_enabled) {
    const interval = parseInt(form.schema_refresh_interval);
    if (interval >= 60 && interval <= 86400) {
      payload.schema_refresh_interval = interval;
    }
  }

  // SSL
  if (form.ssl_enabled && config.supportsSSL) {
    payload.ssl = true;
    payload.ssl_config = {
      enabled: true,
      mode: form.ssl_mode,
      ca_cert: form.ssl_ca_cert || null,
      client_cert: form.ssl_client_cert || null,
      client_key: form.ssl_client_key || null,
    };
  }

  // SSH
  if (form.ssh_enabled && config.supportsSSH) {
    payload.ssh_tunnel = {
      enabled: true,
      host: form.ssh_host,
      port: parseInt(form.ssh_port) || 22,
      username: form.ssh_username,
      auth_method: form.ssh_auth_method,
      password: form.ssh_auth_method === "password" ? form.ssh_password : null,
      private_key: form.ssh_auth_method === "key" ? form.ssh_private_key : null,
      private_key_passphrase: form.ssh_auth_method === "key" ? form.ssh_key_passphrase : null,
    };
  }

  // Schema filtering
  if (form.schema_filter_include.trim()) {
    payload.schema_filter_include = form.schema_filter_include.split(",").map((s: string) => s.trim()).filter(Boolean);
  }
  if (form.schema_filter_exclude.trim()) {
    payload.schema_filter_exclude = form.schema_filter_exclude.split(",").map((s: string) => s.trim()).filter(Boolean);
  }

  // Timeouts (pass as numbers if non-default)
  const connTimeout = parseInt(form.connection_timeout);
  if (connTimeout && connTimeout !== 15) payload.connection_timeout = connTimeout;
  const qTimeout = parseInt(form.query_timeout);
  if (qTimeout && qTimeout !== 120) payload.query_timeout = qTimeout;
  const keepalive = parseInt(form.keepalive_interval);
  if (keepalive && keepalive > 0) payload.keepalive_interval = keepalive;

  // Connection pool size (only for pool-capable connectors like PostgreSQL)
  const poolMin = parseInt(form.pool_min_size);
  const poolMax = parseInt(form.pool_max_size);
  if (poolMin && poolMin !== 1) payload.pool_min_size = poolMin;
  if (poolMax && poolMax !== 5) payload.pool_max_size = poolMax;

  return payload;
}

/* ── DB-specific form sections ── */
function ConnectionFieldsForm({ form, setForm }: { form: FormState; setForm: (f: FormState) => void }) {
  const config = DB_CONFIGS[form.db_type];

  // URL mode
  if (form.connectionMode === "url") {
    const urlHints: Record<string, string> = {
      postgres: "postgresql://user:pass@host:5432/dbname",
      mysql: "mysql://user:pass@host:3306/dbname",
      redshift: "redshift://user:pass@cluster.region.redshift.amazonaws.com:5439/dev",
      clickhouse: "clickhouse://user:pass@host:9000/default  (or clickhouse+http:// for HTTP)",
      snowflake: "snowflake://user:pass@account/db/schema?warehouse=WH&role=ROLE",
      databricks: "databricks://token@host.databricks.com/sql/1.0/warehouses/abc?catalog=main",
      mssql: "mssql://sa:password@host:1433/mydb",
      trino: "trino://user@host:8080/catalog/schema",
    };
    const parsed = form.connection_string ? parseConnectionUrl(form.connection_string, form.db_type) : null;
    const hasValidUrl = parsed && Object.values(parsed).some(v => v);
    return (
      <>
        <FormInput
          label="connection string"
          value={form.connection_string}
          onChange={(v) => setForm({ ...form, connection_string: v })}
          type="password"
          placeholder={urlHints[form.db_type] || "connection string"}
          hint={form.db_type === "clickhouse" ? "native: clickhouse://... | HTTP: clickhouse+http://..." : "full connection URL including credentials"}
          className="col-span-2"
        />
        {hasValidUrl && (
          <div className="col-span-2 -mt-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed">
            <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">parsed components:</span>
            <div className="flex flex-wrap gap-x-4 gap-y-0.5 mt-1">
              {parsed.host && <span className="text-[9px] tracking-wider"><span className="text-[var(--color-text-dim)]">host:</span> <span className="text-[var(--color-text)]">{parsed.host}</span></span>}
              {parsed.port && <span className="text-[9px] tracking-wider"><span className="text-[var(--color-text-dim)]">port:</span> <span className="text-[var(--color-text)]">{parsed.port}</span></span>}
              {parsed.database && <span className="text-[9px] tracking-wider"><span className="text-[var(--color-text-dim)]">db:</span> <span className="text-[var(--color-text)]">{parsed.database}</span></span>}
              {parsed.username && <span className="text-[9px] tracking-wider"><span className="text-[var(--color-text-dim)]">user:</span> <span className="text-[var(--color-text)]">{parsed.username}</span></span>}
              {parsed.account && <span className="text-[9px] tracking-wider"><span className="text-[var(--color-text-dim)]">account:</span> <span className="text-[var(--color-text)]">{parsed.account}</span></span>}
              {parsed.warehouse && <span className="text-[9px] tracking-wider"><span className="text-[var(--color-text-dim)]">warehouse:</span> <span className="text-[var(--color-text)]">{parsed.warehouse}</span></span>}
              {parsed.catalog && <span className="text-[9px] tracking-wider"><span className="text-[var(--color-text-dim)]">catalog:</span> <span className="text-[var(--color-text)]">{parsed.catalog}</span></span>}
              {parsed.password && <span className="text-[9px] tracking-wider text-[var(--color-success)]">password: ****</span>}
            </div>
          </div>
        )}
      </>
    );
  }

  // Snowflake fields
  if (form.db_type === "snowflake") {
    return (
      <>
        <FormInput label="account identifier" value={form.account} onChange={(v) => setForm({ ...form, account: v })} placeholder="org-account" hint="e.g., xy12345.us-east-1" required />
        <FormInput label="username" value={form.username} onChange={(v) => setForm({ ...form, username: v })} placeholder="ANALYTICS_USER" required />
        <div className="col-span-2 mb-1">
          <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">authentication method</label>
          <div className="flex gap-2">
            {(["password", "key_pair", "oauth"] as const).map((method) => (
              <button
                key={method}
                type="button"
                onClick={() => setForm({ ...form, snowflake_auth_method: method })}
                className={`px-2.5 py-1 text-[10px] tracking-wider border transition-all ${
                  form.snowflake_auth_method === method
                    ? "border-[var(--color-text)] text-[var(--color-text)]"
                    : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
                }`}
              >
                {method === "password" ? "password" : method === "key_pair" ? "key pair (RSA)" : "OAuth"}
              </button>
            ))}
          </div>
        </div>
        {form.snowflake_auth_method === "password" ? (
          <FormInput label="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} type="password" required className="col-span-2" />
        ) : form.snowflake_auth_method === "key_pair" ? (
          <>
            <FormTextArea
              label="private key (PEM)"
              value={form.sf_private_key}
              onChange={(v) => setForm({ ...form, sf_private_key: v })}
              placeholder="-----BEGIN ENCRYPTED PRIVATE KEY-----"
              hint="RSA private key for Snowflake key-pair authentication"
              rows={4}
              className="col-span-2"
            />
            <FormInput label="key passphrase" value={form.sf_private_key_passphrase} onChange={(v) => setForm({ ...form, sf_private_key_passphrase: v })} type="password" hint="leave empty if key is unencrypted" className="col-span-2" />
          </>
        ) : (
          <>
            <FormInput label="OAuth access token" value={form.sf_oauth_token} onChange={(v) => setForm({ ...form, sf_oauth_token: v })} type="password" required className="col-span-2" hint="from your identity provider (Okta, Azure AD, etc.)" />
            <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed text-[9px] text-[var(--color-text-dim)] tracking-wider space-y-1">
              <div><span className="text-[var(--color-text-muted)]">setup:</span> Create a Snowflake security integration (CREATE SECURITY INTEGRATION ... TYPE = EXTERNAL_OAUTH) and configure your IdP to issue tokens.</div>
              <div><span className="text-[var(--color-text-muted)]">local dev:</span> Use Snowflake&apos;s built-in SNOWFLAKE$LOCAL_APPLICATION integration for quick setup without admin involvement.</div>
            </div>
          </>
        )}
        <FormInput label="warehouse" value={form.warehouse} onChange={(v) => setForm({ ...form, warehouse: v })} placeholder="COMPUTE_WH" hint="optional — default warehouse" />
        <FormInput label="database" value={form.database} onChange={(v) => setForm({ ...form, database: v })} placeholder="PROD_DB" hint="optional — default database" />
        <FormInput label="schema" value={form.schema_name} onChange={(v) => setForm({ ...form, schema_name: v })} placeholder="PUBLIC" hint="optional — default schema" />
        <FormInput label="role" value={form.role} onChange={(v) => setForm({ ...form, role: v })} placeholder="ANALYST_ROLE" hint="optional — Snowflake role" />
        <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed text-[9px] text-[var(--color-text-dim)] tracking-wider space-y-1">
          <div><span className="text-[var(--color-text-muted)]">network policy:</span> Add this server&apos;s IP to ALLOWED_IP_LIST. Snowflake Admin → Security → Network Policies.</div>
          <div><span className="text-[var(--color-text-muted)]">private link:</span> For AWS PrivateLink or Azure Private Link, use the private account URL (e.g., org-account.privatelink.snowflakecomputing.com).</div>
          <div><span className="text-[var(--color-text-muted)]">vpn:</span> If your Snowflake is behind a VPN, ensure SignalPilot has network access to the Snowflake endpoint.</div>
        </div>
      </>
    );
  }

  // BigQuery fields
  if (form.db_type === "bigquery") {
    return (
      <>
        <FormInput label="gcp project id" value={form.project} onChange={(v) => setForm({ ...form, project: v })} placeholder="my-project-123" required />
        <FormInput label="default dataset" value={form.dataset} onChange={(v) => setForm({ ...form, dataset: v })} placeholder="analytics" hint="optional — default dataset for queries" />
        <FormTextArea
          label="service account json"
          value={form.credentials_json}
          onChange={(v) => setForm({ ...form, credentials_json: v })}
          placeholder='{"type": "service_account", "project_id": "...", ...}'
          hint="paste the full service account JSON key file contents"
          rows={6}
          className="col-span-2"
        />
        <FormInput
          label="location"
          value={form.bq_location}
          onChange={(v) => setForm({ ...form, bq_location: v })}
          placeholder="US"
          hint="optional — dataset location (US, EU, us-east1, europe-west1, etc.)"
        />
        <FormInput
          label="max bytes billed"
          value={form.bq_max_bytes_billed}
          onChange={(v) => setForm({ ...form, bq_max_bytes_billed: v })}
          placeholder="10737418240"
          hint="safety limit — query fails if scan exceeds this (10GB = 10737418240)"
        />
        <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed text-[9px] text-[var(--color-text-dim)] tracking-wider space-y-1">
          <div><span className="text-[var(--color-text-muted)]">setup:</span> GCP Console → IAM → Service Accounts → Create Key (JSON). Needs BigQuery Data Viewer + Job User roles.</div>
          <div><span className="text-[var(--color-text-muted)]">cost control:</span> Set max bytes billed to prevent runaway costs. 2026 pricing: $6.25/TB on-demand (first 1TB free).</div>
          <div><span className="text-[var(--color-text-muted)]">vpc:</span> For VPC Service Controls, ensure the service account has access from SignalPilot&apos;s network perimeter.</div>
        </div>
      </>
    );
  }

  // Databricks fields
  if (form.db_type === "databricks") {
    return (
      <>
        <FormInput label="server hostname" value={form.host} onChange={(v) => setForm({ ...form, host: v })} placeholder="adb-1234567890123456.7.azuredatabricks.net" required />
        <FormInput label="http path" value={form.http_path} onChange={(v) => setForm({ ...form, http_path: v })} placeholder="/sql/1.0/warehouses/abc123" hint="SQL warehouse or cluster HTTP path" required />
        {/* Auth method selector */}
        <div className="col-span-2 mb-1">
          <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">authentication method</label>
          <div className="flex gap-2">
            {(["pat", "oauth_m2m"] as const).map((method) => (
              <button
                key={method}
                type="button"
                onClick={() => setForm({ ...form, databricks_auth_method: method })}
                className={`px-2.5 py-1 text-[10px] tracking-wider border transition-all ${
                  form.databricks_auth_method === method
                    ? "border-[var(--color-text)] text-[var(--color-text)]"
                    : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
                }`}
              >
                {method === "pat" ? "personal access token" : "OAuth M2M (service principal)"}
              </button>
            ))}
          </div>
        </div>
        {form.databricks_auth_method === "pat" ? (
          <FormInput label="access token" value={form.access_token} onChange={(v) => setForm({ ...form, access_token: v })} type="password" hint="personal access token (PAT)" required className="col-span-2" />
        ) : (
          <div className="col-span-2 grid grid-cols-2 gap-3 p-3 border border-amber-500/20 bg-amber-500/5">
            <FormInput label="client ID" value={form.dbx_oauth_client_id} onChange={(v) => setForm({ ...form, dbx_oauth_client_id: v })} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" hint="service principal application (client) ID" required />
            <FormInput label="client secret" value={form.dbx_oauth_client_secret} onChange={(v) => setForm({ ...form, dbx_oauth_client_secret: v })} type="password" hint="service principal client secret" required />
            <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed text-[9px] text-[var(--color-text-dim)] tracking-wider space-y-1">
              <div><span className="text-[var(--color-text-muted)]">setup:</span> Account Console → User Management → Service Principals → Add. Grant CAN USE on the SQL Warehouse and data access on Unity Catalog.</div>
              <div><span className="text-[var(--color-text-muted)]">recommended:</span> OAuth M2M is the production-grade auth method. PATs are workspace-scoped and expire.</div>
            </div>
          </div>
        )}
        <FormInput label="catalog" value={form.catalog} onChange={(v) => setForm({ ...form, catalog: v })} placeholder="main" hint="optional — Unity Catalog name" />
        <FormInput label="schema" value={form.schema_name} onChange={(v) => setForm({ ...form, schema_name: v })} placeholder="default" hint="optional — default schema" />
        <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed text-[9px] text-[var(--color-text-dim)] tracking-wider space-y-1">
          <div><span className="text-[var(--color-text-muted)]">private link:</span> For AWS PrivateLink or Azure Private Link, use the private workspace URL (e.g., adb-xxx.x.azuredatabricks.net).</div>
          <div><span className="text-[var(--color-text-muted)]">unity catalog:</span> If enabled, PKs, FKs, and constraints will be automatically extracted for join discovery.</div>
          <div><span className="text-[var(--color-text-muted)]">ip access list:</span> Add this server&apos;s IP to the workspace IP Access List (Workspace Settings → Security → IP Access Lists).</div>
        </div>
      </>
    );
  }

  // Trino — host/port + catalog/schema + HTTPS toggle
  if (form.db_type === "trino") {
    return (
      <>
        <FormInput label="host" value={form.host} onChange={(v) => setForm({ ...form, host: v })} placeholder="trino.example.com" required />
        <FormInput label="port" value={form.port} onChange={(v) => setForm({ ...form, port: v })} placeholder={form.trino_https ? "443" : "8080"} />
        <FormInput label="username" value={form.username} onChange={(v) => setForm({ ...form, username: v })} placeholder="trino" />
        <FormInput label="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} type="password" hint="optional — for authenticated clusters" />
        <FormInput label="catalog" value={form.catalog} onChange={(v) => setForm({ ...form, catalog: v })} placeholder="hive" hint="default catalog for queries" />
        <FormInput label="schema" value={form.schema_name} onChange={(v) => setForm({ ...form, schema_name: v })} placeholder="default" hint="optional — default schema" />
        <div className="col-span-2">
          <button
            type="button"
            onClick={() => setForm({ ...form, trino_https: !form.trino_https, port: !form.trino_https ? "443" : "8080" })}
            className="flex items-center gap-2 text-[10px] tracking-wider transition-colors"
          >
            <div className={`w-3 h-3 border flex items-center justify-center transition-colors ${form.trino_https ? "border-emerald-500 bg-emerald-500/20" : "border-[var(--color-border)]"}`}>
              {form.trino_https && <div className="w-1.5 h-1.5 bg-emerald-400" />}
            </div>
            <span className={form.trino_https ? "text-[var(--color-text)]" : "text-[var(--color-text-dim)]"}>use HTTPS</span>
            {form.trino_https && <Lock className="w-3 h-3 text-emerald-400" strokeWidth={1.5} />}
          </button>
          <p className="text-[9px] text-[var(--color-text-dim)] mt-1 tracking-wider opacity-60 ml-5">
            {form.trino_https ? "encrypted connection — required for Starburst Galaxy and password auth" : "plain HTTP — for local/development clusters only"}
          </p>
        </div>
        <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed text-[9px] text-[var(--color-text-dim)] tracking-wider">
          <span className="text-[var(--color-text-muted)]">note:</span> Trino supports federated queries across multiple catalogs (Hive, Iceberg, MySQL, PostgreSQL, etc.). Each catalog maps to a data source configured in Trino.
        </div>
      </>
    );
  }

  // DuckDB/SQLite — just path
  if (form.db_type === "duckdb" || form.db_type === "sqlite") {
    const isMotherDuck = form.db_type === "duckdb" && form.database.startsWith("md:");
    return (
      <>
        <FormInput
          label="database path"
          value={form.database}
          onChange={(v) => setForm({ ...form, database: v })}
          placeholder={form.db_type === "duckdb" ? ":memory: or /path/to/db.duckdb or md:my_db" : ":memory: or /path/to/db.sqlite"}
          hint={form.db_type === "duckdb" ? "file path, :memory:, or md:<db_name> for MotherDuck cloud" : "file path or :memory:"}
          className="col-span-2"
        />
        {isMotherDuck && (
          <FormInput
            label="MotherDuck token"
            value={form.motherduck_token}
            onChange={(v) => setForm({ ...form, motherduck_token: v })}
            type="password"
            placeholder="eyJ..."
            hint="personal access token from app.motherduck.com"
            className="col-span-2"
          />
        )}
      </>
    );
  }

  // ClickHouse — protocol selector + host/port
  if (form.db_type === "clickhouse") {
    const httpPort = form.ssl_enabled ? "8443" : "8123";
    const nativePort = form.ssl_enabled ? "9440" : "9000";
    return (
      <>
        <div className="col-span-2 mb-1">
          <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">protocol</label>
          <div className="flex gap-2">
            {(["native", "http"] as const).map((proto) => (
              <button
                key={proto}
                type="button"
                onClick={() => setForm({ ...form, ch_protocol: proto, port: proto === "http" ? httpPort : nativePort })}
                className={`px-2.5 py-1 text-[10px] tracking-wider border transition-all ${
                  form.ch_protocol === proto
                    ? "border-[var(--color-text)] text-[var(--color-text)]"
                    : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
                }`}
              >
                {proto === "native" ? "native TCP (:9000)" : "HTTP (:8123)"}
              </button>
            ))}
          </div>
          <p className="text-[9px] text-[var(--color-text-dim)] mt-1 tracking-wider opacity-60">
            {form.ch_protocol === "http"
              ? "HTTP protocol — better compatibility with ClickHouse Cloud and load balancers"
              : "native protocol — fastest performance, direct binary protocol"}
          </p>
        </div>
        <FormInput label="host" value={form.host} onChange={(v) => setForm({ ...form, host: v })} placeholder="localhost" required />
        <FormInput label="port" value={form.port} onChange={(v) => setForm({ ...form, port: v })} placeholder={form.ch_protocol === "http" ? httpPort : nativePort} />
        <FormInput label="database" value={form.database} onChange={(v) => setForm({ ...form, database: v })} placeholder="default" required />
        <FormInput label="username" value={form.username} onChange={(v) => setForm({ ...form, username: v })} placeholder="default" required />
        <FormInput label="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} type="password" />
      </>
    );
  }

  // MSSQL — instance name, trust cert, encrypt option, Azure AD
  if (form.db_type === "mssql") {
    return (
      <>
        <FormInput label="host" value={form.host} onChange={(v) => setForm({ ...form, host: v })} placeholder="sqlserver.example.com" hint="hostname or IP — for named instances: host\\INSTANCE" required />
        <FormInput label="port" value={form.port} onChange={(v) => setForm({ ...form, port: v })} placeholder="1433" hint="default 1433 — Azure SQL uses 1433" />
        <FormInput label="database" value={form.database} onChange={(v) => setForm({ ...form, database: v })} placeholder="master" required />
        {!form.azure_ad_auth && (
          <>
            <FormInput label="username" value={form.username} onChange={(v) => setForm({ ...form, username: v })} placeholder="sa" hint="SQL Server login" required />
            <FormInput label="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} type="password" />
          </>
        )}
        {/* Azure AD / Entra ID toggle */}
        <div className="col-span-2 mb-1">
          <button
            type="button"
            onClick={() => setForm({ ...form, azure_ad_auth: !form.azure_ad_auth })}
            className={`flex items-center gap-2 px-2.5 py-1.5 text-[10px] tracking-wider border transition-all ${
              form.azure_ad_auth
                ? "border-blue-500/50 text-blue-400 bg-blue-500/10"
                : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
            }`}
          >
            <Shield className="w-3 h-3" />
            <span>Azure AD / Entra ID</span>
            {form.azure_ad_auth && <span className="text-[var(--color-success)] text-[9px]">enabled</span>}
          </button>
        </div>
        {form.azure_ad_auth && (
          <div className="col-span-2 grid grid-cols-2 gap-3 p-3 border border-blue-500/20 bg-blue-500/5">
            <FormInput label="tenant ID" value={form.azure_tenant_id} onChange={(v) => setForm({ ...form, azure_tenant_id: v })} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" hint="Azure AD directory (tenant) ID" required />
            <FormInput label="client ID" value={form.azure_client_id} onChange={(v) => setForm({ ...form, azure_client_id: v })} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" hint="App registration (client) ID" required />
            <FormInput label="client secret" value={form.azure_client_secret} onChange={(v) => setForm({ ...form, azure_client_secret: v })} type="password" hint="Service principal client secret" required className="col-span-2" />
            <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed text-[9px] text-[var(--color-text-dim)] tracking-wider space-y-1">
              <div><span className="text-[var(--color-text-muted)]">setup:</span> Azure Portal → App Registrations → New → Add API Permission for Azure SQL Database. Create a contained DB user: CREATE USER [app-name] FROM EXTERNAL PROVIDER.</div>
              <div><span className="text-[var(--color-text-muted)]">managed identity:</span> For Azure VMs/containers, leave client secret empty to use system-assigned managed identity (coming soon).</div>
            </div>
          </div>
        )}
        <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed text-[9px] text-[var(--color-text-dim)] tracking-wider space-y-1">
          <div><span className="text-[var(--color-text-muted)]">azure sql:</span> Use &lt;server&gt;.database.windows.net as host. Ensure firewall rule allows this server&apos;s IP.</div>
          <div><span className="text-[var(--color-text-muted)]">named instances:</span> Include instance in host: host\SQLEXPRESS. Or use port directly (SQL Browser resolves instances to ports).</div>
          <div><span className="text-[var(--color-text-muted)]">on-prem:</span> For SQL Server behind a firewall, use the SSH tunnel option in Advanced settings.</div>
        </div>
      </>
    );
  }

  // Redshift — cluster endpoint guidance + IAM auth
  if (form.db_type === "redshift") {
    return (
      <>
        <FormInput label="cluster endpoint" value={form.host} onChange={(v) => setForm({ ...form, host: v })} placeholder="my-cluster.abc123xyz.us-east-1.redshift.amazonaws.com" hint="Redshift console → Clusters → Properties → Endpoint" required />
        <FormInput label="port" value={form.port} onChange={(v) => setForm({ ...form, port: v })} placeholder="5439" />
        <FormInput label="database" value={form.database} onChange={(v) => setForm({ ...form, database: v })} placeholder="dev" hint="default database is 'dev'" required />
        {!form.iam_auth && (
          <>
            <FormInput label="username" value={form.username} onChange={(v) => setForm({ ...form, username: v })} placeholder="awsuser" required />
            <FormInput label="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} type="password" />
          </>
        )}
        {/* IAM Auth toggle */}
        <div className="col-span-2 mb-1">
          <button
            type="button"
            onClick={() => setForm({ ...form, iam_auth: !form.iam_auth })}
            className={`flex items-center gap-2 px-2.5 py-1.5 text-[10px] tracking-wider border transition-all ${
              form.iam_auth
                ? "border-amber-500/50 text-amber-400 bg-amber-500/10"
                : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
            }`}
          >
            <Shield className="w-3 h-3" />
            <span>AWS IAM auth</span>
            {form.iam_auth && <span className="text-[var(--color-success)] text-[9px]">enabled</span>}
          </button>
        </div>
        {form.iam_auth && (
          <div className="col-span-2 grid grid-cols-2 gap-3 p-3 border border-amber-500/20 bg-amber-500/5">
            <FormInput label="username" value={form.username} onChange={(v) => setForm({ ...form, username: v })} placeholder="awsuser" hint="Redshift DB user to get temporary credentials for" required />
            <FormInput label="AWS region" value={form.aws_region} onChange={(v) => setForm({ ...form, aws_region: v })} placeholder="us-east-1" hint="Redshift cluster region" />
            <FormInput label="cluster ID" value={form.redshift_cluster_id} onChange={(v) => setForm({ ...form, redshift_cluster_id: v })} placeholder="my-redshift-cluster" hint="provisioned cluster ID (auto-detected from endpoint if blank)" />
            <FormInput label="workgroup" value={form.redshift_workgroup} onChange={(v) => setForm({ ...form, redshift_workgroup: v })} placeholder="default" hint="for Redshift Serverless only" />
            <FormInput label="AWS access key ID" value={form.aws_access_key_id} onChange={(v) => setForm({ ...form, aws_access_key_id: v })} placeholder="AKIA..." hint="leave empty to use instance profile / env credentials" />
            <FormInput label="AWS secret access key" value={form.aws_secret_access_key} onChange={(v) => setForm({ ...form, aws_secret_access_key: v })} type="password" hint="leave empty to use instance profile / env credentials" />
            <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed text-[9px] text-[var(--color-text-dim)] tracking-wider space-y-1">
              <div><span className="text-[var(--color-text-muted)]">setup:</span> IAM user/role needs redshift:GetClusterCredentials (provisioned) or redshift-serverless:GetCredentials (serverless).</div>
              <div><span className="text-[var(--color-text-muted)]">credentials:</span> Leave access key fields empty to use EC2 instance profile, ECS task role, or AWS_* env vars.</div>
            </div>
          </div>
        )}
        <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed text-[9px] text-[var(--color-text-dim)] tracking-wider space-y-1">
          <div><span className="text-[var(--color-text-muted)]">access:</span> Ensure this server&apos;s IP is allowed in the Redshift security group. For VPC clusters, use SSH tunnel or VPC peering.</div>
          <div><span className="text-[var(--color-text-muted)]">serverless:</span> Use workgroup endpoint: &lt;workgroup-name&gt;.&lt;account-id&gt;.&lt;region&gt;.redshift-serverless.amazonaws.com</div>
        </div>
      </>
    );
  }

  // Standard host/port (Postgres, MySQL)
  const placeholders: Record<string, Record<string, string>> = {
    postgres: { host: "localhost", db: "mydb", user: "postgres" },
    mysql: { host: "localhost", db: "mydb", user: "root" },
  };
  const ph = placeholders[form.db_type] || { host: "localhost", db: "mydb", user: "user" };
  return (
    <>
      <FormInput label="host" value={form.host} onChange={(v) => setForm({ ...form, host: v })} placeholder={ph.host} required />
      <FormInput label="port" value={form.port} onChange={(v) => setForm({ ...form, port: v })} placeholder={String(config.defaultPort)} />
      <FormInput label="database" value={form.database} onChange={(v) => setForm({ ...form, database: v })} placeholder={ph.db} required />
      <FormInput label="username" value={form.username} onChange={(v) => setForm({ ...form, username: v })} placeholder={ph.user} required />
      {!form.iam_auth && (
        <FormInput label="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} type="password" />
      )}
      {/* AWS IAM Auth toggle for RDS */}
      <div className="col-span-2 mt-1">
        <button
          type="button"
          onClick={() => setForm({ ...form, iam_auth: !form.iam_auth })}
          className={`flex items-center gap-2 px-2.5 py-1 text-[10px] tracking-wider border transition-all ${
            form.iam_auth
              ? "border-[var(--color-text)] text-[var(--color-text)]"
              : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
          }`}
        >
          {form.iam_auth ? "✓ " : ""}AWS IAM authentication
        </button>
      </div>
      {form.iam_auth && (
        <>
          <FormInput label="AWS region" value={form.aws_region} onChange={(v) => setForm({ ...form, aws_region: v })} placeholder="us-east-1" hint="RDS instance region" />
          <FormInput label="AWS access key ID" value={form.aws_access_key_id} onChange={(v) => setForm({ ...form, aws_access_key_id: v })} placeholder="AKIA..." hint="leave empty to use instance profile / env credentials" />
          <FormInput label="AWS secret access key" value={form.aws_secret_access_key} onChange={(v) => setForm({ ...form, aws_secret_access_key: v })} type="password" hint="leave empty to use instance profile / env credentials" />
          <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed text-[9px] text-[var(--color-text-dim)] tracking-wider space-y-1">
            <div><span className="text-[var(--color-text-muted)]">setup:</span> DB user must have rds_iam role (PostgreSQL) or be created with AWSAuthenticationPlugin (MySQL). SSL is auto-enabled.</div>
            <div><span className="text-[var(--color-text-muted)]">credentials:</span> Leave access key fields empty to use EC2 instance profile, ECS task role, or AWS_* env vars.</div>
          </div>
        </>
      )}
      {/* Connection guidance (HEX pattern — contextual setup instructions) */}
      <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed text-[9px] text-[var(--color-text-dim)] tracking-wider space-y-1">
        {form.db_type === "postgres" ? (
          <>
            <div><span className="text-[var(--color-text-muted)]">rds:</span> Use endpoint from RDS Console → Connectivity. Ensure security group allows this server&apos;s IP on port 5432.</div>
            <div><span className="text-[var(--color-text-muted)]">supabase:</span> Project Settings → Database → Connection string. Use pooler for serverless (port 6543).</div>
            <div><span className="text-[var(--color-text-muted)]">neon:</span> Use the connection string from Neon console. SSL is required (auto-enabled).</div>
            <div><span className="text-[var(--color-text-muted)]">on-prem:</span> For databases behind a firewall, enable the SSH tunnel in Advanced settings.</div>
          </>
        ) : (
          <>
            <div><span className="text-[var(--color-text-muted)]">rds:</span> Use endpoint from RDS Console → Connectivity. Security group must allow port 3306 from this server.</div>
            <div><span className="text-[var(--color-text-muted)]">planetscale:</span> Use the connection string from PlanetScale dashboard. SSL is required (auto-enabled).</div>
            <div><span className="text-[var(--color-text-muted)]">cloud sql:</span> For Google Cloud SQL, use the Cloud SQL Auth Proxy or add this server&apos;s IP to authorized networks.</div>
            <div><span className="text-[var(--color-text-muted)]">on-prem:</span> For MySQL behind a firewall, enable the SSH tunnel in Advanced settings.</div>
          </>
        )}
      </div>
    </>
  );
}

/* ── SSL Config Section ── */
function SSLSection({ form, setForm }: { form: FormState; setForm: (f: FormState) => void }) {
  const config = DB_CONFIGS[form.db_type];
  if (!config.supportsSSL) return null;

  return (
    <div className="border-t border-[var(--color-border)] pt-4 mt-4">
      <button
        type="button"
        onClick={() => setForm({ ...form, ssl_enabled: !form.ssl_enabled })}
        className="flex items-center gap-2 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
      >
        <Lock className="w-3 h-3" strokeWidth={1.5} />
        <span>ssl / tls</span>
        {form.ssl_enabled ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {form.ssl_enabled && <span className="text-[var(--color-success)] text-[9px]">enabled</span>}
      </button>
      {form.ssl_enabled && (
        <div className="grid grid-cols-2 gap-4 mt-3 animate-fade-in">
          <div>
            <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">ssl mode</label>
            <select
              value={form.ssl_mode}
              onChange={(e) => setForm({ ...form, ssl_mode: e.target.value })}
              className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
            >
              <option value="require">require</option>
              <option value="verify-ca">verify-ca</option>
              <option value="verify-full">verify-full</option>
              <option value="prefer">prefer</option>
              <option value="allow">allow</option>
            </select>
          </div>
          <div />
          <FormTextArea label="ca certificate (pem)" value={form.ssl_ca_cert} onChange={(v) => setForm({ ...form, ssl_ca_cert: v })} placeholder="-----BEGIN CERTIFICATE-----" hint="root CA certificate for server verification" rows={3} />
          <FormTextArea label="client certificate (pem)" value={form.ssl_client_cert} onChange={(v) => setForm({ ...form, ssl_client_cert: v })} placeholder="-----BEGIN CERTIFICATE-----" hint="optional — for mutual TLS" rows={3} />
          <FormTextArea label="client key (pem)" value={form.ssl_client_key} onChange={(v) => setForm({ ...form, ssl_client_key: v })} placeholder="-----BEGIN PRIVATE KEY-----" hint="optional — for mutual TLS" rows={3} className="col-span-2" />
        </div>
      )}
    </div>
  );
}

/* ── SSH Tunnel Section ── */
function SSHSection({ form, setForm }: { form: FormState; setForm: (f: FormState) => void }) {
  const config = DB_CONFIGS[form.db_type];
  if (!config.supportsSSH) return null;

  return (
    <div className="border-t border-[var(--color-border)] pt-4 mt-4">
      <button
        type="button"
        onClick={() => setForm({ ...form, ssh_enabled: !form.ssh_enabled })}
        className="flex items-center gap-2 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
      >
        <Server className="w-3 h-3" strokeWidth={1.5} />
        <span>ssh tunnel</span>
        {form.ssh_enabled ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {form.ssh_enabled && <span className="text-[var(--color-success)] text-[9px]">enabled</span>}
      </button>
      {form.ssh_enabled && (
        <div className="grid grid-cols-2 gap-4 mt-3 animate-fade-in">
          <FormInput label="ssh host" value={form.ssh_host} onChange={(v) => setForm({ ...form, ssh_host: v })} placeholder="bastion.example.com" required />
          <FormInput label="ssh port" value={form.ssh_port} onChange={(v) => setForm({ ...form, ssh_port: v })} placeholder="22" />
          <FormInput label="ssh username" value={form.ssh_username} onChange={(v) => setForm({ ...form, ssh_username: v })} placeholder="ubuntu" required />
          <div>
            <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">auth method</label>
            <select
              value={form.ssh_auth_method}
              onChange={(e) => setForm({ ...form, ssh_auth_method: e.target.value })}
              className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
            >
              <option value="password">password</option>
              <option value="key">private key</option>
            </select>
          </div>
          {form.ssh_auth_method === "password" ? (
            <FormInput label="ssh password" value={form.ssh_password} onChange={(v) => setForm({ ...form, ssh_password: v })} type="password" className="col-span-2" />
          ) : (
            <>
              <FormTextArea label="private key (pem)" value={form.ssh_private_key} onChange={(v) => setForm({ ...form, ssh_private_key: v })} placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" rows={4} className="col-span-2" />
              <FormInput label="key passphrase" value={form.ssh_key_passphrase} onChange={(v) => setForm({ ...form, ssh_key_passphrase: v })} type="password" hint="leave empty if key is not encrypted" className="col-span-2" />
            </>
          )}
          <div className="col-span-2">
            <p className="text-[9px] text-[var(--color-text-dim)] tracking-wider opacity-60">
              signalpilot will create an on-demand ssh tunnel to your database through this bastion host. whitelist our ip: <code className="text-[var(--color-text-muted)]">your-signalpilot-ip</code>
            </p>
          </div>
        </div>
      )}
    </div>
  );
}


export default function ConnectionsPage() {
  const { toast } = useToast();
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingConnection, setEditingConnection] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { status: string; message: string; phases?: { phase: string; status: string; message: string; duration_ms?: number }[]; total_duration_ms?: number }>>({});
  const [saving, setSaving] = useState(false);
  const [expandedConn, setExpandedConn] = useState<string | null>(null);
  const [schemaData, setSchemaData] = useState<Record<string, { tables: Record<string, { schema: string; name: string; columns: { name: string; type: string; nullable: boolean; primary_key?: boolean }[] }> }>>({});
  const [schemaLoading, setSchemaLoading] = useState<string | null>(null);
  const [healthData, setHealthData] = useState<Record<string, ConnectionHealthStats>>({});
  const [piiData, setPiiData] = useState<Record<string, { tables_scanned: number; tables_with_pii: number; detections: Record<string, Record<string, string>> }>>({});
  const [piiLoading, setPiiLoading] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [schemaSearch, setSchemaSearch] = useState<Record<string, string>>({});
  const [schemaSearchResults, setSchemaSearchResults] = useState<Record<string, { result_count: number; total_tables: number; tables: Record<string, any> }>>({});
  const [schemaSearchLoading, setSchemaSearchLoading] = useState<string | null>(null);
  const [endorsements, setEndorsements] = useState<Record<string, { endorsed: string[]; hidden: string[]; mode: "all" | "endorsed_only" }>>({});
  const [form, setForm] = useState<FormState>({ ...defaultForm });
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [filterTag, setFilterTag] = useState<string | null>(null);
  const importFileRef = useRef<HTMLInputElement>(null);
  const [serverIp, setServerIp] = useState<string | null>(null);
  const [diagnosing, setDiagnosing] = useState<string | null>(null);
  const [diagResults, setDiagResults] = useState<Record<string, { host: string; port: number; diagnostics: { check: string; status: string; message: string; hint?: string; duration_ms: number }[] }>>({});

  const refresh = useCallback(() => {
    getConnections().then(setConnections).catch(() => {});
    getConnectionsHealth()
      .then((res) => {
        const map: Record<string, ConnectionHealthStats> = {};
        for (const h of res.connections) map[h.connection_name] = h;
        setHealthData(map);
      })
      .catch(() => {});
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // Fetch server IP for whitelist guidance
  useEffect(() => {
    getNetworkInfo().then((info) => {
      setServerIp(info.public_ip || (info.local_ips?.[0] ?? null));
    }).catch(() => {});
  }, []);

  function handleDbTypeChange(newType: DBType) {
    const config = DB_CONFIGS[newType];
    setForm({
      ...form,
      db_type: newType,
      port: String(config.defaultPort || ""),
      connectionMode: config.connectionModes[0],
      host: config.fields.includes("host") ? form.host || "localhost" : "",
    });
  }

  async function handleCreate() {
    setSaving(true);
    try {
      const payload = buildCreatePayload(form);
      if (editingConnection) {
        // Update existing connection
        const { name: _n, db_type: _d, ...updateFields } = payload;
        await updateConnection(editingConnection, updateFields);
        toast("connection updated successfully", "success");
      } else {
        await createConnection(payload);
        toast("connection created successfully", "success");
      }
      setShowForm(false);
      setEditingConnection(null);
      setForm({ ...defaultForm });
      setShowAdvanced(false);
      refresh();
    } catch (e) { toast(_parseError(e), "error"); } finally { setSaving(false); }
  }

  function _parseError(e: unknown): string {
    const msg = String(e);
    // Parse validation errors from the API
    try {
      const match = msg.match(/\{.*"validation_errors".*\}/);
      if (match) {
        const parsed = JSON.parse(match[0]);
        if (parsed.validation_errors) {
          return parsed.validation_errors.join("; ");
        }
      }
    } catch {}
    // Clean up generic error messages
    return msg.replace(/^Error:\s*\d+:\s*/, "").replace(/^"?(.*?)"?$/, "$1").slice(0, 200);
  }

  async function handleSaveAndTest() {
    setSaving(true);
    try {
      const payload = buildCreatePayload(form);
      if (editingConnection) {
        const { name: _n, db_type: _d, ...updateFields } = payload;
        await updateConnection(editingConnection, updateFields);
      } else {
        await createConnection(payload);
      }
      setShowForm(false);
      setEditingConnection(null);
      setForm({ ...defaultForm });
      setShowAdvanced(false);
      refresh();
      // Auto-test after save
      const connName = editingConnection || (payload.name as string);
      toast(`${connName}: testing connection...`, "info");
      const result = await testConnection(connName);
      setTestResult((prev) => ({ ...prev, [connName]: result }));
      toast(result.status === "healthy" ? `${connName}: connection healthy` : `${connName}: ${result.message}`, result.status === "healthy" ? "success" : "error");
    } catch (e) { toast(_parseError(e), "error"); } finally { setSaving(false); }
  }

  function handleEditConnection(conn: ConnectionInfo) {
    const connConfig = DB_CONFIGS[conn.db_type as DBType] || DB_CONFIGS.postgres;
    setForm({
      ...defaultForm,
      name: conn.name,
      db_type: conn.db_type as DBType,
      connectionMode: connConfig.connectionModes[0],
      host: conn.host || "",
      port: String(conn.port || connConfig.defaultPort || ""),
      database: conn.database || "",
      username: conn.username || "",
      password: "", // Never pre-fill passwords
      description: conn.description || "",
      account: conn.account || "",
      warehouse: conn.warehouse || "",
      schema_name: conn.schema_name || "",
      role: conn.role || "",
      project: conn.project || "",
      dataset: conn.dataset || "",
      bq_location: (conn as any).location || "",
      bq_max_bytes_billed: (conn as any).maximum_bytes_billed ? String((conn as any).maximum_bytes_billed) : "",
      http_path: conn.http_path || "",
      catalog: conn.catalog || "",
      ssl_enabled: conn.ssl || false,
      ssl_mode: conn.ssl_config?.mode || "require",
      ssl_ca_cert: conn.ssl_config?.ca_cert || "",
      ssl_client_cert: conn.ssl_config?.client_cert || "",
      ssl_client_key: conn.ssl_config?.client_key || "",
      ssh_enabled: conn.ssh_tunnel?.enabled || false,
      ssh_host: conn.ssh_tunnel?.host || "",
      ssh_port: String(conn.ssh_tunnel?.port || 22),
      ssh_username: conn.ssh_tunnel?.username || "",
      ssh_auth_method: conn.ssh_tunnel?.auth_method || "password",
      tags: conn.tags || [],
      schema_refresh_enabled: !!(conn.schema_refresh_interval),
      schema_refresh_interval: String(conn.schema_refresh_interval || 300),
      scope: (conn as any).scope || "workspace",
      read_only: (conn as any).read_only !== false,
      schema_filter_include: (conn.schema_filter_include || []).join(", "),
      schema_filter_exclude: (conn.schema_filter_exclude || []).join(", "),
      connection_timeout: String(conn.connection_timeout || 15),
      query_timeout: String(conn.query_timeout || 120),
      keepalive_interval: String(conn.keepalive_interval || 0),
      // Pool size (PostgreSQL)
      pool_min_size: String((conn as any).pool_min_size || 1),
      pool_max_size: String((conn as any).pool_max_size || 5),
      // IAM auth
      iam_auth: (conn as any).auth_method === "iam",
      aws_region: (conn as any).aws_region || "us-east-1",
      aws_access_key_id: "", // Never pre-fill secrets
      aws_secret_access_key: "",
      redshift_cluster_id: (conn as any).cluster_id || "",
      redshift_workgroup: (conn as any).workgroup || "",
      // Azure AD auth
      azure_ad_auth: (conn as any).auth_method === "azure_ad",
      azure_tenant_id: (conn as any).azure_tenant_id || "",
      azure_client_id: (conn as any).azure_client_id || "",
      azure_client_secret: "", // Never pre-fill secrets
    });
    setEditingConnection(conn.name);
    setShowForm(true);
    const hasCustomTimeouts = (conn.connection_timeout && conn.connection_timeout !== 15) || (conn.query_timeout && conn.query_timeout !== 120) || (conn.keepalive_interval && conn.keepalive_interval > 0);
    setShowAdvanced(!!(conn.ssl || conn.ssh_tunnel?.enabled || conn.schema_refresh_interval || conn.schema_filter_include?.length || conn.schema_filter_exclude?.length || hasCustomTimeouts));
  }

  async function handleTest(name: string) {
    setTesting(name);
    try {
      const result = await testConnection(name);
      setTestResult((prev) => ({ ...prev, [name]: result }));
      toast(result.status === "healthy" ? `${name}: connection healthy` : `${name}: ${result.message}`, result.status === "healthy" ? "success" : "error");
    } catch (e) {
      setTestResult((prev) => ({ ...prev, [name]: { status: "error", message: String(e) } }));
      toast(`${name}: test failed`, "error");
    } finally { setTesting(null); }
  }

  async function handleGenerateSemantic(name: string) {
    try {
      const result = await generateSemanticModel(name);
      toast(`${name}: semantic model generated — ${result.joins} joins, ${result.glossary_terms} glossary terms`, "success");
    } catch (e) {
      toast(`${name}: semantic model generation failed — ${String(e)}`, "error");
    }
  }

  async function handleDiagnose(name: string) {
    setDiagnosing(name);
    try {
      const result = await diagnoseConnection(name);
      setDiagResults((prev) => ({ ...prev, [name]: result }));
      const allOk = result.diagnostics.every((d: { status: string }) => d.status === "ok");
      toast(allOk ? `${name}: all checks passed` : `${name}: see diagnostic results`, allOk ? "success" : "info");
    } catch (e) {
      toast(`${name}: diagnose failed — ${String(e)}`, "error");
    } finally { setDiagnosing(null); }
  }

  async function handleDelete(name: string) { setDeleteTarget(name); }

  async function confirmDelete() {
    if (!deleteTarget) return;
    await deleteConnection(deleteTarget);
    refresh();
    toast(`${deleteTarget} deleted`, "info");
    setDeleteTarget(null);
  }

  async function handleClone(name: string) {
    const newName = prompt(`Clone "${name}" as:`, `${name}-copy`);
    if (!newName || !newName.trim()) return;
    try {
      await cloneConnection(name, newName.trim());
      refresh();
      toast(`Cloned as "${newName.trim()}"`, "success");
    } catch (err: any) {
      toast(`Clone failed: ${err.message?.slice(0, 80) || "unknown error"}`, "error");
    }
  }

  async function handleToggleSchema(name: string) {
    if (expandedConn === name) { setExpandedConn(null); return; }
    setExpandedConn(name);
    if (!schemaData[name]) {
      setSchemaLoading(name);
      try {
        const data = await getConnectionSchema(name);
        setSchemaData((prev) => ({ ...prev, [name]: { tables: data.tables } }));
      } catch { setSchemaData((prev) => ({ ...prev, [name]: { tables: {} } })); }
      finally { setSchemaLoading(null); }
    }
    // Load endorsements if not cached
    if (!endorsements[name]) {
      try {
        const e = await getSchemaEndorsements(name);
        setEndorsements(prev => ({ ...prev, [name]: e }));
      } catch {}
    }
  }

  async function handleScanPII(name: string) {
    setPiiLoading(name);
    try {
      const data = await detectPII(name);
      setPiiData((prev) => ({ ...prev, [name]: data }));
    } catch { setPiiData((prev) => ({ ...prev, [name]: { tables_scanned: 0, tables_with_pii: 0, detections: {} } })); }
    finally { setPiiLoading(null); }
  }

  const searchTimerRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  function handleSchemaSearch(name: string, query: string) {
    setSchemaSearch((prev) => ({ ...prev, [name]: query }));
    // Clear previous debounce timer
    if (searchTimerRef.current[name]) {
      clearTimeout(searchTimerRef.current[name]);
    }
    if (!query.trim()) {
      setSchemaSearchResults((prev) => { const n = { ...prev }; delete n[name]; return n; });
      return;
    }
    // Debounce 300ms to avoid excessive API calls
    searchTimerRef.current[name] = setTimeout(async () => {
      setSchemaSearchLoading(name);
      try {
        const data = await searchConnectionSchema(name, query);
        setSchemaSearchResults((prev) => ({ ...prev, [name]: { result_count: data.result_count, total_tables: data.total_tables, tables: data.tables } }));
      } catch {
        setSchemaSearchResults((prev) => ({ ...prev, [name]: { result_count: 0, total_tables: 0, tables: {} } }));
      } finally {
        setSchemaSearchLoading(null);
      }
    }, 300);
  }

  async function handleExport() {
    try {
      const data = await exportConnections(false);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `signalpilot-connections-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Export failed:", err);
    }
  }

  async function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const manifest = JSON.parse(text);
      const result = await importConnections(manifest);
      refresh();
      const msg = [`Imported: ${result.imported}`];
      if (result.skipped.length) msg.push(`Skipped (existing): ${result.skipped.join(", ")}`);
      if (result.errors.length) msg.push(`Errors: ${result.errors.map(e => `${e.name}: ${e.error}`).join("; ")}`);
      alert(msg.join("\n"));
    } catch (err) {
      alert(`Import failed: ${err instanceof Error ? err.message : err}`);
    }
    // Reset file input
    if (importFileRef.current) importFileRef.current.value = "";
  }

  const config = DB_CONFIGS[form.db_type];

  return (
    <div className="p-8 animate-fade-in">
      <input
        ref={importFileRef}
        type="file"
        accept=".json"
        className="hidden"
        onChange={handleImportFile}
      />
      <PageHeader
        title="connections"
        subtitle="databases"
        description="manage database connections for governed ai access"
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={handleExport}
              className="flex items-center gap-1.5 px-3 py-2 border border-[var(--color-border)] text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-all tracking-wider"
              title="Export connections"
            >
              <Download className="w-3 h-3" /> export
            </button>
            <button
              onClick={() => importFileRef.current?.click()}
              className="flex items-center gap-1.5 px-3 py-2 border border-[var(--color-border)] text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-all tracking-wider"
              title="Import connections from JSON"
            >
              <Upload className="w-3 h-3" /> import
            </button>
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90"
            >
              <Plus className="w-3.5 h-3.5" /> add connection
            </button>
          </div>
        }
      />

      <TerminalBar
        path="connections --list"
        status={<StatusDot status={connections.length > 0 ? "healthy" : "unknown"} size={4} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">registered: <code className="text-[10px] text-[var(--color-text)]">{connections.length}</code></span>
        </div>
      </TerminalBar>

      {/* ─── Create Connection Form ─── */}
      {showForm && (
        <div className="mb-6 border border-[var(--color-border)] bg-[var(--color-bg-card)] animate-scale-in overflow-hidden">
          <div className="px-6 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
            <div className="flex items-center gap-2">
              <DbTypeIcon type={form.db_type} />
              <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                {editingConnection ? `edit ${editingConnection}` : `new ${DB_CONFIGS[form.db_type].label} connection`}
              </span>
            </div>
            <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider opacity-50">
              {DB_CONFIGS[form.db_type].description}
            </span>
          </div>

          <div className="p-6">
            {/* DB Type Selector — visual grid */}
            <div className="mb-5">
              <label className="block text-[10px] text-[var(--color-text-dim)] mb-2 tracking-wider">database type</label>
              <div className="flex flex-wrap gap-1.5">
                {DB_TYPE_ORDER.map((dbType) => {
                  const cfg = DB_CONFIGS[dbType];
                  const isSelected = form.db_type === dbType;
                  return (
                    <button
                      key={dbType}
                      onClick={() => handleDbTypeChange(dbType)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 text-[10px] tracking-wider border transition-all ${
                        isSelected
                          ? "border-[var(--color-text)] text-[var(--color-text)] bg-[var(--color-text)]/5"
                          : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
                      }`}
                    >
                      <DbTypeIcon type={dbType} />
                      {cfg.label}
                      <span className={`text-[8px] opacity-60 ${CONNECTOR_TIERS[dbType]?.tier === 1 ? "text-emerald-400" : CONNECTOR_TIERS[dbType]?.tier === 2 ? "text-sky-400" : "text-zinc-400"}`}>
                        {CONNECTOR_TIERS[dbType]?.label}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Name + Description */}
            <div className="grid grid-cols-2 gap-4 mb-4">
              {editingConnection ? (
                <div>
                  <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">connection name</label>
                  <div className="px-3 py-2 bg-[var(--color-bg-hover)] border border-[var(--color-border)] text-xs text-[var(--color-text-dim)] tracking-wide">{editingConnection}</div>
                </div>
              ) : (
                <FormInput label="connection name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} placeholder="prod-analytics" hint="alphanumeric, dashes, underscores" required />
              )}
              <FormInput label="description" value={form.description} onChange={(v) => setForm({ ...form, description: v })} placeholder="Production analytics DB" />
            </div>

            {/* Tags */}
            <div className="mb-4">
              <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">tags</label>
              <div className="flex flex-wrap items-center gap-1.5">
                {form.tags.map((tag) => (
                  <span key={tag} className="flex items-center gap-1 px-2 py-0.5 text-[9px] bg-[var(--color-bg-hover)] border border-[var(--color-border)] text-[var(--color-text-dim)] tracking-wider">
                    {tag}
                    <button type="button" onClick={() => setForm({ ...form, tags: form.tags.filter(t => t !== tag) })} className="text-[var(--color-text-dim)] hover:text-[var(--color-error)] ml-0.5">&times;</button>
                  </span>
                ))}
                <input
                  type="text"
                  value={form.tagInput}
                  onChange={(e) => setForm({ ...form, tagInput: e.target.value })}
                  onKeyDown={(e) => {
                    if ((e.key === "Enter" || e.key === ",") && form.tagInput.trim()) {
                      e.preventDefault();
                      const tag = form.tagInput.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
                      if (tag && !form.tags.includes(tag)) {
                        setForm({ ...form, tags: [...form.tags, tag], tagInput: "" });
                      } else {
                        setForm({ ...form, tagInput: "" });
                      }
                    }
                  }}
                  placeholder={form.tags.length === 0 ? "prod, analytics, team-data..." : "add tag..."}
                  className="flex-1 min-w-[100px] px-2 py-1 text-[10px] bg-transparent border-none outline-none text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] tracking-wider"
                />
              </div>
              <p className="text-[9px] text-[var(--color-text-dim)] mt-1 tracking-wider opacity-60">press enter or comma to add — organize connections by environment, team, or purpose</p>
            </div>

            {/* Connection mode toggle (fields vs URL) — bidirectional sync */}
            {config.connectionModes.length > 1 && (
              <div className="flex items-center gap-3 mb-4">
                <span className="text-[10px] text-[var(--color-text-dim)] tracking-wider">connect via:</span>
                {config.connectionModes.map((mode) => (
                  <button
                    key={mode}
                    onClick={() => {
                      if (mode === form.connectionMode) return;
                      if (mode === "url") {
                        // Fields → URL: build connection string from current fields
                        const preview = buildConnectionPreview({ ...form, connectionMode: "fields" });
                        setForm({ ...form, connectionMode: "url", connection_string: preview.replace(":****@", `:${form.password || ""}@`) });
                      } else {
                        // URL → Fields: parse connection string into fields
                        const parsed = parseConnectionUrl(form.connection_string, form.db_type);
                        setForm({ ...form, connectionMode: "fields", ...parsed });
                      }
                    }}
                    className={`flex items-center gap-1.5 px-2.5 py-1 text-[10px] tracking-wider border transition-all ${
                      form.connectionMode === mode
                        ? "border-[var(--color-text)] text-[var(--color-text)]"
                        : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
                    }`}
                  >
                    {mode === "url" ? <Link2 className="w-3 h-3" strokeWidth={1.5} /> : <Settings2 className="w-3 h-3" strokeWidth={1.5} />}
                    {mode === "url" ? "connection string" : "individual fields"}
                  </button>
                ))}
              </div>
            )}

            {/* DB-specific fields */}
            <div className="grid grid-cols-2 gap-4 mb-4">
              <ConnectionFieldsForm form={form} setForm={setForm} />
            </div>

            {/* Connection string preview with copy button */}
            {form.connectionMode !== "url" && (
              <div className="mb-4 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed">
                <div className="flex items-center gap-2">
                  <Link2 className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
                  <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">connection preview</span>
                  <div className="flex-1" />
                  <button
                    type="button"
                    onClick={() => {
                      const fullUrl = buildConnectionPreview({ ...form, connectionMode: "fields" }).replace(":****@", `:${form.password || ""}@`);
                      navigator.clipboard.writeText(fullUrl).then(() => toast("Connection URL copied", "info"));
                    }}
                    className="text-[9px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider transition-colors"
                  >
                    copy url
                  </button>
                </div>
                <code className="text-[10px] text-[var(--color-text-muted)] tracking-wide break-all">{buildConnectionPreview(form)}</code>
              </div>
            )}

            {/* Advanced: SSL + SSH + Access Controls + Schema Refresh */}
            <div>
              <button
                type="button"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex items-center gap-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider mb-2"
              >
                {showAdvanced ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                advanced options
                {(form.ssl_enabled || form.ssh_enabled || !form.read_only || form.schema_refresh_enabled || form.connection_timeout !== "15" || form.query_timeout !== "120") && (
                  <span className="text-[var(--color-success)] text-[9px] ml-1">
                    {[form.ssl_enabled && "ssl", form.ssh_enabled && "ssh", !form.read_only && "read-write", form.schema_refresh_enabled && "auto-refresh", (form.connection_timeout !== "15" || form.query_timeout !== "120") && "custom timeouts"].filter(Boolean).join(" + ")}
                  </span>
                )}
              </button>
                {showAdvanced && (
                  <div className="animate-fade-in">
                    <SSLSection form={form} setForm={setForm} />
                    <SSHSection form={form} setForm={setForm} />
                    {/* Connection Scope + Read-only (HEX pattern) */}
                    <div className="border-t border-[var(--color-border)] pt-4 mt-4">
                      <div className="flex items-center gap-2 text-[10px] text-[var(--color-text-dim)] tracking-wider mb-3">
                        <Settings2 className="w-3 h-3" strokeWidth={1.5} />
                        <span>access controls</span>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">connection scope</label>
                          <select
                            value={form.scope}
                            onChange={(e) => setForm({ ...form, scope: e.target.value as "workspace" | "project" })}
                            className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
                          >
                            <option value="workspace">workspace — all projects</option>
                            <option value="project">project — current only</option>
                          </select>
                          <p className="text-[8px] text-[var(--color-text-dim)] mt-1 tracking-wider opacity-60">
                            workspace connections are shared across all projects
                          </p>
                        </div>
                        <div>
                          <label className="flex items-center gap-2 cursor-pointer mt-5">
                            <input
                              type="checkbox"
                              checked={form.read_only}
                              onChange={(e) => setForm({ ...form, read_only: e.target.checked })}
                              className="accent-[var(--color-text)]"
                            />
                            <span className="text-[10px] text-[var(--color-text-muted)] tracking-wider">
                              read-only mode
                            </span>
                          </label>
                          <p className="text-[8px] text-[var(--color-text-dim)] mt-1 tracking-wider opacity-60 ml-5">
                            only SELECT queries allowed (recommended)
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* IP Allowlist Info */}
                    <div className="border-t border-[var(--color-border)] pt-4 mt-4">
                      <div className="flex items-center gap-2 text-[10px] text-[var(--color-text-dim)] tracking-wider mb-2">
                        <Shield className="w-3 h-3" strokeWidth={1.5} />
                        <span>ip allowlisting</span>
                      </div>
                      <div className="px-3 py-2.5 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed">
                        <p className="text-[9px] text-[var(--color-text-dim)] tracking-wider mb-1.5">
                          if your database requires ip allowlisting, add this signalpilot server ip to your firewall rules:
                        </p>
                        <div className="flex flex-wrap gap-2">
                          <code className="text-[10px] text-[var(--color-text)] bg-[var(--color-bg-hover)] px-2 py-0.5 tracking-wider font-mono">
                            {serverIp ? `${serverIp}/32` : "detecting..."}
                          </code>
                          {serverIp && (
                            <button
                              type="button"
                              onClick={() => { navigator.clipboard.writeText(serverIp); toast("IP copied to clipboard", "success"); }}
                              className="text-[9px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider transition-colors"
                            >
                              <Copy className="w-3 h-3 inline" /> copy
                            </button>
                          )}
                        </div>
                        <p className="text-[8px] text-[var(--color-text-dim)] tracking-wider mt-1.5 opacity-60">
                          {serverIp ? "add this ip to your database firewall, security group, or network policy." : "fetching server ip..."}
                        </p>
                      </div>
                    </div>

                    {/* Schema Filtering */}
                    <div className="border-t border-[var(--color-border)] pt-4 mt-4">
                      <div className="flex items-center gap-2 text-[10px] text-[var(--color-text-dim)] tracking-wider mb-2">
                        <Filter className="w-3 h-3" strokeWidth={1.5} />
                        <span>schema filtering</span>
                      </div>
                      <div className="text-[8px] text-[var(--color-text-dim)] tracking-wider mb-3 opacity-60">
                        filter which schemas are visible to the ai agent. excludes staging, dev, and raw schemas to improve accuracy.
                      </div>
                      <div className="space-y-3">
                        <div>
                          <label className="block text-[9px] text-[var(--color-text-muted)] tracking-wider mb-1">
                            include schemas <span className="opacity-50">(comma-separated, empty = all)</span>
                          </label>
                          <input
                            type="text"
                            placeholder="public, analytics, production"
                            value={form.schema_filter_include}
                            onChange={(e) => setForm({ ...form, schema_filter_include: e.target.value })}
                            className="w-full bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text)] text-[10px] px-3 py-2 tracking-wider placeholder:text-[var(--color-text-dim)]"
                          />
                        </div>
                        <div>
                          <label className="block text-[9px] text-[var(--color-text-muted)] tracking-wider mb-1">
                            exclude schemas <span className="opacity-50">(comma-separated, glob patterns supported)</span>
                          </label>
                          <input
                            type="text"
                            placeholder="staging*, dev*, raw, tmp*, _dbt_*"
                            value={form.schema_filter_exclude}
                            onChange={(e) => setForm({ ...form, schema_filter_exclude: e.target.value })}
                            className="w-full bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text)] text-[10px] px-3 py-2 tracking-wider placeholder:text-[var(--color-text-dim)]"
                          />
                        </div>
                      </div>
                    </div>

                    {/* Scheduled Schema Refresh */}
                    <div className="border-t border-[var(--color-border)] pt-4 mt-4">
                      <div className="flex items-center gap-2 text-[10px] text-[var(--color-text-dim)] tracking-wider mb-2">
                        <RefreshCw className="w-3 h-3" strokeWidth={1.5} />
                        <span>scheduled schema refresh</span>
                      </div>
                      <div className="flex items-center gap-3 mb-2">
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={form.schema_refresh_enabled}
                            onChange={(e) => setForm({ ...form, schema_refresh_enabled: e.target.checked })}
                            className="accent-[var(--color-text)]"
                          />
                          <span className="text-[10px] text-[var(--color-text-muted)] tracking-wider">
                            auto-refresh schema metadata
                          </span>
                        </label>
                      </div>
                      {form.schema_refresh_enabled && (
                        <div className="flex items-center gap-2 animate-fade-in">
                          <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">every</span>
                          <select
                            value={form.schema_refresh_interval}
                            onChange={(e) => setForm({ ...form, schema_refresh_interval: e.target.value })}
                            className="bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text)] text-[10px] px-2 py-1 tracking-wider"
                          >
                            <option value="60">1 min</option>
                            <option value="300">5 min</option>
                            <option value="900">15 min</option>
                            <option value="1800">30 min</option>
                            <option value="3600">1 hour</option>
                            <option value="14400">4 hours</option>
                            <option value="43200">12 hours</option>
                            <option value="86400">24 hours</option>
                          </select>
                          <span className="text-[8px] text-[var(--color-text-dim)] tracking-wider opacity-60">
                            keeps ai agent schema knowledge current
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Connection Timeouts */}
                    <div className="border-t border-[var(--color-border)] pt-4 mt-4">
                      <div className="flex items-center gap-2 text-[10px] text-[var(--color-text-dim)] tracking-wider mb-3">
                        <Clock className="w-3 h-3" strokeWidth={1.5} />
                        <span>timeouts & keepalive</span>
                      </div>
                      <div className="grid grid-cols-3 gap-4">
                        <div>
                          <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">connection timeout</label>
                          <div className="flex items-center gap-1.5">
                            <input
                              type="number"
                              min="1"
                              max="300"
                              value={form.connection_timeout}
                              onChange={(e) => setForm({ ...form, connection_timeout: e.target.value })}
                              className="w-20 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tabular-nums"
                            />
                            <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">sec</span>
                          </div>
                          <p className="text-[8px] text-[var(--color-text-dim)] mt-1 tracking-wider opacity-60">max time to establish connection</p>
                        </div>
                        <div>
                          <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">query timeout</label>
                          <div className="flex items-center gap-1.5">
                            <input
                              type="number"
                              min="1"
                              max="3600"
                              value={form.query_timeout}
                              onChange={(e) => setForm({ ...form, query_timeout: e.target.value })}
                              className="w-20 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tabular-nums"
                            />
                            <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">sec</span>
                          </div>
                          <p className="text-[8px] text-[var(--color-text-dim)] mt-1 tracking-wider opacity-60">max query execution time</p>
                        </div>
                        <div>
                          <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">keepalive interval</label>
                          <div className="flex items-center gap-1.5">
                            <select
                              value={form.keepalive_interval}
                              onChange={(e) => setForm({ ...form, keepalive_interval: e.target.value })}
                              className="bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text)] text-[10px] px-2 py-2 tracking-wider"
                            >
                              <option value="0">disabled</option>
                              <option value="30">30 sec</option>
                              <option value="60">1 min</option>
                              <option value="120">2 min</option>
                              <option value="300">5 min</option>
                            </select>
                          </div>
                          <p className="text-[8px] text-[var(--color-text-dim)] mt-1 tracking-wider opacity-60">ping to prevent idle disconnect</p>
                        </div>
                      </div>
                      {/* Pool sizing — only for pool-capable connectors */}
                      {(form.db_type === "postgres") && (
                        <div className="grid grid-cols-2 gap-4 mt-3 pt-3 border-t border-[var(--color-border)]/50">
                          <div>
                            <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">pool min size</label>
                            <div className="flex items-center gap-1.5">
                              <input type="number" min="1" max="20" value={form.pool_min_size} onChange={(e) => setForm({ ...form, pool_min_size: e.target.value })} className="w-20 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tabular-nums" />
                              <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">conns</span>
                            </div>
                            <p className="text-[8px] text-[var(--color-text-dim)] mt-1 tracking-wider opacity-60">minimum idle connections</p>
                          </div>
                          <div>
                            <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">pool max size</label>
                            <div className="flex items-center gap-1.5">
                              <input type="number" min="1" max="50" value={form.pool_max_size} onChange={(e) => setForm({ ...form, pool_max_size: e.target.value })} className="w-20 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tabular-nums" />
                              <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">conns</span>
                            </div>
                            <p className="text-[8px] text-[var(--color-text-dim)] mt-1 tracking-wider opacity-60">max concurrent connections</p>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>

            {/* Action buttons */}
            <div className="flex items-center gap-3 mt-5 pt-4 border-t border-[var(--color-border)]">
              <button onClick={handleCreate} disabled={saving || (!editingConnection && !form.name)} className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30">
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {editingConnection ? "update connection" : "save connection"}
              </button>
              <button onClick={handleSaveAndTest} disabled={saving || (!editingConnection && !form.name)} className="flex items-center gap-2 px-4 py-2 border border-[var(--color-border)] text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-all tracking-wider">
                <TestTube className="w-3.5 h-3.5" strokeWidth={1.5} />
                {editingConnection ? "update & test" : "save & test"}
              </button>
              <button onClick={() => { setShowForm(false); setEditingConnection(null); setForm({ ...defaultForm }); setShowAdvanced(false); }} className="px-4 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider">
                cancel
              </button>
              {editingConnection && (
                <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider opacity-60 ml-auto">
                  leave password blank to keep existing credentials
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ─── Connections List ─── */}
      {connections.length === 0 && !showForm ? (
        <EmptyState
          icon={EmptyDatabase}
          title="no connections configured"
          description="add a database connection to enable governed sql queries and sandbox access"
          action={
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider"
            >
              <Plus className="w-3.5 h-3.5" /> add first connection
            </button>
          }
        />
      ) : (
        <div className="space-y-2">
          {/* Tag filter bar */}
          {(() => {
            const allTags = [...new Set(connections.flatMap(c => c.tags || []))].sort();
            if (allTags.length === 0) return null;
            return (
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">filter:</span>
                {allTags.map((tag) => (
                  <button
                    key={tag}
                    onClick={() => setFilterTag(filterTag === tag ? null : tag)}
                    className={`px-2 py-0.5 text-[9px] tracking-wider border transition-all ${
                      filterTag === tag
                        ? "border-blue-500 text-blue-400 bg-blue-500/10"
                        : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-blue-500/50 hover:text-blue-400"
                    }`}
                  >
                    {tag}
                  </button>
                ))}
                {filterTag && (
                  <button onClick={() => setFilterTag(null)} className="text-[9px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider ml-1">clear</button>
                )}
              </div>
            );
          })()}
          {connections.filter(c => !filterTag || (c.tags || []).includes(filterTag)).map((conn) => {
            const health = healthData[conn.name];
            const isExpanded = expandedConn === conn.name;
            const tables = schemaData[conn.name]?.tables;
            const connConfig = DB_CONFIGS[conn.db_type as DBType] || DB_CONFIGS.postgres;

            // Build display string
            let displayStr = "";
            if (conn.host && conn.port) {
              displayStr = `${conn.host}:${conn.port}/${conn.database || ""}`;
            } else if (conn.account) {
              displayStr = `${conn.account}/${conn.database || ""}`;
            } else if (conn.project) {
              displayStr = `${conn.project}/${conn.dataset || ""}`;
            } else if (conn.database) {
              displayStr = conn.database;
            }

            return (
              <div key={conn.id} className="bg-[var(--color-bg-card)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] transition-all card-accent-top">
                <div className="flex items-center gap-4 p-4">
                  {/* Status indicator */}
                  <div className="flex-shrink-0">
                    <StatusDot
                      status={
                        health?.status === "healthy" ? "healthy" :
                        health?.status === "warning" ? "warning" :
                        health?.status === "degraded" || health?.status === "unhealthy" ? "error" :
                        "unknown"
                      }
                      size={5}
                      pulse={health?.status === "healthy"}
                    />
                  </div>

                  {/* Connection info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-[var(--color-text)]">{conn.name}</span>
                      <span className="flex items-center gap-1 text-[9px] px-1.5 py-0.5 border border-[var(--color-border)] text-[var(--color-text-dim)] tracking-wider">
                        <DbTypeIcon type={conn.db_type} />
                        {dbTypeLabels[conn.db_type] || conn.db_type}
                      </span>
                      <Tooltip content={`Tier ${CONNECTOR_TIERS[conn.db_type as DBType]?.tier || 3}: ${CONNECTOR_TIERS[conn.db_type as DBType]?.tier === 1 ? "Full support" : CONNECTOR_TIERS[conn.db_type as DBType]?.tier === 2 ? "Stable" : "Basic"}`} position="top">
                        <span className={`text-[9px] px-1 py-0.5 border tracking-wider cursor-default ${CONNECTOR_TIERS[conn.db_type as DBType]?.color || "text-zinc-400 border-zinc-500/30"}`}>
                          {CONNECTOR_TIERS[conn.db_type as DBType]?.label || "T3"}
                        </span>
                      </Tooltip>
                      {conn.ssl && (
                        <span className="text-[9px] px-1 py-0.5 border border-[var(--color-success)]/30 text-[var(--color-success)] tracking-wider">ssl</span>
                      )}
                      {conn.ssh_tunnel?.enabled && (
                        <span className="text-[9px] px-1 py-0.5 border border-purple-500/30 text-purple-400 tracking-wider">ssh</span>
                      )}
                      {conn.tags?.map((tag) => (
                        <span key={tag} className="text-[9px] px-1 py-0.5 border border-blue-500/30 text-blue-400 tracking-wider">{tag}</span>
                      ))}
                      {health && (
                        <span className={`text-[10px] tracking-wider ${
                          health.status === "healthy" ? "text-[var(--color-success)]" :
                          health.status === "warning" ? "text-[var(--color-warning)]" :
                          "text-[var(--color-error)]"
                        }`}>
                          {health.status}
                        </span>
                      )}
                    </div>
                    <div className="text-[10px] text-[var(--color-text-dim)] mt-0.5 tracking-wider">
                      {displayStr}
                      {conn.description && <span className="ml-2 text-[var(--color-text-dim)]">— {conn.description}</span>}
                      {conn.last_used && (
                        <span className="ml-2 text-[var(--color-text-dim)] opacity-60" title={new Date(conn.last_used * 1000).toLocaleString()}>
                          last used {(() => {
                            const diff = Math.floor(Date.now() / 1000 - conn.last_used);
                            if (diff < 60) return "just now";
                            if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
                            if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
                            return `${Math.floor(diff / 86400)}d ago`;
                          })()}
                        </span>
                      )}
                    </div>
                    {health && health.sample_count > 0 && (
                      <div className="flex items-center gap-4 mt-1.5 text-[9px] text-[var(--color-text-dim)] tracking-wider">
                        <span className="flex items-center gap-1">
                          <Activity className="w-2.5 h-2.5" strokeWidth={1.5} />
                          {health.sample_count} queries
                        </span>
                        {health.error_rate != null && health.error_rate > 0 && (
                          <span className="flex items-center gap-1 text-[var(--color-error)]">
                            <AlertTriangle className="w-2.5 h-2.5" strokeWidth={1.5} />
                            {(health.error_rate * 100).toFixed(1)}% errors
                          </span>
                        )}
                        {health.latency_p50_ms != null && (
                          <Tooltip content={`p50: ${health.latency_p50_ms.toFixed(1)}ms${health.latency_p95_ms ? ` · p95: ${health.latency_p95_ms.toFixed(1)}ms` : ""}`} position="top">
                            <span className="flex items-center gap-1.5 tabular-nums cursor-default">
                              <Clock className="w-2.5 h-2.5" strokeWidth={1.5} />
                              <MiniBar
                                value={health.latency_p50_ms}
                                max={300}
                                width={32}
                                height={3}
                                color={health.latency_p50_ms < 50 ? "var(--color-success)" : health.latency_p50_ms < 150 ? "var(--color-warning)" : "var(--color-error)"}
                              />
                              <span className={
                                health.latency_p50_ms < 50 ? "text-[var(--color-success)]" :
                                health.latency_p50_ms < 150 ? "text-[var(--color-text-dim)]" :
                                "text-[var(--color-error)]"
                              }>
                                {health.latency_p50_ms.toFixed(0)}ms
                              </span>
                            </span>
                          </Tooltip>
                        )}
                        {health.latency_p95_ms != null && (
                          <span className="flex items-center gap-1 tabular-nums">
                            p95: {health.latency_p95_ms.toFixed(0)}ms
                          </span>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Test result — compact summary + expandable detail */}
                  {testResult[conn.name] && (
                    <div className="flex flex-col gap-0.5">
                      <span className={`flex items-center gap-1.5 text-[10px] tracking-wider ${
                        testResult[conn.name].status === "healthy" ? "text-[var(--color-success)]"
                        : testResult[conn.name].status === "warning" ? "text-[var(--color-warning)]"
                        : "text-[var(--color-error)]"
                      }`}>
                        {testResult[conn.name].status === "healthy" ? <CheckCircle2 className="w-3 h-3" />
                         : testResult[conn.name].status === "warning" ? <AlertTriangle className="w-3 h-3" />
                         : <XCircle className="w-3 h-3" />}
                        {testResult[conn.name].phases ? (
                          <span className="flex items-center gap-2">
                            {testResult[conn.name].phases!.map((p, i) => {
                              const phaseLabel = p.phase === "ssh_tunnel" ? "SSH"
                                : p.phase === "schema_access" ? "Schema"
                                : p.phase === "database" ? "Auth"
                                : p.phase;
                              const statusIcon = p.status === "ok" ? "\u2713" : p.status === "warning" ? "!" : "\u2717";
                              const statusColor = p.status === "ok" ? "text-[var(--color-success)]"
                                : p.status === "warning" ? "text-[var(--color-warning)]"
                                : "text-[var(--color-error)]";
                              return (
                                <Tooltip key={i} content={p.message || phaseLabel} position="top">
                                  <span className={`${statusColor} cursor-default tabular-nums`}>
                                    {phaseLabel}{statusIcon}
                                    {p.duration_ms ? ` ${p.duration_ms}ms` : ""}
                                  </span>
                                </Tooltip>
                              );
                            })}
                            {testResult[conn.name].total_duration_ms != null && (
                              <span className="text-[9px] text-[var(--color-text-dim)] tabular-nums">
                                total: {testResult[conn.name].total_duration_ms}ms
                              </span>
                            )}
                          </span>
                        ) : (
                          <Tooltip content={testResult[conn.name].message} position="top">
                            <span className="cursor-default">{testResult[conn.name].message.slice(0, 50)}</span>
                          </Tooltip>
                        )}
                      </span>
                    </div>
                  )}

                  {/* Diagnostic results */}
                  {diagResults[conn.name] && (
                    <div className="flex flex-col gap-0.5">
                      <span className="flex items-center gap-2 text-[10px] tracking-wider">
                        {diagResults[conn.name].diagnostics.map((d, i) => {
                          const statusColor = d.status === "ok" ? "text-[var(--color-success)]"
                            : d.status === "warning" ? "text-[var(--color-warning)]"
                            : "text-[var(--color-error)]";
                          const icon = d.status === "ok" ? "\u2713" : d.status === "warning" ? "!" : "\u2717";
                          return (
                            <Tooltip key={i} content={d.hint || d.message} position="top">
                              <span className={`${statusColor} cursor-default tabular-nums`}>
                                {d.check}{icon} {d.duration_ms}ms
                              </span>
                            </Tooltip>
                          );
                        })}
                      </span>
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="flex items-center gap-1">
                    <button onClick={(e) => { e.stopPropagation(); handleToggleSchema(conn.name); }}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-all tracking-wider">
                      {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      <Table2 className="w-3 h-3" strokeWidth={1.5} /> schema
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); handleScanPII(conn.name); }} disabled={piiLoading === conn.name}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-all tracking-wider">
                      {piiLoading === conn.name ? <Loader2 className="w-3 h-3 animate-spin" /> : <Eye className="w-3 h-3" strokeWidth={1.5} />}
                      pii
                      {piiData[conn.name] && piiData[conn.name].tables_with_pii > 0 && (
                        <span className="ml-1 px-1 py-0.5 border badge-warning text-[9px] tabular-nums">
                          {piiData[conn.name].tables_with_pii}
                        </span>
                      )}
                    </button>
                    <button onClick={() => handleTest(conn.name)} disabled={testing === conn.name}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-all tracking-wider">
                      {testing === conn.name ? <Loader2 className="w-3 h-3 animate-spin" /> : <TestTube className="w-3 h-3" strokeWidth={1.5} />}
                      test
                    </button>
                    <button onClick={() => handleDiagnose(conn.name)} disabled={diagnosing === conn.name}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-all tracking-wider">
                      {diagnosing === conn.name ? <Loader2 className="w-3 h-3 animate-spin" /> : <Activity className="w-3 h-3" strokeWidth={1.5} />}
                      diagnose
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); handleEditConnection(conn); }}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-all tracking-wider">
                      <Pencil className="w-3 h-3" strokeWidth={1.5} /> edit
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); handleClone(conn.name); }}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-all tracking-wider">
                      <Copy className="w-3 h-3" strokeWidth={1.5} /> clone
                    </button>
                    <button onClick={() => handleDelete(conn.name)}
                      className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-error)] hover:bg-[var(--color-error)]/5 transition-all">
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>

                {/* Inline schema browser */}
                {isExpanded && (
                  <div className="border-t border-[var(--color-border)] px-4 py-4 animate-fade-in">
                    {schemaLoading === conn.name ? (
                      <div className="flex items-center gap-2 py-4 justify-center text-xs text-[var(--color-text-dim)] tracking-wider">
                        <Loader2 className="w-3.5 h-3.5 animate-spin" /> loading schema...
                      </div>
                    ) : tables && Object.keys(tables).length > 0 ? (
                      <div className="space-y-2">
                        <div className="flex items-center gap-3 mb-3">
                          <p className="text-[10px] text-[var(--color-text-dim)] tracking-wider">
                            {schemaSearchResults[conn.name]
                              ? `${schemaSearchResults[conn.name].result_count} / ${schemaSearchResults[conn.name].total_tables} tables`
                              : `${Object.keys(tables).length} tables`}
                          </p>
                          {(() => {
                            const displayTables = schemaSearchResults[conn.name]?.tables || tables;
                            const totalFKs = Object.values(displayTables).reduce((sum: number, t: any) => sum + (t.foreign_keys?.length || 0), 0);
                            const totalIdxs = Object.values(displayTables).reduce((sum: number, t: any) => sum + (t.indexes?.length || 0), 0);
                            return (
                              <>
                                {totalFKs > 0 && <span className="text-[9px] text-purple-400 tracking-wider">{totalFKs} FKs</span>}
                                {totalIdxs > 0 && <span className="text-[9px] text-blue-400 tracking-wider">{totalIdxs} indexes</span>}
                              </>
                            );
                          })()}
                          <div className="flex-1" />
                          {/* Endorsement mode toggle */}
                          <button
                            onClick={async () => {
                              const current = endorsements[conn.name] || { endorsed: [], hidden: [], mode: "all" as const };
                              const nextMode = current.mode === "all" ? "endorsed_only" as const : "all" as const;
                              const updated = { ...current, mode: nextMode };
                              try {
                                await setSchemaEndorsements(conn.name, updated);
                                setEndorsements(prev => ({ ...prev, [conn.name]: updated }));
                                // Re-fetch schema with new endorsements applied
                                const data = await getConnectionSchema(conn.name);
                                setSchemaData(prev => ({ ...prev, [conn.name]: data }));
                                toast(`Schema filter: ${nextMode === "endorsed_only" ? "endorsed only" : "all tables"}`, "success");
                              } catch { toast("Failed to update endorsements", "error"); }
                            }}
                            className={`px-2 py-0.5 text-[9px] border tracking-wider transition-all ${
                              endorsements[conn.name]?.mode === "endorsed_only"
                                ? "border-[var(--color-success)]/30 text-[var(--color-success)] bg-[var(--color-success)]/5"
                                : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
                            }`}
                            title="Toggle between showing all tables or only endorsed tables"
                          >
                            <Star className="w-2.5 h-2.5 inline mr-1" strokeWidth={1.5} />
                            {endorsements[conn.name]?.mode === "endorsed_only" ? "endorsed only" : "all tables"}
                          </button>
                          <button
                            onClick={async () => {
                              setSchemaLoading(conn.name);
                              try {
                                await refreshConnectionSchema(conn.name);
                                const data = await getConnectionSchema(conn.name);
                                setSchemaData(prev => ({ ...prev, [conn.name]: { tables: data.tables } }));
                                toast(`${conn.name}: schema refreshed`, "success");
                              } catch { toast(`${conn.name}: refresh failed`, "error"); }
                              finally { setSchemaLoading(null); }
                            }}
                            disabled={schemaLoading === conn.name}
                            className="flex items-center gap-1 px-1.5 py-0.5 text-[9px] border border-[var(--color-border)] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-all tracking-wider"
                            title="Re-introspect schema from database"
                          >
                            <RefreshCw className={`w-2.5 h-2.5 ${schemaLoading === conn.name ? "animate-spin" : ""}`} strokeWidth={1.5} />
                            refresh
                          </button>
                          <button
                            onClick={async () => {
                              await handleGenerateSemantic(conn.name);
                            }}
                            className="flex items-center gap-1 px-1.5 py-0.5 text-[9px] border border-[var(--color-border)] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-all tracking-wider"
                            title="Generate semantic model with auto-detected joins and business glossary"
                          >
                            <Star className="w-2.5 h-2.5" strokeWidth={1.5} />
                            semantic
                          </button>
                          <div className="relative">
                            <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
                            <input
                              type="text"
                              placeholder="search tables & columns..."
                              value={schemaSearch[conn.name] || ""}
                              onChange={(e) => handleSchemaSearch(conn.name, e.target.value)}
                              className="w-48 pl-7 pr-2 py-1 text-[10px] bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-border-hover)] focus:outline-none tracking-wider"
                            />
                            {schemaSearchLoading === conn.name && (
                              <Loader2 className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 animate-spin text-[var(--color-text-dim)]" />
                            )}
                          </div>
                        </div>
                        <div className="grid grid-cols-2 gap-px max-h-96 overflow-auto bg-[var(--color-border)]">
                          {Object.entries(schemaSearchResults[conn.name]?.tables || tables).map(([key, t]: [string, any]) => (
                            <div key={t.name} className="p-3 bg-[var(--color-bg)]">
                              <div className="flex items-center gap-2 mb-2">
                                <Table2 className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
                                <span className="text-[10px] text-[var(--color-text-muted)]">{t.schema}.{t.name}</span>
                                <span className="text-[9px] text-[var(--color-text-dim)] tabular-nums tracking-wider">{t.columns?.length || 0} cols</span>
                                {t.type === "view" && (
                                  <span className="text-[9px] text-cyan-400 tracking-wider">view</span>
                                )}
                                {t.row_count > 0 && (
                                  <span className="text-[9px] text-[var(--color-text-dim)] tabular-nums tracking-wider">
                                    ~{t.row_count >= 1000000 ? `${(t.row_count / 1000000).toFixed(1)}M` : t.row_count >= 1000 ? `${(t.row_count / 1000).toFixed(1)}K` : t.row_count} rows
                                  </span>
                                )}
                                {t._relevance_score && (
                                  <span className="text-[9px] text-[var(--color-success)] tabular-nums tracking-wider">
                                    score: {t._relevance_score}
                                  </span>
                                )}
                                <div className="flex-1" />
                                {/* Endorsement toggle per table */}
                                <button
                                  onClick={async (e) => {
                                    e.stopPropagation();
                                    const current = endorsements[conn.name] || { endorsed: [], hidden: [], mode: "all" as const };
                                    const isEndorsed = current.endorsed.includes(key);
                                    const isHidden = current.hidden.includes(key);
                                    let updated = { ...current };
                                    if (isEndorsed) {
                                      updated.endorsed = current.endorsed.filter(k => k !== key);
                                    } else if (isHidden) {
                                      updated.hidden = current.hidden.filter(k => k !== key);
                                      updated.endorsed = [...current.endorsed, key];
                                    } else {
                                      updated.endorsed = [...current.endorsed, key];
                                    }
                                    try {
                                      await setSchemaEndorsements(conn.name, updated);
                                      setEndorsements(prev => ({ ...prev, [conn.name]: updated }));
                                    } catch {}
                                  }}
                                  className={`p-0.5 transition-all ${
                                    endorsements[conn.name]?.endorsed?.includes(key)
                                      ? "text-[var(--color-success)]"
                                      : "text-[var(--color-text-dim)] opacity-30 hover:opacity-60"
                                  }`}
                                  title={endorsements[conn.name]?.endorsed?.includes(key) ? "Endorsed — click to remove" : "Click to endorse for AI agents"}
                                >
                                  <Star className="w-2.5 h-2.5" strokeWidth={1.5} />
                                </button>
                                <button
                                  onClick={async (e) => {
                                    e.stopPropagation();
                                    const current = endorsements[conn.name] || { endorsed: [], hidden: [], mode: "all" as const };
                                    const isHidden = current.hidden.includes(key);
                                    let updated = { ...current };
                                    if (isHidden) {
                                      updated.hidden = current.hidden.filter(k => k !== key);
                                    } else {
                                      updated.hidden = [...current.hidden, key];
                                      updated.endorsed = current.endorsed.filter(k => k !== key);
                                    }
                                    try {
                                      await setSchemaEndorsements(conn.name, updated);
                                      setEndorsements(prev => ({ ...prev, [conn.name]: updated }));
                                    } catch {}
                                  }}
                                  className={`p-0.5 transition-all ${
                                    endorsements[conn.name]?.hidden?.includes(key)
                                      ? "text-[var(--color-error)]"
                                      : "text-[var(--color-text-dim)] opacity-30 hover:opacity-60"
                                  }`}
                                  title={endorsements[conn.name]?.hidden?.includes(key) ? "Hidden — click to show" : "Click to hide from AI agents"}
                                >
                                  <EyeOff className="w-2.5 h-2.5" strokeWidth={1.5} />
                                </button>
                              </div>
                              {t.description && (
                                <p className="text-[8px] text-[var(--color-text-dim)] tracking-wider opacity-70 mb-1.5 italic">{t.description}</p>
                              )}
                              <div className="space-y-0.5">
                                {(t.columns || []).slice(0, 8).map((col: any) => {
                                  const isMatched = t._matched_columns?.includes(col.name);
                                  return (
                                  <div key={col.name} className="flex items-center gap-2 text-[9px] tracking-wider">
                                    <span className={col.primary_key ? "text-[var(--color-warning)]" : isMatched ? "text-[var(--color-success)]" : "text-[var(--color-text-dim)]"}>
                                      {col.name}
                                    </span>
                                    <span className="text-[var(--color-text-dim)] opacity-50">{col.type}</span>
                                    {col.primary_key && <span className="text-[var(--color-warning)]">pk</span>}
                                    {isMatched && !col.primary_key && <span className="text-[var(--color-success)] text-[8px]">match</span>}
                                    {col.comment && <span className="text-[var(--color-text-dim)] opacity-40 text-[8px] italic truncate max-w-[120px]" title={col.comment}>{col.comment}</span>}
                                  </div>
                                  );
                                })}
                                {t.columns.length > 8 && (
                                  <p className="text-[9px] text-[var(--color-text-dim)] tracking-wider">+ {t.columns.length - 8} more</p>
                                )}
                              </div>
                              {/* Foreign keys */}
                              {t.foreign_keys?.length > 0 && (
                                <div className="mt-2 pt-1.5 border-t border-[var(--color-border)]">
                                  {t.foreign_keys.map((fk: any, i: number) => (
                                    <div key={i} className="text-[8px] text-purple-400/80 tracking-wider">
                                      {fk.column} → {fk.references_table}.{fk.references_column}
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <p className="text-[10px] text-[var(--color-text-dim)] py-4 text-center tracking-wider">
                        no schema available. test the connection first.
                      </p>
                    )}
                  </div>
                )}

                {/* PII Detection Results */}
                {piiData[conn.name] && piiData[conn.name].tables_with_pii > 0 && (
                  <div className="border-t border-[var(--color-border)] px-4 py-4 animate-fade-in">
                    <div className="flex items-center gap-2 mb-3">
                      <Shield className="w-3.5 h-3.5 text-[var(--color-warning)]" strokeWidth={1.5} />
                      <span className="text-[10px] text-[var(--color-text-muted)] tracking-wider">
                        pii detected: {piiData[conn.name].tables_with_pii} table{piiData[conn.name].tables_with_pii > 1 ? "s" : ""}
                      </span>
                    </div>
                    <div className="space-y-2">
                      {Object.entries(piiData[conn.name].detections).map(([table, columns]) => (
                        <div key={table} className="p-3 border border-[var(--color-warning)]/20 bg-[var(--color-warning)]/5">
                          <p className="text-[10px] text-[var(--color-text-muted)] mb-1.5 tracking-wider">{table}</p>
                          <div className="flex flex-wrap gap-2">
                            {Object.entries(columns).map(([col, rule]) => (
                              <span key={col} className={`text-[9px] px-1.5 py-0.5 border tracking-wider uppercase ${
                                rule === "drop" ? "badge-error" :
                                rule === "hash" ? "border-purple-500/30 text-purple-400" :
                                "badge-warning"
                              }`}>
                                {col} ({rule})
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                    <p className="text-[9px] text-[var(--color-text-dim)] mt-2 tracking-wider">
                      add these rules to schema.yml annotations for automatic pii redaction.
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="delete connection"
        message={`Remove "${deleteTarget}" and all associated health data? This cannot be undone.`}
        confirmLabel="delete"
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
