import type { DBType } from "~/lib/types";
import { DB_CONFIGS } from "./connector-catalog";
import type { ConnectionForm } from "./types";

export function buildConnectionPreview(form: ConnectionForm): string {
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
    case "snowflake": {
      const sfHost = form.snowflake_host.trim() || form.account || "account";
      const sfParams: string[] = [];
      if (form.warehouse) sfParams.push(`warehouse=${form.warehouse}`);
      if (form.role) sfParams.push(`role=${form.role}`);
      // Reflect the chosen auth method; secrets stay masked.
      const sfAuthLabel: Record<ConnectionForm["snowflake_auth_method"], string> = {
        password: "password", key_pair: "key_pair", oauth: "oauth",
        pat: "pat", okta: "okta", mfa: "mfa",
      };
      sfParams.push(`authenticator=${sfAuthLabel[form.snowflake_auth_method]}`);
      const sfQuery = sfParams.length ? `?${sfParams.join("&")}` : "";
      return `snowflake://${form.username || "user"}:****@${sfHost}/${form.database || "db"}/${form.schema_name || "schema"}${sfQuery}`;
    }
    case "bigquery":
      return `bigquery://${form.project || "project"}/${form.dataset || "dataset"}`;
    case "databricks":
      return `databricks://****@${form.host || "host"}/${form.http_path || "sql/..."}${form.catalog ? `?catalog=${form.catalog}` : ""}`;
    case "mssql":
      return `mssql://${form.username || "sa"}:****@${form.host || "host"}:${form.port || "1433"}/${form.database || ""}`;
    case "trino": {
      const trinoScheme = form.trino_https ? "trino+https" : "trino";
      const trinoPort = form.port || (form.trino_https ? "443" : "8080");
      return `${trinoScheme}://${form.username || "trino"}${form.password ? ":****" : ""}@${form.host || "host"}:${trinoPort}/${form.catalog || "catalog"}${form.schema_name ? `/${form.schema_name}` : ""}`;
    }
    case "xata":
      return `xata://${form.xata_organization || "organization"}/${form.xata_project || "project"}/${form.branch || "main"}`;
    case "duckdb":
    case "sqlite":
      return form.database || ":memory:";
    default:
      return "";
  }
}

/** Return the database type that matches the URL scheme. */
export function detectDbTypeFromUrl(url: string): DBType | null {
  const lower = url.trim().toLowerCase();
  if (lower.startsWith("postgresql://") || lower.startsWith("postgres://")) return "postgres";
  if (lower.startsWith("mysql://") || lower.startsWith("mysql+pymysql://") || lower.startsWith("mariadb://")) return "mysql";
  if (lower.startsWith("redshift://")) return "redshift";
  if (lower.startsWith("clickhouse://") || lower.startsWith("clickhouses://") || lower.startsWith("clickhouse+http://") || lower.startsWith("clickhouse+https://")) return "clickhouse";
  if (lower.startsWith("snowflake://")) return "snowflake";
  if (lower.startsWith("mssql://") || lower.startsWith("mssql+pymssql://") || lower.startsWith("sqlserver://")) return "mssql";
  if (lower.startsWith("trino://") || lower.startsWith("trino+https://")) return "trino";
  if (lower.startsWith("databricks://")) return "databricks";
  if (lower.startsWith("bigquery://")) return "bigquery";
  if (lower.startsWith("md:")) return "duckdb";
  return null;
}

/** Convert supported URL values to form fields. */
export function parseConnectionUrl(url: string, dbType: DBType): Partial<ConnectionForm> {
  try {
    if (dbType === "postgres" || dbType === "mysql" || dbType === "redshift" || dbType === "clickhouse" || dbType === "mssql") {
      const parsed = new URL(url.replace(/^(postgresql|redshift|clickhouse|mysql\+pymysql|mssql|mssql\+pymssql|sqlserver):/, "http:"));
      const result: Partial<ConnectionForm> = {
        host: parsed.hostname || "",
        port: parsed.port || String(DB_CONFIGS[dbType].defaultPort),
        database: parsed.pathname.replace(/^\//, "") || "",
        username: decodeURIComponent(parsed.username || ""),
        password: decodeURIComponent(parsed.password || ""),
      };
      // Extract SSL mode from query params (e.g., ?sslmode=require)
      const sslmode = parsed.searchParams.get("sslmode");
      if (sslmode && sslmode !== "disable") {
        result.ssl_enabled = true;
        result.ssl_mode = sslmode as ConnectionForm["ssl_mode"];
      }
      return result;
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
  } catch {
    // Keep the current form values when the URL is invalid.
  }
  return {};
}


