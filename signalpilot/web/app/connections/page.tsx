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
} from "lucide-react";
import {
  getConnections,
  createConnection,
  updateConnection,
  deleteConnection,
  testConnection,
  getConnectionSchema,
  searchConnectionSchema,
  getConnectionsHealth,
  detectPII,
  refreshConnectionSchema,
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
    fields: ["host", "port", "database", "username", "password"],
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
  "postgres", "mysql", "redshift", "snowflake", "bigquery",
  "clickhouse", "databricks", "duckdb", "sqlite",
];

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
  // Databricks
  http_path: string;
  access_token: string;
  catalog: string;
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
}

const defaultForm: FormState = {
  name: "", db_type: "postgres", connectionMode: "fields",
  connection_string: "", host: "localhost", port: "5432",
  database: "", username: "", password: "", description: "",
  account: "", warehouse: "", schema_name: "", role: "",
  project: "", dataset: "", credentials_json: "",
  http_path: "", access_token: "", catalog: "",
  ssl_enabled: false, ssl_mode: "require", ssl_ca_cert: "", ssl_client_cert: "", ssl_client_key: "",
  ssh_enabled: false, ssh_host: "", ssh_port: "22", ssh_username: "", ssh_auth_method: "password",
  ssh_password: "", ssh_private_key: "", ssh_key_passphrase: "",
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
    case "clickhouse":
      return `clickhouse://${form.username || "default"}:****@${form.host || "host"}:${form.port || "9000"}/${form.database || "default"}`;
    case "snowflake":
      return `snowflake://${form.username || "user"}:****@${form.account || "account"}/${form.database || "db"}/${form.schema_name || "schema"}${form.warehouse ? `?warehouse=${form.warehouse}` : ""}`;
    case "bigquery":
      return `bigquery://${form.project || "project"}/${form.dataset || "dataset"}`;
    case "databricks":
      return `databricks://${form.host || "host"}${form.http_path || "/sql/..."}`;
    case "duckdb":
    case "sqlite":
      return form.database || ":memory:";
    default:
      return "";
  }
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

  // Databricks
  if (config.fields.includes("http_path")) payload.http_path = form.http_path;
  if (config.fields.includes("access_token")) payload.access_token = form.access_token;
  if (config.fields.includes("catalog")) payload.catalog = form.catalog;

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
      clickhouse: "clickhouse://user:pass@host:9000/default",
      snowflake: "snowflake://user:pass@account/db/schema?warehouse=WH&role=ROLE",
    };
    return (
      <FormInput
        label="connection string"
        value={form.connection_string}
        onChange={(v) => setForm({ ...form, connection_string: v })}
        type="password"
        placeholder={urlHints[form.db_type] || "connection string"}
        hint={form.db_type === "clickhouse" ? "native: clickhouse://... | HTTP: clickhouse+http://..." : "full connection URL including credentials"}
        className="col-span-2"
      />
    );
  }

  // Snowflake fields
  if (form.db_type === "snowflake") {
    return (
      <>
        <FormInput label="account identifier" value={form.account} onChange={(v) => setForm({ ...form, account: v })} placeholder="org-account" hint="e.g., xy12345.us-east-1" required />
        <FormInput label="username" value={form.username} onChange={(v) => setForm({ ...form, username: v })} placeholder="ANALYTICS_USER" required />
        <FormInput label="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} type="password" required />
        <FormInput label="warehouse" value={form.warehouse} onChange={(v) => setForm({ ...form, warehouse: v })} placeholder="COMPUTE_WH" hint="optional — default warehouse" />
        <FormInput label="database" value={form.database} onChange={(v) => setForm({ ...form, database: v })} placeholder="PROD_DB" hint="optional — default database" />
        <FormInput label="schema" value={form.schema_name} onChange={(v) => setForm({ ...form, schema_name: v })} placeholder="PUBLIC" hint="optional — default schema" />
        <FormInput label="role" value={form.role} onChange={(v) => setForm({ ...form, role: v })} placeholder="ANALYST_ROLE" hint="optional — Snowflake role" />
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
      </>
    );
  }

  // Databricks fields
  if (form.db_type === "databricks") {
    return (
      <>
        <FormInput label="server hostname" value={form.host} onChange={(v) => setForm({ ...form, host: v })} placeholder="adb-1234567890123456.7.azuredatabricks.net" required />
        <FormInput label="http path" value={form.http_path} onChange={(v) => setForm({ ...form, http_path: v })} placeholder="/sql/1.0/warehouses/abc123" hint="SQL warehouse or cluster HTTP path" required />
        <FormInput label="access token" value={form.access_token} onChange={(v) => setForm({ ...form, access_token: v })} type="password" hint="personal access token (PAT)" required />
        <FormInput label="catalog" value={form.catalog} onChange={(v) => setForm({ ...form, catalog: v })} placeholder="main" hint="optional — Unity Catalog name" />
        <FormInput label="schema" value={form.schema_name} onChange={(v) => setForm({ ...form, schema_name: v })} placeholder="default" hint="optional — default schema" />
      </>
    );
  }

  // DuckDB/SQLite — just path
  if (form.db_type === "duckdb" || form.db_type === "sqlite") {
    return (
      <FormInput
        label="database path"
        value={form.database}
        onChange={(v) => setForm({ ...form, database: v })}
        placeholder={form.db_type === "duckdb" ? ":memory: or /path/to/db.duckdb" : ":memory: or /path/to/db.sqlite"}
        hint={form.db_type === "duckdb" ? "file path, :memory:, or md: for MotherDuck" : "file path or :memory:"}
        className="col-span-2"
      />
    );
  }

  // Standard host/port (Postgres, MySQL, Redshift, ClickHouse)
  return (
    <>
      <FormInput label="host" value={form.host} onChange={(v) => setForm({ ...form, host: v })} placeholder="localhost" required />
      <FormInput label="port" value={form.port} onChange={(v) => setForm({ ...form, port: v })} placeholder={String(config.defaultPort)} />
      <FormInput label="database" value={form.database} onChange={(v) => setForm({ ...form, database: v })} placeholder={form.db_type === "clickhouse" ? "default" : "mydb"} required />
      <FormInput label="username" value={form.username} onChange={(v) => setForm({ ...form, username: v })} placeholder={form.db_type === "clickhouse" ? "default" : "postgres"} required />
      <FormInput label="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} type="password" />
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
  const [form, setForm] = useState<FormState>({ ...defaultForm });
  const [showAdvanced, setShowAdvanced] = useState(false);

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
    });
    setEditingConnection(conn.name);
    setShowForm(true);
    setShowAdvanced(!!(conn.ssl || conn.ssh_tunnel?.enabled));
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

  async function handleDelete(name: string) { setDeleteTarget(name); }

  async function confirmDelete() {
    if (!deleteTarget) return;
    await deleteConnection(deleteTarget);
    refresh();
    toast(`${deleteTarget} deleted`, "info");
    setDeleteTarget(null);
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

  const config = DB_CONFIGS[form.db_type];

  return (
    <div className="p-8 animate-fade-in">
      <PageHeader
        title="connections"
        subtitle="databases"
        description="manage database connections for governed ai access"
        actions={
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90"
          >
            <Plus className="w-3.5 h-3.5" /> add connection
          </button>
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

            {/* Connection mode toggle (fields vs URL) */}
            {config.connectionModes.length > 1 && (
              <div className="flex items-center gap-3 mb-4">
                <span className="text-[10px] text-[var(--color-text-dim)] tracking-wider">connect via:</span>
                {config.connectionModes.map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setForm({ ...form, connectionMode: mode })}
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

            {/* Connection string preview */}
            {form.connectionMode !== "url" && (
              <div className="mb-4 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed">
                <div className="flex items-center gap-2">
                  <Link2 className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
                  <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">connection preview</span>
                </div>
                <code className="text-[10px] text-[var(--color-text-muted)] tracking-wide break-all">{buildConnectionPreview(form)}</code>
              </div>
            )}

            {/* Advanced: SSL + SSH */}
            {(config.supportsSSL || config.supportsSSH) && (
              <div>
                <button
                  type="button"
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  className="flex items-center gap-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider mb-2"
                >
                  {showAdvanced ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                  advanced options
                  {(form.ssl_enabled || form.ssh_enabled) && (
                    <span className="text-[var(--color-success)] text-[9px] ml-1">
                      {[form.ssl_enabled && "ssl", form.ssh_enabled && "ssh"].filter(Boolean).join(" + ")}
                    </span>
                  )}
                </button>
                {showAdvanced && (
                  <div className="animate-fade-in">
                    <SSLSection form={form} setForm={setForm} />
                    <SSHSection form={form} setForm={setForm} />
                  </div>
                )}
              </div>
            )}

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
          {connections.map((conn) => {
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
                      {conn.ssl && (
                        <span className="text-[9px] px-1 py-0.5 border border-[var(--color-success)]/30 text-[var(--color-success)] tracking-wider">ssl</span>
                      )}
                      {conn.ssh_tunnel?.enabled && (
                        <span className="text-[9px] px-1 py-0.5 border border-purple-500/30 text-purple-400 tracking-wider">ssh</span>
                      )}
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

                  {/* Test result */}
                  {testResult[conn.name] && (
                    <span className={`flex items-center gap-1 text-[10px] tracking-wider ${testResult[conn.name].status === "healthy" ? "text-[var(--color-success)]" : "text-[var(--color-error)]"}`}>
                      {testResult[conn.name].status === "healthy" ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                      {testResult[conn.name].phases ? (
                        <span className="flex items-center gap-1">
                          {testResult[conn.name].phases!.map((p, i) => (
                            <span key={i} className={`${p.status === "ok" ? "text-[var(--color-success)]" : "text-[var(--color-error)]"}`}>
                              {p.phase === "ssh_tunnel" ? "SSH" : "DB"}{p.status === "ok" ? "\u2713" : "\u2717"}
                              {p.duration_ms ? ` ${p.duration_ms}ms` : ""}
                            </span>
                          ))}
                          {testResult[conn.name].total_duration_ms ? ` (${testResult[conn.name].total_duration_ms}ms)` : ""}
                        </span>
                      ) : testResult[conn.name].message.slice(0, 40)}
                    </span>
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
                    <button onClick={(e) => { e.stopPropagation(); handleEditConnection(conn); }}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-all tracking-wider">
                      <Pencil className="w-3 h-3" strokeWidth={1.5} /> edit
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
                              </div>
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
