import type { DBType } from "~/lib/types";
import type { ConnectionForm } from "./types";

export interface DBTypeConfig {
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

export const DB_CONFIGS: Record<DBType, DBTypeConfig> = {
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
  xata: {
    label: "Xata",
    shortLabel: "xata",
    defaultPort: 5432,
    category: "warehouse",
    supportsSSH: false,
    supportsSSL: false,
    connectionModes: ["fields"],
    fields: ["branch"],
    description: "Postgres at scale with instant branches",
  },
};

export const DB_TYPE_ORDER: DBType[] = [
  "postgres", "mysql", "mssql", "redshift", "snowflake", "bigquery",
  "clickhouse", "databricks", "trino", "xata", "duckdb", "sqlite",
];

export const CONNECTOR_TIERS: Record<DBType, { tier: number; label: string; color: string }> = {
  postgres:   { tier: 1, label: "T1", color: "text-emerald-400 border-emerald-500/30" },
  mysql:      { tier: 1, label: "T1", color: "text-emerald-400 border-emerald-500/30" },
  snowflake:  { tier: 1, label: "T1", color: "text-emerald-400 border-emerald-500/30" },
  bigquery:   { tier: 1, label: "T1", color: "text-emerald-400 border-emerald-500/30" },
  xata:       { tier: 1, label: "T1", color: "text-emerald-400 border-emerald-500/30" },
  mssql:      { tier: 2, label: "T2", color: "text-sky-400 border-sky-500/30" },
  redshift:   { tier: 2, label: "T2", color: "text-sky-400 border-sky-500/30" },
  clickhouse: { tier: 2, label: "T2", color: "text-sky-400 border-sky-500/30" },
  databricks: { tier: 2, label: "T2", color: "text-sky-400 border-sky-500/30" },
  trino:      { tier: 2, label: "T2", color: "text-sky-400 border-sky-500/30" },
  duckdb:     { tier: 3, label: "T3", color: "text-zinc-400 border-zinc-500/30" },
  sqlite:     { tier: 3, label: "T3", color: "text-zinc-400 border-zinc-500/30" },
};

export const CATEGORY_LABELS: Record<string, string> = {
  relational: "relational databases",
  warehouse: "data warehouses",
  columnar: "columnar databases",
  embedded: "embedded databases",
};

// Each variant supplies defaults for one hosting environment.
export interface ConnectionVariant {
  key: string;
  label: string;
  hint: string;
  defaults: Partial<ConnectionForm>;
}

export const DEFAULT_VARIANT: ConnectionVariant = {
  key: "default",
  label: "Default",
  hint: "standard self-managed instance",
  defaults: {},
};

export const DB_VARIANTS: Record<DBType, ConnectionVariant[]> = {
  postgres: [
    { key: "default", label: "Default", hint: "self-managed or docker PostgreSQL", defaults: {} },
    { key: "aws-rds", label: "AWS RDS / Aurora", hint: "SSL required by default on RDS", defaults: { ssl_enabled: true, ssl_mode: "require", description: "AWS RDS PostgreSQL instance" } },
    { key: "gcp-cloudsql", label: "GCP Cloud SQL", hint: "verifies the Cloud SQL server certificate", defaults: { ssl_enabled: true, ssl_mode: "verify-ca", description: "GCP Cloud SQL for PostgreSQL" } },
    { key: "supabase", label: "Supabase", hint: "Project Settings → Database → Connection string (pooler port 6543 for serverless)", defaults: { ssl_enabled: true, ssl_mode: "require", description: "Supabase Postgres" } },
    { key: "ssh", label: "Behind SSH bastion", hint: "tunnels through a jump host — fill SSH settings under Advanced", defaults: { ssh_enabled: true, ssh_port: "22", description: "Database behind SSH bastion" } },
  ],
  mysql: [
    { key: "default", label: "Default", hint: "self-managed or docker MySQL", defaults: {} },
    { key: "aws-rds", label: "AWS RDS / Aurora", hint: "SSL required by default on RDS", defaults: { ssl_enabled: true, ssl_mode: "require", description: "AWS RDS MySQL instance" } },
  ],
  mssql: [
    { key: "default", label: "Single database", hint: "connects to one named database on the server", defaults: {} },
    { key: "multi-db", label: "All databases", hint: "leave database empty — discovers every accessible database on the server as database.schema.table", defaults: { database: "", description: "SQL Server — all databases in one connection" } },
    { key: "aws-rds", label: "AWS RDS SQL Server", hint: "all databases in one connection, SSL on — RDS system databases are filtered out automatically", defaults: { ssl_enabled: true, database: "", description: "AWS RDS SQL Server — all databases in one connection" } },
    { key: "azure-sql", label: "Azure SQL", hint: "Entra ID (Azure AD) service-principal auth — host is <server>.database.windows.net", defaults: { ssl_enabled: true, azure_ad_auth: true, description: "Azure SQL with Entra ID auth" } },
  ],
  redshift: [
    { key: "default", label: "Provisioned cluster", hint: "classic Redshift cluster with database credentials", defaults: { ssl_enabled: true, ssl_mode: "require", description: "Amazon Redshift cluster" } },
    { key: "serverless", label: "Serverless (IAM)", hint: "Redshift Serverless workgroup with IAM auth", defaults: { ssl_enabled: true, ssl_mode: "require", iam_auth: true, description: "Redshift Serverless with IAM auth" } },
  ],
  snowflake: [
    { key: "default", label: "Password", hint: "username + password auth", defaults: {} },
    { key: "key-pair", label: "Key pair", hint: "RSA key-pair auth for service accounts", defaults: { snowflake_auth_method: "key_pair", description: "Snowflake with RSA key-pair auth" } },
  ],
  bigquery: [
    { key: "default", label: "Service account", hint: "paste the service-account JSON key", defaults: { bq_auth_method: "service_account", description: "Google BigQuery with service account" } },
  ],
  clickhouse: [
    { key: "default", label: "Self-hosted", hint: "native protocol on port 9000", defaults: {} },
    { key: "cloud", label: "ClickHouse Cloud", hint: "HTTPS on port 8443", defaults: { ch_protocol: "http", ssl_enabled: true, port: "8443", description: "ClickHouse Cloud (HTTPS)" } },
  ],
  databricks: [
    { key: "default", label: "Access token", hint: "personal access token auth", defaults: {} },
    { key: "oauth", label: "OAuth M2M", hint: "OAuth machine-to-machine service principal", defaults: { databricks_auth_method: "oauth_m2m", description: "Databricks with OAuth M2M service principal" } },
  ],
  trino: [
    { key: "default", label: "Self-hosted", hint: "plain HTTP on port 8080", defaults: {} },
    { key: "starburst", label: "Starburst Galaxy", hint: "HTTPS on port 443 with password auth", defaults: { trino_https: true, port: "443", trino_auth_method: "password", description: "Starburst Galaxy / Trino HTTPS" } },
  ],
  duckdb: [
    { key: "default", label: "Local file", hint: "path to a .duckdb file on the gateway host", defaults: {} },
    { key: "motherduck", label: "MotherDuck", hint: "cloud-hosted DuckDB (md: database)", defaults: { database: "md:", duckdb_mode: "motherduck", description: "MotherDuck cloud DuckDB" } },
  ],
  sqlite: [
    { key: "default", label: "Local file", hint: "path to a .sqlite file on the gateway host", defaults: {} },
  ],
  xata: [
    { key: "default", label: "Default", hint: "Xata Postgres project with instant branches", defaults: { branch: "main", xata_database: "xata", xata_api_url: "https://api.xata.tech", description: "Xata Postgres project" } },
  ],
};

export const DB_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(DB_CONFIGS).map(([k, v]) => [k, v.shortLabel])
);


