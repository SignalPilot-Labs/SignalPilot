import { describe, expect, it } from "vitest";

import { buildConnectionPayload } from "./connection-payload";
import { buildConnectionPreview, detectDbTypeFromUrl, parseConnectionUrl } from "./connection-url";
import { validateConnectionForm } from "./connection-validation";
import { DEFAULT_CONNECTION_FORM } from "./defaults";
import type { ConnectionForm } from "./types";

function form(values: Partial<ConnectionForm> = {}): ConnectionForm {
  return { ...DEFAULT_CONNECTION_FORM, name: "warehouse", ...values };
}

describe("connection URL helpers", () => {
  it.each([
    ["postgresql://user:secret@db.example.com:5432/app", "postgres"],
    ["mysql+pymysql://user:secret@db.example.com/app", "mysql"],
    ["redshift://user:secret@cluster.example.com/dev", "redshift"],
    ["clickhouse+https://user:secret@cluster.example.com/default", "clickhouse"],
    ["snowflake://user:secret@org-account/db/public", "snowflake"],
    ["mssql://user:secret@sql.example.com/app", "mssql"],
    ["trino+https://user@trino.example.com/hive/default", "trino"],
    ["databricks://token@workspace.example.com/sql/path", "databricks"],
    ["bigquery://project/dataset", "bigquery"],
    ["md:analytics", "duckdb"],
  ] as const)("detects %s", (url, expected) => {
    expect(detectDbTypeFromUrl(url)).toBe(expected);
  });

  it("returns null for an unsupported URL", () => {
    expect(detectDbTypeFromUrl("oracle://db.example.com/app")).toBeNull();
  });

  it("parses relational credentials and SSL settings", () => {
    expect(
      parseConnectionUrl(
        "postgresql://my_user:my_pass@db.example.com:5440/analytics?sslmode=require",
        "postgres",
      ),
    ).toEqual({
      host: "db.example.com",
      port: "5440",
      database: "analytics",
      username: "my_user",
      password: "my_pass",
      ssl_enabled: true,
      ssl_mode: "require",
    });
  });

  it("does not expose passwords in previews", () => {
    const preview = buildConnectionPreview(
      form({ username: "my_user", password: "my_pass", database: "analytics" }),
    );
    expect(preview).toContain("my_user:****@");
    expect(preview).not.toContain("my_pass");
  });
});

describe("connection validation", () => {
  it("accepts a complete PostgreSQL form", () => {
    expect(
      validateConnectionForm(
        form({ database: "analytics", username: "my_user", password: "my_pass" }),
      ),
    ).toEqual({});
  });

  it("validates only the name and URL in URL mode", () => {
    expect(
      validateConnectionForm(
        form({ connectionMode: "url", connection_string: "postgresql://db.example.com/app" }),
      ),
    ).toEqual({});
  });

  it("requires connector-specific Snowflake fields", () => {
    const errors = validateConnectionForm(
      form({ db_type: "snowflake", account: "", username: "my_user" }),
    );
    expect(errors.account).toBeDefined();
  });

  it("requires a CA certificate for verification modes", () => {
    const errors = validateConnectionForm(
      form({
        database: "analytics",
        username: "my_user",
        ssl_enabled: true,
        ssl_mode: "verify-full",
      }),
    );
    expect(errors.ssl_ca_cert).toBeDefined();
  });
});

describe("connection payloads", () => {
  it("does not overwrite URL values with field defaults", () => {
    const payload = buildConnectionPayload(
      form({
        connectionMode: "url",
        connection_string: "postgresql://my_user:my_pass@db.example.com/analytics",
      }),
    );
    expect(payload.connection_string).toBe(
      "postgresql://my_user:my_pass@db.example.com/analytics",
    );
    expect(payload.host).toBeUndefined();
    expect(payload.port).toBeUndefined();
  });

  it("maps SSH and SSL settings to nested payloads", () => {
    const payload = buildConnectionPayload(
      form({
        database: "analytics",
        username: "my_user",
        ssl_enabled: true,
        ssl_mode: "require",
        ssh_enabled: true,
        ssh_host: "bastion.example.com",
        ssh_username: "deploy",
        ssh_password: "secret",
      }),
    );
    expect(payload.ssl_config).toMatchObject({ enabled: true, mode: "require" });
    expect(payload.ssh_tunnel).toMatchObject({
      enabled: true,
      host: "bastion.example.com",
      username: "deploy",
    });
  });

  it("maps Snowflake key-pair authentication without a password", () => {
    const payload = buildConnectionPayload(
      form({
        db_type: "snowflake",
        account: "org-account",
        username: "my_user",
        password: "unused",
        snowflake_auth_method: "key_pair",
        sf_private_key: "-----BEGIN PRIVATE KEY-----",
      }),
    );
    expect(payload.authenticator).toBe("key_pair");
    expect(payload.private_key).toBe("-----BEGIN PRIVATE KEY-----");
    expect(payload.password).toBeUndefined();
  });
});
