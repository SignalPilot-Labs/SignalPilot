"use client";

import { X } from "lucide-react";

import { ReadOnlyNote } from "~/components/access/read-only-note";
import { DbTypeIcon } from "~/components/connections/db-type-icon";
import { DB_CONFIGS } from "~/lib/connections/connector-catalog";
import type { ConnectionForm } from "~/lib/connections/types";

/** What a member sees in place of any credential or token. */
export const REDACTED_VALUE = "••••••••";

interface DetailRow {
  label: string;
  value: string;
  mono?: boolean;
}

/** Mask the password segment of a connection URL: `user:secret@host` -> `user:****@host`. */
function redactUrl(url: string): string {
  return url.replace(/^([a-z0-9+]+:\/\/[^:/@]*):[^@]*@/i, "$1:****@");
}

function push(rows: DetailRow[], label: string, value: string | null | undefined, mono = true) {
  if (value == null || value === "") return;
  rows.push({ label, value, mono });
}

/** The saved connection's fields as plain values. Credentials are never listed. */
export function connectionDetailRows(form: ConnectionForm): DetailRow[] {
  const config = DB_CONFIGS[form.db_type] ?? DB_CONFIGS.postgres;
  const rows: DetailRow[] = [];
  push(rows, "database type", config.label, false);
  push(rows, "description", form.description, false);

  if (form.connectionMode === "url" && form.connection_string) {
    push(rows, "connection string", redactUrl(form.connection_string));
  } else {
    push(rows, "host", form.host);
    push(rows, "port", form.port);
    push(rows, "database", form.database);
    push(rows, "username", form.username);
  }

  // Warehouse-specific identity fields.
  push(rows, "account", form.account);
  push(rows, "warehouse", form.warehouse);
  push(rows, "schema", form.schema_name);
  push(rows, "role", form.role);
  push(rows, "gcp project", form.project);
  push(rows, "dataset", form.dataset);
  push(rows, "http path", form.http_path);
  push(rows, "catalog", form.catalog);
  push(rows, "xata organization", form.xata_organization);
  push(rows, "xata project", form.xata_project);
  push(rows, "xata database", form.xata_database);
  push(rows, "branch", form.branch);

  push(rows, "credentials", REDACTED_VALUE);

  push(rows, "ssl", form.ssl_enabled ? `on (${form.ssl_mode || "require"})` : "off", false);
  if (config.supportsSSH) {
    push(
      rows,
      "ssh tunnel",
      form.ssh_enabled ? `${form.ssh_username || "?"}@${form.ssh_host || "?"}:${form.ssh_port || "22"}` : "off",
      form.ssh_enabled,
    );
  }
  push(rows, "access", `${form.read_only ? "read-only" : "read-write"} · ${form.scope} scope`, false);
  push(rows, "timeouts", `${form.connection_timeout}s connect · ${form.query_timeout}s query`, false);
  push(rows, "include schemas", form.schema_filter_include.trim());
  push(rows, "exclude schemas", form.schema_filter_exclude.trim());
  push(rows, "schema refresh", form.schema_refresh_enabled ? `every ${form.schema_refresh_interval}s` : "manual", false);
  if (form.tags.length > 0) push(rows, "tags", form.tags.join(", "), false);
  return rows;
}

interface ConnectionReadOnlyViewProps {
  /** The saved connection's name. */
  name: string;
  form: ConnectionForm;
  onClose: () => void;
}

/**
 * The member's view of a connection: the fields the editor would offer, as
 * values. No inputs, no save, no test-before-save. Credentials stay redacted
 * because the gateway never returns them.
 */
export function ConnectionReadOnlyView({ name, form, onClose }: ConnectionReadOnlyViewProps) {
  const config = DB_CONFIGS[form.db_type] ?? DB_CONFIGS.postgres;
  const rows = connectionDetailRows(form);
  return (
    <div className="connection-form-shell animate-scale-in" data-testid="connection-read-only-view">
      <header>
        <div className="flex items-center gap-2">
          <DbTypeIcon type={form.db_type} />
          <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">{name}</span>
        </div>
        <span className="text-[11px] text-[var(--color-text-dim)] opacity-50">{config.description}</span>
      </header>

      <div className="connection-form-body">
        <ReadOnlyNote block className="mb-4">
          connection settings and credentials are read-only
        </ReadOnlyNote>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
          {rows.map((row) => (
            <div key={row.label} className={row.label === "connection string" ? "col-span-2" : ""}>
              <dt className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">{row.label}</dt>
              <dd
                className={`px-3 py-2 bg-[var(--color-bg-hover)] border border-[var(--color-border)] rounded-[10px] text-xs text-[var(--color-text-muted)] break-all${row.mono ? " font-mono" : ""}`}
              >
                {row.value}
              </dd>
            </div>
          ))}
        </dl>

        <div className="flex items-center gap-3 mt-5 pt-4 border-t border-[var(--color-border)]">
          <button
            type="button"
            onClick={onClose}
            className="flex items-center gap-1.5 px-4 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
          >
            <X className="w-3 h-3" strokeWidth={1.5} /> close
          </button>
          <span className="text-[11px] text-[var(--color-text-dim)] opacity-60 ml-auto">
            ask an org admin to change these settings
          </span>
        </div>
      </div>
    </div>
  );
}
