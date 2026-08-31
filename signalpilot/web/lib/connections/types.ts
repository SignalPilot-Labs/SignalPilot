import type { DBType } from "~/lib/types";

export interface ConnectionForm {
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
  bq_auth_method: "service_account" | "oauth" | "adc";
  bq_oauth_token: string;
  bq_impersonate_sa: string; // target service account email for impersonation
  // ClickHouse
  ch_protocol: "native" | "http";
  // Databricks
  http_path: string;
  access_token: string;
  catalog: string;
  databricks_auth_method: "pat" | "oauth_m2m" | "oauth_u2m";
  dbx_oauth_client_id: string;
  dbx_oauth_client_secret: string;
  // Xata — a "connection" is org + project + branch; the gateway resolves the per-branch
  // Postgres endpoint server-side. xata_api_key is the control-plane secret (xau_...).
  branch: string;
  xata_api_key: string;
  xata_organization: string;
  xata_project: string;
  xata_database: string;
  xata_api_url: string;
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
  // HTTP proxy for SSH (HEX pattern — for VPCs that block direct SSH)
  ssh_proxy_enabled: boolean;
  ssh_proxy_host: string;
  ssh_proxy_port: string;
  // Snowflake auth method (password, key-pair, OAuth, PAT, Okta SSO, or MFA)
  snowflake_auth_method: "password" | "key_pair" | "oauth" | "pat" | "okta" | "mfa";
  sf_private_key: string;
  sf_private_key_passphrase: string;
  sf_oauth_token: string;
  sf_pat: string; // Programmatic access token (sent in password field)
  sf_passcode: string; // MFA passcode
  sf_okta_url: string; // Okta SSO URL (sent as authenticator)
  // Snowflake advanced: explicit host/protocol override (PrivateLink, China, gov, VPS)
  snowflake_host: string;
  snowflake_protocol: "https" | "http";
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
  // Trino
  trino_https: boolean;
  trino_auth_method: "none" | "password" | "jwt" | "certificate" | "kerberos";
  trino_jwt_token: string;
  trino_client_cert: string;
  trino_client_key: string;
  trino_krb_service_name: string;
  // DuckDB / MotherDuck
  duckdb_mode: "local" | "motherduck" | "memory";
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


