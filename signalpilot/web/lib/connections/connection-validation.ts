import { DB_CONFIGS } from "./connector-catalog";
import type { ConnectionForm } from "./types";

export function validateConnectionForm(form: ConnectionForm): Record<string, string> {
  const errors: Record<string, string> = {};
  const config = DB_CONFIGS[form.db_type];

  if (!form.name.trim()) errors.name = "connection name is required";
  else if (!/^[a-zA-Z0-9_-]+$/.test(form.name)) errors.name = "only letters, numbers, hyphens, underscores";

  if (form.connectionMode === "url") {
    if (!form.connection_string.trim()) errors.connection_string = "connection URL is required";
    return errors;
  }

  // DB-specific validation
  if (config.fields.includes("host") && !form.host.trim()) errors.host = "host is required";
  if (config.fields.includes("port")) {
    const port = parseInt(form.port);
    if (isNaN(port) || port < 1 || port > 65535) errors.port = "port must be 1-65535";
  }

  // §9 gap-fill: username required for connectors that use it
  if (["postgres", "mysql", "redshift", "clickhouse", "mssql", "snowflake"].includes(form.db_type) && !form.connection_string) {
    if (!form.username.trim()) errors.username = "username is required";
  }

  // §9 gap-fill: catalog required for trino
  if (form.db_type === "trino" && !form.connection_string) {
    if (!form.catalog.trim()) errors.catalog = "catalog is required";
  }

  // §9 gap-fill: database required for duckdb/sqlite (local mode)
  if ((form.db_type === "duckdb" || form.db_type === "sqlite") && !form.connection_string) {
    if (!form.database.trim()) errors.database = "database file path is required";
  }

  // Gap 1+2: database required for standard relational connectors.
  // mssql is exempt: an empty database means multi-database mode — the
  // connector discovers every accessible database on the server.
  if (["postgres", "mysql", "clickhouse", "redshift"].includes(form.db_type) && !form.connection_string) {
    if (!form.database.trim()) errors.database = "database is required";
  }

  if (form.db_type === "snowflake") {
    if (!form.account.trim()) errors.account = "account identifier is required";
    else if (!form.account.includes(".") && !form.account.includes("-")) {
      errors.account = "use full identifier: org-account or account.region";
    }
    // Gap 4: key-pair / OAuth token validation
    if (form.snowflake_auth_method === "key_pair" && !form.sf_private_key.trim()) {
      errors.sf_private_key = "private key (PEM) is required for key-pair auth";
    }
    if (form.snowflake_auth_method === "key_pair" && form.sf_private_key.trim()
        && !form.sf_private_key.trim().startsWith("-----BEGIN")) {
      errors.sf_private_key = "must be a PEM-format private key (-----BEGIN ... PRIVATE KEY-----)";
    }
    if (form.snowflake_auth_method === "oauth" && !form.sf_oauth_token.trim()) {
      errors.sf_oauth_token = "OAuth access token is required";
    }
    if (form.snowflake_auth_method === "pat" && !form.sf_pat.trim()) {
      errors.sf_pat = "programmatic access token is required";
    }
    if (form.snowflake_auth_method === "mfa" && !form.password.trim()) {
      errors.password = "password is required for MFA auth";
    }
    if (form.snowflake_auth_method === "okta") {
      if (!form.sf_okta_url.trim()) {
        errors.sf_okta_url = "Okta URL is required";
      } else if (!/^https:\/\/.+\.okta\.com/.test(form.sf_okta_url.trim())) {
        errors.sf_okta_url = "must be an Okta URL (e.g., https://your-org.okta.com)";
      }
      if (!form.password.trim()) errors.password = "password is required for Okta SSO";
    }
    if (form.snowflake_protocol === "http" && !form.snowflake_host.trim()) {
      errors.snowflake_host = "host override is required when protocol is http";
    }
  }

  if (form.db_type === "xata") {
    if (!form.xata_api_key.trim()) errors.xata_api_key = "API key is required";
    if (!form.xata_organization.trim()) errors.xata_organization = "organization id is required";
    if (!form.xata_project.trim()) errors.xata_project = "project id is required";
  }

  if (form.db_type === "bigquery") {
    if (!form.project.trim()) errors.project = "GCP project ID is required";
    if (form.bq_auth_method === "service_account" && !form.credentials_json.trim()) {
      errors.credentials_json = "service account JSON is required";
    } else if (form.bq_auth_method === "service_account" && form.credentials_json.trim()) {
      try { JSON.parse(form.credentials_json); } catch { errors.credentials_json = "invalid JSON format"; }
    }
    // Gap 5: bq_oauth_token required when OAuth method selected
    if (form.bq_auth_method === "oauth" && !form.bq_oauth_token.trim()) {
      errors.bq_oauth_token = "OAuth access token is required";
    }
  }

  // Gap 3: Azure AD required fields
  if (form.db_type === "mssql" && form.azure_ad_auth) {
    if (!form.azure_tenant_id.trim()) errors.azure_tenant_id = "tenant ID is required for Azure AD auth";
    if (!form.azure_client_id.trim()) errors.azure_client_id = "client ID is required for Azure AD auth";
    if (!form.azure_client_secret.trim()) errors.azure_client_secret = "client secret is required for Azure AD auth";
  }

  if (form.db_type === "databricks") {
    if (!form.http_path.trim()) errors.http_path = "HTTP path is required (e.g., /sql/1.0/warehouses/abc123)";
    if (form.databricks_auth_method === "pat" && !form.access_token.trim()) errors.access_token = "personal access token is required";
    if (form.databricks_auth_method === "oauth_m2m") {
      if (!form.dbx_oauth_client_id?.trim()) errors.dbx_oauth_client_id = "OAuth client ID is required for M2M auth";
      if (!form.dbx_oauth_client_secret?.trim()) errors.dbx_oauth_client_secret = "OAuth client secret is required for M2M auth";
    }
  }

  if (form.ssh_enabled) {
    if (!form.ssh_host.trim()) errors.ssh_host = "SSH host is required";
    if (!form.ssh_username.trim()) errors.ssh_username = "SSH username is required";
    if (form.ssh_auth_method === "password" && !form.ssh_password.trim()) errors.ssh_password = "SSH password is required";
    if (form.ssh_auth_method === "key") {
      if (!form.ssh_private_key.trim()) {
        errors.ssh_private_key = "SSH private key is required";
      } else if (!form.ssh_private_key.trim().startsWith("-----BEGIN")) {
        errors.ssh_private_key = "must be a PEM-format private key (-----BEGIN ... PRIVATE KEY-----)";
      }
    }
    const sshPort = parseInt(form.ssh_port || "22");
    if (isNaN(sshPort) || sshPort < 1 || sshPort > 65535) errors.ssh_port = "SSH port must be 1-65535";
  }

  // Gap 7: SSL CA cert required for verify modes
  if (form.ssl_enabled && form.ssl_mode.startsWith("verify") && !form.ssl_ca_cert.trim()) {
    errors.ssl_ca_cert = "CA certificate is required for verify-ca / verify-full mode";
  }

  // Timeout validation (if provided, must be positive integers)
  if (form.connection_timeout) {
    const ct = parseInt(form.connection_timeout);
    if (isNaN(ct) || ct < 1 || ct > 300) errors.connection_timeout = "connection timeout must be 1-300 seconds";
  }
  if (form.query_timeout) {
    const qt = parseInt(form.query_timeout);
    if (isNaN(qt) || qt < 1 || qt > 3600) errors.query_timeout = "query timeout must be 1-3600 seconds";
  }

  return errors;
}


