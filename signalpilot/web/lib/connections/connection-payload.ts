import { DB_CONFIGS } from "./connector-catalog";
import type { ConnectionForm } from "./types";

export function buildConnectionPayload(form: ConnectionForm): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    name: form.name,
    db_type: form.db_type,
    description: form.description,
  };

  const isUrlMode = form.connectionMode === "url" && form.connection_string;

  if (isUrlMode) {
    payload.connection_string = form.connection_string;
  }

  const config = DB_CONFIGS[form.db_type];

  // Common host/port fields — skip when using connection_string to avoid
  // overwriting parsed values with form defaults (e.g., "localhost:5432").
  if (!isUrlMode) {
    if (config.fields.includes("host")) payload.host = form.host;
    if (config.fields.includes("port")) payload.port = parseInt(form.port) || config.defaultPort;
    if (config.fields.includes("database")) payload.database = form.database;
    if (config.fields.includes("username")) payload.username = form.username;
    if (config.fields.includes("password")) payload.password = form.password;
  }

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
    payload.auth_method = form.bq_auth_method;
    if (form.bq_auth_method === "oauth") {
      payload.oauth_access_token = form.bq_oauth_token;
    }
    if (form.bq_impersonate_sa) {
      payload.impersonate_service_account = form.bq_impersonate_sa;
    }
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

  // Xata — org + project + branch scoped. The gateway resolves the per-branch Postgres
  // endpoint (<branchID>.<region>.xata.tech) server-side from the control-plane API key.
  if (form.db_type === "xata") {
    payload.xata_api_key = form.xata_api_key;
    payload.xata_organization = form.xata_organization.trim();
    payload.xata_project = form.xata_project.trim();
    payload.branch = form.branch.trim() || "main";
    payload.xata_database = form.xata_database.trim() || "xata";
    if (form.xata_api_url.trim()) payload.xata_api_url = form.xata_api_url.trim();
  }

  // Trino — auth method and HTTPS connection string
  if (form.db_type === "trino" && form.connectionMode !== "url") {
    if (form.trino_https) {
      const trinoPort = form.port || "443";
      const userPart = form.password
        ? `${form.username || "trino"}:${form.password}@`
        : `${form.username || "trino"}@`;
      const pathPart = form.catalog ? `/${form.catalog}${form.schema_name ? `/${form.schema_name}` : ""}` : "";
      payload.connection_string = `trino+https://${userPart}${form.host}:${trinoPort}${pathPart}`;
    }
    if (form.trino_auth_method !== "none") {
      payload.auth_method = form.trino_auth_method;
      if (form.trino_auth_method === "jwt") {
        payload.jwt_token = form.trino_jwt_token;
      } else if (form.trino_auth_method === "certificate") {
        payload.client_cert = form.trino_client_cert;
        if (form.trino_client_key) payload.client_key = form.trino_client_key;
      } else if (form.trino_auth_method === "kerberos") {
        payload.kerberos_config = { service_name: form.trino_krb_service_name || "trino" };
      }
    }
  }

  // Tags
  if (form.tags.length > 0) {
    payload.tags = form.tags;
  }

  // Snowflake auth method → maps to the gateway `authenticator` contract.
  if (form.db_type === "snowflake") {
    switch (form.snowflake_auth_method) {
      case "key_pair":
        payload.authenticator = "key_pair";
        payload.private_key = form.sf_private_key;
        if (form.sf_private_key_passphrase) payload.private_key_passphrase = form.sf_private_key_passphrase;
        delete payload.password; // key-pair does not use a password
        break;
      case "oauth":
        payload.authenticator = "oauth";
        payload.access_token = form.sf_oauth_token;
        delete payload.password; // OAuth does not use a password
        break;
      case "pat":
        // Programmatic access token is supplied in the password field.
        payload.authenticator = "pat";
        payload.password = form.sf_pat;
        break;
      case "mfa":
        payload.authenticator = "mfa";
        payload.password = form.password;
        if (form.sf_passcode) payload.passcode = form.sf_passcode;
        break;
      case "okta":
        // Okta native SSO: the Okta URL itself is the authenticator value.
        payload.authenticator = form.sf_okta_url.trim();
        payload.password = form.password;
        break;
      case "password":
      default:
        payload.authenticator = "password";
        payload.password = form.password;
        break;
    }
    // Advanced host/protocol overrides (PrivateLink, China, gov, VPS).
    if (form.snowflake_host.trim()) payload.snowflake_host = form.snowflake_host.trim();
    if (form.snowflake_protocol && form.snowflake_protocol !== "https") {
      payload.snowflake_protocol = form.snowflake_protocol;
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
    const sshPayload: Record<string, unknown> = {
      enabled: true,
      host: form.ssh_host,
      port: parseInt(form.ssh_port) || 22,
      username: form.ssh_username,
      auth_method: form.ssh_auth_method,
      password: form.ssh_auth_method === "password" ? form.ssh_password : null,
      private_key: form.ssh_auth_method === "key" ? form.ssh_private_key : null,
      private_key_passphrase: form.ssh_auth_method === "key" ? form.ssh_key_passphrase : null,
    };
    // Route the SSH tunnel through the configured HTTP proxy.
    if (form.ssh_proxy_enabled && form.ssh_proxy_host) {
      sshPayload.proxy_host = form.ssh_proxy_host;
      sshPayload.proxy_port = parseInt(form.ssh_proxy_port) || 3128;
    }
    payload.ssh_tunnel = sshPayload;
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



