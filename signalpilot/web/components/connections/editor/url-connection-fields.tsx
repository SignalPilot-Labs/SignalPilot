"use client";

import type { MutableRefObject } from "react";

import { FormInput, fieldProps } from "./form-controls";
import { DB_CONFIGS } from "~/lib/connections/connector-catalog";
import { detectDbTypeFromUrl, parseConnectionUrl } from "~/lib/connections/connection-url";
import type { ConnectionForm } from "~/lib/connections/types";

interface UrlConnectionFieldsProps {
  form: ConnectionForm;
  setForm: (form: ConnectionForm) => void;
  formErrors: Record<string, string>;
  fieldRefs: MutableRefObject<Record<string, HTMLElement | null>>;
  clearServerError: (key: string) => void;
}

export function UrlConnectionFields({
  form,
  setForm,
  formErrors,
  fieldRefs,
  clearServerError,
}: UrlConnectionFieldsProps) {
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
        onChange={(v) => {
          clearServerError("connection_string");
          const detected = detectDbTypeFromUrl(v);
          if (detected && detected !== form.db_type) {
            // Change the database type when the URL uses a recognized scheme.
            setForm({ ...form, connection_string: v, db_type: detected, port: String(DB_CONFIGS[detected].defaultPort) });
          } else {
            setForm({ ...form, connection_string: v });
          }
        }}
        type="password"
        placeholder={urlHints[form.db_type] || "paste any connection string — db type auto-detected"}
        hint={form.db_type === "clickhouse" ? "native: clickhouse://... | HTTP: clickhouse+http://..." : "paste a URL — database type is auto-detected from the scheme"}
        className="col-span-2"
        {...fieldProps("connection_string", formErrors, fieldRefs)}
      />
      {hasValidUrl && (
        <div className="col-span-2 -mt-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-[var(--color-text-dim)]">parsed components:</span>
            <button
              type="button"
              onClick={() => {
                // Switch to fields mode with parsed values pre-filled
                setForm({
                  ...form,
                  connectionMode: "fields",
                  connection_string: "",
                  ...(parsed as Partial<ConnectionForm>),
                });
              }}
              className="text-[11px] text-[var(--color-accent)] hover:text-[var(--color-text)] transition-colors"
            >
              switch to fields &rarr;
            </button>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 mt-1">
            {parsed.host && <span className="text-[11px]"><span className="text-[var(--color-text-dim)]">host:</span> <span className="text-[var(--color-text)]">{parsed.host}</span></span>}
            {parsed.port && <span className="text-[11px]"><span className="text-[var(--color-text-dim)]">port:</span> <span className="text-[var(--color-text)]">{parsed.port}</span></span>}
            {parsed.database && <span className="text-[11px]"><span className="text-[var(--color-text-dim)]">db:</span> <span className="text-[var(--color-text)]">{parsed.database}</span></span>}
            {parsed.username && <span className="text-[11px]"><span className="text-[var(--color-text-dim)]">user:</span> <span className="text-[var(--color-text)]">{parsed.username}</span></span>}
            {parsed.account && <span className="text-[11px]"><span className="text-[var(--color-text-dim)]">account:</span> <span className="text-[var(--color-text)]">{parsed.account}</span></span>}
            {parsed.warehouse && <span className="text-[11px]"><span className="text-[var(--color-text-dim)]">warehouse:</span> <span className="text-[var(--color-text)]">{parsed.warehouse}</span></span>}
            {parsed.catalog && <span className="text-[11px]"><span className="text-[var(--color-text-dim)]">catalog:</span> <span className="text-[var(--color-text)]">{parsed.catalog}</span></span>}
            {parsed.password && <span className="text-[11px] text-[var(--color-success)]">password: ****</span>}
          </div>
        </div>
      )}
    </>
  );
}
