import type { ConnectionInfo, DBType } from "~/lib/types";

import { DB_CONFIGS } from "./connector-catalog";
import { DEFAULT_CONNECTION_FORM } from "./defaults";
import type { ConnectionForm } from "./types";

function snowflakeAuthMethod(
  authenticator: string | null,
): ConnectionForm["snowflake_auth_method"] {
  const value = (authenticator ?? "").toLowerCase();
  if (value.includes("okta.com")) return "okta";
  if (value === "key_pair" || value === "snowflake_jwt") return "key_pair";
  if (value === "oauth") return "oauth";
  if (value === "pat") return "pat";
  if (value === "mfa" || value === "username_password_mfa") return "mfa";
  return "password";
}

export function connectionToForm(connection: ConnectionInfo): ConnectionForm {
  const config = DB_CONFIGS[connection.db_type] ?? DB_CONFIGS.postgres;
  const authenticator = connection.authenticator ?? "";

  return {
    ...DEFAULT_CONNECTION_FORM,
    name: connection.name,
    db_type: connection.db_type as DBType,
    connectionMode: config.connectionModes[0],
    host: connection.host ?? "",
    port: String(connection.port || config.defaultPort || ""),
    database: connection.database ?? "",
    username: connection.username ?? "",
    password: "",
    description: connection.description ?? "",
    account: connection.account ?? "",
    warehouse: connection.warehouse ?? "",
    schema_name: connection.schema_name ?? "",
    role: connection.role ?? "",
    snowflake_auth_method: snowflakeAuthMethod(authenticator),
    sf_okta_url: authenticator.includes("okta.com") ? authenticator : "",
    snowflake_host: connection.snowflake_host ?? "",
    snowflake_protocol: connection.snowflake_protocol === "http" ? "http" : "https",
    project: connection.project ?? "",
    dataset: connection.dataset ?? "",
    bq_location: connection.location ?? "",
    bq_max_bytes_billed: connection.maximum_bytes_billed
      ? String(connection.maximum_bytes_billed)
      : "",
    http_path: connection.http_path ?? "",
    catalog: connection.catalog ?? "",
    branch: connection.branch ?? (connection.db_type === "xata" ? "main" : ""),
    xata_api_key: "",
    xata_organization: connection.xata_organization ?? "",
    xata_project: connection.xata_project ?? "",
    xata_database:
      connection.xata_database ?? (connection.db_type === "xata" ? "xata" : ""),
    xata_api_url:
      connection.xata_api_url ??
      (connection.db_type === "xata" ? "https://api.xata.tech" : ""),
    ssl_enabled: connection.ssl,
    ssl_mode: connection.ssl_config?.mode ?? "require",
    ssl_ca_cert: connection.ssl_config?.ca_cert ?? "",
    ssl_client_cert: connection.ssl_config?.client_cert ?? "",
    ssl_client_key: connection.ssl_config?.client_key ?? "",
    ssh_enabled: connection.ssh_tunnel?.enabled ?? false,
    ssh_host: connection.ssh_tunnel?.host ?? "",
    ssh_port: String(connection.ssh_tunnel?.port || 22),
    ssh_username: connection.ssh_tunnel?.username ?? "",
    ssh_auth_method: connection.ssh_tunnel?.auth_method ?? "password",
    ssh_proxy_enabled: Boolean(connection.ssh_tunnel?.proxy_host),
    ssh_proxy_host: connection.ssh_tunnel?.proxy_host ?? "",
    ssh_proxy_port: String(connection.ssh_tunnel?.proxy_port || 3128),
    tags: connection.tags ?? [],
    schema_refresh_enabled: Boolean(connection.schema_refresh_interval),
    schema_refresh_interval: String(connection.schema_refresh_interval || 300),
    scope: connection.scope ?? "workspace",
    read_only: connection.read_only !== false,
    schema_filter_include: (connection.schema_filter_include ?? []).join(", "),
    schema_filter_exclude: (connection.schema_filter_exclude ?? []).join(", "),
    connection_timeout: String(connection.connection_timeout || 15),
    query_timeout: String(connection.query_timeout || 120),
    keepalive_interval: String(connection.keepalive_interval || 0),
    pool_min_size: String(connection.pool_min_size || 1),
    pool_max_size: String(connection.pool_max_size || 5),
    iam_auth: connection.auth_method === "iam",
    aws_region: connection.aws_region ?? "us-east-1",
    aws_access_key_id: "",
    aws_secret_access_key: "",
    redshift_cluster_id: connection.cluster_id ?? "",
    redshift_workgroup: connection.workgroup ?? "",
    azure_ad_auth: connection.auth_method === "azure_ad",
    azure_tenant_id: connection.azure_tenant_id ?? "",
    azure_client_id: connection.azure_client_id ?? "",
    azure_client_secret: "",
  };
}

export function connectionUsesAdvancedSettings(connection: ConnectionInfo): boolean {
  const hasCustomTimeout =
    (connection.connection_timeout != null && connection.connection_timeout !== 15) ||
    (connection.query_timeout != null && connection.query_timeout !== 120) ||
    (connection.keepalive_interval != null && connection.keepalive_interval > 0);

  return Boolean(
    connection.ssl ||
      connection.ssh_tunnel?.enabled ||
      connection.schema_refresh_interval ||
      connection.schema_filter_include?.length ||
      connection.schema_filter_exclude?.length ||
      hasCustomTimeout,
  );
}
