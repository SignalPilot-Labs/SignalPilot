"use client";

import { useState, type MutableRefObject, type Ref } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, Lock, Server } from "lucide-react";

import { LocalDbFilePicker } from "./local-db-file-picker";
import { FormInput, FormTextArea, fieldProps } from "./form-controls";
import { DB_CONFIGS } from "~/lib/connections/connector-catalog";
import { detectDbTypeFromUrl, parseConnectionUrl } from "~/lib/connections/connection-url";
import type { ConnectionForm as FormState } from "~/lib/connections/types";

export function ConnectionFieldsForm({
  form, setForm, formErrors, fieldRefs, clearServerError,
}: {
  form: FormState;
  setForm: (f: FormState) => void;
  formErrors: Record<string, string>;
  fieldRefs: MutableRefObject<Record<string, HTMLElement | null>>;
  clearServerError: (key: string) => void;
}) {
  const config = DB_CONFIGS[form.db_type];
  const [showSnowflakeAdvanced, setShowSnowflakeAdvanced] = useState(false);
  const [showXataAdvanced, setShowXataAdvanced] = useState(false);

  /** Wrap onChange to also clear the server error for this field key. */
  function field(key: keyof FormState, update: (v: string) => void) {
    return (v: string) => { update(v); clearServerError(key as string); };
  }

  // URL mode
  if (form.connectionMode === "url") {
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
              // Auto-switch DB type when URL scheme is recognized
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
                    ...(parsed as Partial<FormState>),
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

  // Snowflake fields
  if (form.db_type === "snowflake") {
    return (
      <>
        <FormInput label="account identifier" value={form.account} onChange={field("account", (v) => setForm({ ...form, account: v }))} placeholder="org-account" hint="e.g., xy12345.us-east-1" required {...fieldProps("account", formErrors, fieldRefs)} />
        <FormInput label="username" value={form.username} onChange={field("username", (v) => setForm({ ...form, username: v }))} placeholder="ANALYTICS_USER" required {...fieldProps("username", formErrors, fieldRefs)} />
        <div className="col-span-2 mb-1">
          <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">authentication method</label>
          <div className="flex flex-wrap gap-2">
            {([
              ["password", "password"],
              ["key_pair", "key pair (RSA)"],
              ["oauth", "OAuth"],
              ["pat", "programmatic access token"],
              ["okta", "Okta SSO"],
              ["mfa", "username+password+MFA"],
            ] as const).map(([method, label]) => (
              <button
                key={method}
                type="button"
                onClick={() => setForm({ ...form, snowflake_auth_method: method })}
                className={`px-2.5 py-1 text-[12px] border rounded-[6px] transition-colors duration-150 ${
                  form.snowflake_auth_method === method
                    ? "border-[var(--color-text)] text-[var(--color-text)]"
                    : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {form.snowflake_auth_method === "password" ? (
          <>
            <FormInput label="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} type="password" required className="col-span-2" />
            <div className="col-span-2 px-3 py-2 border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 rounded-[10px] text-[11px] text-[var(--color-warning)]">
              <AlertTriangle className="w-3 h-3 inline mr-1" strokeWidth={1.5} />
              snowflake is enforcing mandatory MFA for all accounts. password-only connections will stop working. switch to <button type="button" onClick={() => setForm({ ...form, snowflake_auth_method: "key_pair" })} className="underline hover:text-[var(--color-text)]">key pair</button> or <button type="button" onClick={() => setForm({ ...form, snowflake_auth_method: "oauth" })} className="underline hover:text-[var(--color-text)]">OAuth</button> authentication.
            </div>
          </>
        ) : form.snowflake_auth_method === "key_pair" ? (
          <>
            <FormTextArea
              label="private key (PEM)"
              value={form.sf_private_key}
              onChange={(v) => setForm({ ...form, sf_private_key: v })}
              placeholder="-----BEGIN ENCRYPTED PRIVATE KEY-----"
              hint="RSA private key for Snowflake key-pair authentication"
              rows={4}
              className="col-span-2"
              {...(fieldProps("sf_private_key", formErrors, fieldRefs) as { id: string; inputRef: Ref<HTMLTextAreaElement>; error: string | undefined })}
            />
            <FormInput label="key passphrase" value={form.sf_private_key_passphrase} onChange={(v) => setForm({ ...form, sf_private_key_passphrase: v })} type="password" hint="leave empty if key is unencrypted" className="col-span-2" />
          </>
        ) : form.snowflake_auth_method === "oauth" ? (
          <>
            <FormInput label="OAuth access token" value={form.sf_oauth_token} onChange={(v) => setForm({ ...form, sf_oauth_token: v })} type="password" required className="col-span-2" hint="from your identity provider (Okta, Azure AD, etc.)" {...fieldProps("sf_oauth_token", formErrors, fieldRefs)} />
            <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
              <div><span className="text-[var(--color-text-muted)]">setup:</span> Create a Snowflake security integration (CREATE SECURITY INTEGRATION ... TYPE = EXTERNAL_OAUTH) and configure your IdP to issue tokens.</div>
              <div><span className="text-[var(--color-text-muted)]">local dev:</span> Use Snowflake&apos;s built-in SNOWFLAKE$LOCAL_APPLICATION integration for quick setup without admin involvement.</div>
            </div>
          </>
        ) : form.snowflake_auth_method === "pat" ? (
          <>
            <FormInput label="programmatic access token" value={form.sf_pat} onChange={field("sf_pat", (v) => setForm({ ...form, sf_pat: v }))} type="password" required className="col-span-2" hint="Snowflake PAT (Admin → Users → Programmatic Access Tokens)" {...fieldProps("sf_pat", formErrors, fieldRefs)} />
          </>
        ) : form.snowflake_auth_method === "mfa" ? (
          <>
            <FormInput label="password" value={form.password} onChange={field("password", (v) => setForm({ ...form, password: v }))} type="password" required className="col-span-2" {...fieldProps("password", formErrors, fieldRefs)} />
            <FormInput label="MFA passcode" value={form.sf_passcode} onChange={(v) => setForm({ ...form, sf_passcode: v })} placeholder="123456" className="col-span-2" hint="optional — TOTP passcode from your authenticator app. leave empty to receive a Duo push." />
          </>
        ) : (
          <>
            <FormInput label="Okta URL" value={form.sf_okta_url} onChange={field("sf_okta_url", (v) => setForm({ ...form, sf_okta_url: v }))} placeholder="https://your-org.okta.com" required className="col-span-2" hint="your Okta organization URL — sent as the Snowflake authenticator" {...fieldProps("sf_okta_url", formErrors, fieldRefs)} />
            <FormInput label="password" value={form.password} onChange={field("password", (v) => setForm({ ...form, password: v }))} type="password" required className="col-span-2" {...fieldProps("password", formErrors, fieldRefs)} />
            <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
              <div><span className="text-[var(--color-text-muted)]">native SSO:</span> Snowflake authenticates directly against Okta using your Okta username and password. Requires Snowflake to be federated with this Okta org.</div>
            </div>
          </>
        )}
        <FormInput label="warehouse" value={form.warehouse} onChange={(v) => setForm({ ...form, warehouse: v })} placeholder="COMPUTE_WH" hint="optional — default warehouse" />
        <FormInput label="database" value={form.database} onChange={(v) => setForm({ ...form, database: v })} placeholder="PROD_DB" hint="optional — default database" />
        <FormInput label="schema" value={form.schema_name} onChange={(v) => setForm({ ...form, schema_name: v })} placeholder="PUBLIC" hint="optional — default schema" />
        <FormInput label="role" value={form.role} onChange={(v) => setForm({ ...form, role: v })} placeholder="ANALYST_ROLE" hint="optional — Snowflake role" />
        <div className="col-span-2">
          <button
            type="button"
            onClick={() => setShowSnowflakeAdvanced(!showSnowflakeAdvanced)}
            className="flex items-center gap-1.5 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors mb-2"
          >
            {showSnowflakeAdvanced ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            advanced — host override
            {(form.snowflake_host.trim() !== "" || form.snowflake_protocol !== "https") && (
              <span className="text-[var(--color-success)] text-[11px] ml-1">
                {[form.snowflake_host.trim() !== "" && "host", form.snowflake_protocol !== "https" && "http"].filter(Boolean).join(" + ")}
              </span>
            )}
          </button>
          {showSnowflakeAdvanced && (
            <div className="animate-fade-in grid grid-cols-2 gap-3">
              <FormInput
                label="host override"
                value={form.snowflake_host}
                onChange={field("snowflake_host", (v) => setForm({ ...form, snowflake_host: v }))}
                placeholder="org-account.privatelink.snowflakecomputing.com"
                hint="explicit host — for PrivateLink, China (.cn), SnowGov, or VPS"
                className="col-span-2"
                {...fieldProps("snowflake_host", formErrors, fieldRefs)}
              />
              <div className="col-span-2">
                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">protocol</label>
                <div className="flex gap-2">
                  {(["https", "http"] as const).map((proto) => (
                    <button
                      key={proto}
                      type="button"
                      onClick={() => setForm({ ...form, snowflake_protocol: proto })}
                      className={`px-2.5 py-1 text-[12px] border rounded-[6px] transition-colors duration-150 ${
                        form.snowflake_protocol === proto
                          ? "border-[var(--color-text)] text-[var(--color-text)]"
                          : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
                      }`}
                    >
                      {proto}
                    </button>
                  ))}
                </div>
                <p className="text-[11px] text-[var(--color-text-dim)] mt-1 opacity-60">defaults to https — leave host override blank unless you need a non-standard endpoint</p>
              </div>
            </div>
          )}
        </div>
        <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
          <div><span className="text-[var(--color-text-muted)]">network policy:</span> Add this server&apos;s IP to ALLOWED_IP_LIST. Snowflake Admin → Security → Network Policies.</div>
          <div><span className="text-[var(--color-text-muted)]">private link:</span> For AWS PrivateLink or Azure Private Link, use the private account URL (e.g., org-account.privatelink.snowflakecomputing.com).</div>
          <div><span className="text-[var(--color-text-muted)]">vpn:</span> If your Snowflake is behind a VPN, ensure SignalPilot has network access to the Snowflake endpoint.</div>
        </div>
      </>
    );
  }

  // Xata fields — a connection is org + project + branch; the agent never sees a raw DB URL.
  if (form.db_type === "xata") {
    const xataAdvancedSet = form.xata_api_url.trim() !== "" && form.xata_api_url.trim() !== "https://api.xata.tech";
    return (
      <>
        <FormInput label="API key" value={form.xata_api_key} onChange={field("xata_api_key", (v) => setForm({ ...form, xata_api_key: v }))} type="password" placeholder="xau_..." hint="Xata control-plane API key" required className="col-span-2" {...fieldProps("xata_api_key", formErrors, fieldRefs)} />
        <FormInput label="organization" value={form.xata_organization} onChange={field("xata_organization", (v) => setForm({ ...form, xata_organization: v }))} placeholder="0psl2d" hint="Xata organization id" required {...fieldProps("xata_organization", formErrors, fieldRefs)} />
        <FormInput label="project" value={form.xata_project} onChange={field("xata_project", (v) => setForm({ ...form, xata_project: v }))} placeholder="prj_037kol78gl76p88o6fngc8s1jk" hint="Xata project id" required {...fieldProps("xata_project", formErrors, fieldRefs)} />
        <FormInput label="branch" value={form.branch} onChange={(v) => setForm({ ...form, branch: v })} placeholder="main" hint="optional — defaults to main" />
        <FormInput label="database" value={form.xata_database} onChange={(v) => setForm({ ...form, xata_database: v })} placeholder="xata" hint="optional — defaults to xata" />
        <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
          <div><Lock className="w-3 h-3 inline mr-1 -mt-0.5" strokeWidth={1.5} /><span className="text-[var(--color-text-muted)]">security:</span> the API key is stored encrypted; the agent only ever receives a governed per-branch endpoint, never the raw URL or key.</div>
        </div>

        {/* Advanced — control-plane endpoint (only for self-hosted / non-default control planes) */}
        <div className="col-span-2">
          <button
            type="button"
            onClick={() => setShowXataAdvanced(!showXataAdvanced)}
            className="flex items-center gap-1.5 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors mb-2"
          >
            {showXataAdvanced ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            advanced — control plane (optional)
            {xataAdvancedSet && <span className="text-[var(--color-success)] text-[11px] ml-1">configured</span>}
          </button>
          {showXataAdvanced && (
            <div className="animate-fade-in grid grid-cols-2 gap-3">
              <FormInput label="control-plane API url" value={form.xata_api_url} onChange={(v) => setForm({ ...form, xata_api_url: v })} placeholder="https://api.xata.tech" hint="optional — only for self-hosted / non-default control planes" className="col-span-2" />
            </div>
          )}
        </div>
      </>
    );
  }

  // BigQuery fields
  if (form.db_type === "bigquery") {
    const bqAuthMethods = ["service_account", "oauth", "adc"] as const;
    const bqAuthLabels: Record<string, string> = { service_account: "service account", oauth: "OAuth token", adc: "application default" };
    return (
      <>
        <FormInput label="gcp project id" value={form.project} onChange={field("project", (v) => setForm({ ...form, project: v }))} placeholder="my-project-123" required {...fieldProps("project", formErrors, fieldRefs)} />
        <FormInput label="default dataset" value={form.dataset} onChange={(v) => setForm({ ...form, dataset: v })} placeholder="analytics" hint="optional — default dataset for queries" />

        {/* Auth method selector */}
        <div className="col-span-2 mb-1">
          <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">authentication method</label>
          <div className="flex gap-2">
            {bqAuthMethods.map((method) => (
              <button
                key={method}
                type="button"
                onClick={() => setForm({ ...form, bq_auth_method: method })}
                className={`px-2.5 py-1 text-[12px] border rounded-[6px] transition-colors duration-150 ${
                  form.bq_auth_method === method
                    ? "border-[var(--color-text)] text-[var(--color-text)]"
                    : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
                }`}
              >
                {bqAuthLabels[method]}
              </button>
            ))}
          </div>
        </div>

        {/* Auth-specific fields */}
        {form.bq_auth_method === "service_account" && (
          <FormTextArea
            label="service account json"
            value={form.credentials_json}
            onChange={field("credentials_json", (v) => setForm({ ...form, credentials_json: v }))}
            placeholder='{"type": "service_account", "project_id": "...", ...}'
            hint="paste the full service account JSON key file contents"
            rows={6}
            className="col-span-2"
            {...(fieldProps("credentials_json", formErrors, fieldRefs) as { id: string; inputRef: Ref<HTMLTextAreaElement>; error: string | undefined })}
          />
        )}
        {form.bq_auth_method === "oauth" && (
          <>
            <FormInput label="OAuth access token" value={form.bq_oauth_token} onChange={(v) => setForm({ ...form, bq_oauth_token: v })} type="password" required className="col-span-2" hint="from Google Cloud OAuth flow or gcloud auth print-access-token" {...fieldProps("bq_oauth_token", formErrors, fieldRefs)} />
            <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
              <div><span className="text-[var(--color-text-muted)]">setup:</span> Create an OAuth client in GCP Console → APIs & Services → Credentials → OAuth 2.0 Client ID.</div>
              <div><span className="text-[var(--color-text-muted)]">scopes:</span> Token must include https://www.googleapis.com/auth/bigquery scope.</div>
            </div>
          </>
        )}
        {form.bq_auth_method === "adc" && (
          <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
            <div><span className="text-[var(--color-text-muted)]">setup:</span> Run <code className="bg-[var(--color-bg-hover)] px-1">gcloud auth application-default login</code> on the server, or set GOOGLE_APPLICATION_CREDENTIALS env var.</div>
            <div><span className="text-[var(--color-text-muted)]">gke:</span> On GKE, workload identity is used automatically. Ensure the KSA is bound to a GCP SA with BigQuery roles.</div>
          </div>
        )}

        {/* Impersonation (cross-project access) */}
        <FormInput
          label="impersonate service account"
          value={form.bq_impersonate_sa}
          onChange={(v) => setForm({ ...form, bq_impersonate_sa: v })}
          placeholder="analytics-reader@target-project.iam.gserviceaccount.com"
          hint="optional — act as another service account for cross-project access"
          className="col-span-2"
        />

        <FormInput
          label="location"
          value={form.bq_location}
          onChange={(v) => setForm({ ...form, bq_location: v })}
          placeholder="US"
          hint="optional — dataset location (US, EU, us-east1, europe-west1, etc.)"
        />
        <FormInput
          label="max bytes billed"
          value={form.bq_max_bytes_billed}
          onChange={(v) => setForm({ ...form, bq_max_bytes_billed: v })}
          placeholder="10737418240"
          hint="safety limit — query fails if scan exceeds this (10GB = 10737418240)"
        />
        <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
          <div><span className="text-[var(--color-text-muted)]">cost control:</span> Set max bytes billed to prevent runaway costs. 2026 pricing: $6.25/TB on-demand (first 1TB free).</div>
          <div><span className="text-[var(--color-text-muted)]">vpc:</span> For VPC Service Controls, ensure the service account has access from SignalPilot&apos;s network perimeter.</div>
        </div>
      </>
    );
  }

  // Databricks fields
  if (form.db_type === "databricks") {
    return (
      <>
        <FormInput label="server hostname" value={form.host} onChange={field("host", (v) => setForm({ ...form, host: v }))} placeholder="adb-1234567890123456.7.azuredatabricks.net" required {...fieldProps("host", formErrors, fieldRefs)} />
        <FormInput label="http path" value={form.http_path} onChange={field("http_path", (v) => setForm({ ...form, http_path: v }))} placeholder="/sql/1.0/warehouses/abc123" hint="SQL warehouse or cluster HTTP path" required {...fieldProps("http_path", formErrors, fieldRefs)} />
        {/* Auth method selector */}
        <div className="col-span-2 mb-1">
          <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">authentication method</label>
          <div className="flex flex-wrap gap-2">
            {(["pat", "oauth_m2m", "oauth_u2m"] as const).map((method) => (
              <button
                key={method}
                type="button"
                onClick={() => setForm({ ...form, databricks_auth_method: method })}
                className={`px-2.5 py-1 text-[12px] border rounded-[6px] transition-colors duration-150 ${
                  form.databricks_auth_method === method
                    ? "border-[var(--color-text)] text-[var(--color-text)]"
                    : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
                }`}
              >
                {method === "pat" ? "personal access token" : method === "oauth_m2m" ? "OAuth M2M (service principal)" : "OAuth U2M (browser)"}
              </button>
            ))}
          </div>
        </div>
        {form.databricks_auth_method === "pat" ? (
          <FormInput label="access token" value={form.access_token} onChange={field("access_token", (v) => setForm({ ...form, access_token: v }))} type="password" hint="personal access token (PAT)" required className="col-span-2" {...fieldProps("access_token", formErrors, fieldRefs)} />
        ) : form.databricks_auth_method === "oauth_m2m" ? (
          <div className="col-span-2 grid grid-cols-2 gap-3 p-3 border border-amber-500/20 bg-amber-500/5 rounded-[10px]">
            <FormInput label="client ID" value={form.dbx_oauth_client_id} onChange={field("dbx_oauth_client_id", (v) => setForm({ ...form, dbx_oauth_client_id: v }))} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" hint="service principal application (client) ID" required {...fieldProps("dbx_oauth_client_id", formErrors, fieldRefs)} />
            <FormInput label="client secret" value={form.dbx_oauth_client_secret} onChange={field("dbx_oauth_client_secret", (v) => setForm({ ...form, dbx_oauth_client_secret: v }))} type="password" hint="service principal client secret" required {...fieldProps("dbx_oauth_client_secret", formErrors, fieldRefs)} />
            <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
              <div><span className="text-[var(--color-text-muted)]">setup:</span> Account Console → User Management → Service Principals → Add. Grant CAN USE on the SQL Warehouse and data access on Unity Catalog.</div>
              <div><span className="text-[var(--color-text-muted)]">recommended:</span> OAuth M2M is the production-grade auth method. PATs are workspace-scoped and expire.</div>
            </div>
          </div>
        ) : (
          <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
            <div><span className="text-[var(--color-text-muted)]">browser auth:</span> OAuth U2M opens a browser window for authentication. Best for interactive development — the token is automatically refreshed.</div>
            <div><span className="text-[var(--color-text-muted)]">setup:</span> Ensure your Databricks workspace has OAuth configured (Admin Console → App Connections) and your user has access to the SQL Warehouse.</div>
            <div><span className="text-[var(--color-text-muted)]">note:</span> OAuth U2M requires the server to have browser access. For headless/server environments, use OAuth M2M instead.</div>
          </div>
        )}
        <FormInput label="catalog" value={form.catalog} onChange={(v) => setForm({ ...form, catalog: v })} placeholder="main" hint="optional — Unity Catalog name" />
        <FormInput label="schema" value={form.schema_name} onChange={(v) => setForm({ ...form, schema_name: v })} placeholder="default" hint="optional — default schema" />
        <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
          <div><span className="text-[var(--color-text-muted)]">private link:</span> For AWS PrivateLink or Azure Private Link, use the private workspace URL (e.g., adb-xxx.x.azuredatabricks.net).</div>
          <div><span className="text-[var(--color-text-muted)]">unity catalog:</span> If enabled, PKs, FKs, and constraints will be automatically extracted for join discovery.</div>
          <div><span className="text-[var(--color-text-muted)]">ip access list:</span> Add this server&apos;s IP to the workspace IP Access List (Workspace Settings → Security → IP Access Lists).</div>
        </div>
      </>
    );
  }

  // Trino — host/port + catalog/schema + auth method + HTTPS toggle
  if (form.db_type === "trino") {
    const trinoAuthMethods = ["none", "password", "jwt", "certificate", "kerberos"] as const;
    const trinoAuthLabels: Record<string, string> = { none: "no auth", password: "password", jwt: "JWT token", certificate: "client cert", kerberos: "Kerberos" };
    return (
      <>
        <FormInput label="host" value={form.host} onChange={field("host", (v) => setForm({ ...form, host: v }))} placeholder="trino.example.com" required {...fieldProps("host", formErrors, fieldRefs)} />
        <FormInput label="port" value={form.port} onChange={field("port", (v) => setForm({ ...form, port: v }))} placeholder={form.trino_https ? "443" : "8080"} {...fieldProps("port", formErrors, fieldRefs)} />
        <FormInput label="username" value={form.username} onChange={field("username", (v) => setForm({ ...form, username: v }))} placeholder="trino" {...fieldProps("username", formErrors, fieldRefs)} />
        <FormInput label="catalog" value={form.catalog} onChange={field("catalog", (v) => setForm({ ...form, catalog: v }))} placeholder="hive" hint="default catalog for queries" {...fieldProps("catalog", formErrors, fieldRefs)} />
        <FormInput label="schema" value={form.schema_name} onChange={(v) => setForm({ ...form, schema_name: v })} placeholder="default" hint="optional — default schema" />

        {/* Auth method selector */}
        <div className="col-span-2 mb-1">
          <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">authentication method</label>
          <div className="flex flex-wrap gap-2">
            {trinoAuthMethods.map((method) => (
              <button
                key={method}
                type="button"
                onClick={() => {
                  const updates: Partial<FormState> = { trino_auth_method: method };
                  // Auto-enable HTTPS for authenticated methods
                  if (method !== "none" && !form.trino_https) {
                    updates.trino_https = true;
                    updates.port = "443";
                  }
                  setForm({ ...form, ...updates } as FormState);
                }}
                className={`px-2.5 py-1 text-[12px] border rounded-[6px] transition-colors duration-150 ${
                  form.trino_auth_method === method
                    ? "border-[var(--color-text)] text-[var(--color-text)]"
                    : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
                }`}
              >
                {trinoAuthLabels[method]}
              </button>
            ))}
          </div>
        </div>

        {/* Auth-specific fields */}
        {form.trino_auth_method === "password" && (
          <FormInput label="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} type="password" required className="col-span-2" />
        )}
        {form.trino_auth_method === "jwt" && (
          <FormInput label="JWT token" value={form.trino_jwt_token} onChange={(v) => setForm({ ...form, trino_jwt_token: v })} type="password" required className="col-span-2" hint="Bearer token from your identity provider (Okta, Auth0, etc.)" />
        )}
        {form.trino_auth_method === "certificate" && (
          <>
            <FormTextArea
              label="client certificate (PEM)"
              value={form.trino_client_cert}
              onChange={(v) => setForm({ ...form, trino_client_cert: v })}
              placeholder="-----BEGIN CERTIFICATE-----"
              rows={3}
              className="col-span-2"
            />
            <FormTextArea
              label="client private key (PEM)"
              value={form.trino_client_key}
              onChange={(v) => setForm({ ...form, trino_client_key: v })}
              placeholder="-----BEGIN PRIVATE KEY-----"
              rows={3}
              hint="optional — if separate from certificate"
              className="col-span-2"
            />
          </>
        )}
        {form.trino_auth_method === "kerberos" && (
          <>
            <FormInput label="service name" value={form.trino_krb_service_name} onChange={(v) => setForm({ ...form, trino_krb_service_name: v })} placeholder="trino" hint="Kerberos service principal name" className="col-span-2" />
            <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
              <div><span className="text-[var(--color-text-muted)]">setup:</span> Configure krb5.conf and kinit before connecting. The server must have a valid Kerberos ticket.</div>
              <div><span className="text-[var(--color-text-muted)]">keytab:</span> For unattended access, configure a keytab file in /etc/krb5.keytab or via KRB5_KTNAME.</div>
            </div>
          </>
        )}

        {/* HTTPS toggle */}
        <div className="col-span-2">
          <button
            type="button"
            onClick={() => setForm({ ...form, trino_https: !form.trino_https, port: !form.trino_https ? "443" : "8080" })}
            className="flex items-center gap-2 text-[12px] transition-colors"
          >
            <div className={`w-3 h-3 border rounded-[3px] flex items-center justify-center transition-colors ${form.trino_https ? "border-emerald-500 bg-emerald-500/20" : "border-[var(--color-border)]"}`}>
              {form.trino_https && <div className="w-1.5 h-1.5 bg-emerald-400" />}
            </div>
            <span className={form.trino_https ? "text-[var(--color-text)]" : "text-[var(--color-text-dim)]"}>use HTTPS</span>
            {form.trino_https && <Lock className="w-3 h-3 text-emerald-400" strokeWidth={1.5} />}
          </button>
          <p className="text-[11px] text-[var(--color-text-dim)] mt-1 opacity-60 ml-5">
            {form.trino_https ? "encrypted connection — required for Starburst Galaxy and password auth" : "plain HTTP — for local/development clusters only"}
          </p>
        </div>
        <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)]">
          <span className="text-[var(--color-text-muted)]">note:</span> Trino supports federated queries across multiple catalogs (Hive, Iceberg, MySQL, PostgreSQL, etc.). Each catalog maps to a data source configured in Trino.
        </div>
      </>
    );
  }

  // SQLite — mode selector: local file or in-memory
  if (form.db_type === "sqlite") {
    const sqliteMode = form.database === ":memory:" ? "memory" : "local";
    return (
      <>
        <div className="col-span-2 mb-1">
          <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">mode</label>
          <div className="flex gap-2">
            {([
              { key: "local", label: "local file" },
              { key: "memory", label: "in-memory" },
            ] as const).filter(({ key }) => !(IS_CLOUD_MODE && key === "local")).map(({ key, label }) => (
              <button
                key={key}
                type="button"
                onClick={() => {
                  if (key === "memory") setForm({ ...form, database: ":memory:" });
                  else setForm({ ...form, database: form.database === ":memory:" ? "" : form.database });
                }}
                className={`px-2.5 py-1 text-[12px] border rounded-[6px] transition-colors duration-150 ${
                  sqliteMode === key
                    ? "border-[var(--color-text)] text-[var(--color-text)]"
                    : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {!IS_CLOUD_MODE && sqliteMode === "local" && (
          <div className="col-span-2">
          <LocalDbFilePicker
              value={form.database}
              onChange={(v) => { setForm({ ...form, database: v }); clearServerError("database"); }}
              pattern="*.sqlite,*.db"
              placeholder="/path/to/database.sqlite"
              hint="paste a file path or browse to select a .sqlite or .db file"
              {...fieldProps("database", formErrors, fieldRefs)}
            />
          </div>
        )}

        {sqliteMode === "memory" && (
          <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)]">
            <span className="text-[var(--color-text-muted)]">note:</span> in-memory databases are ephemeral — data is lost when the gateway restarts.
          </div>
        )}
      </>
    );
  }

  // DuckDB — mode selector: in-memory, local file, or MotherDuck
  if (form.db_type === "duckdb") {
    return (
      <>
        <div className="col-span-2 mb-1">
          <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">mode</label>
          <div className="flex gap-2">
            {([
              { key: "local", label: "local file" },
              { key: "motherduck", label: "MotherDuck" },
              { key: "memory", label: "in-memory" },
            ] as const).filter(({ key }) => !(IS_CLOUD_MODE && (key === "local" || key === "memory"))).map(({ key, label }) => (
              <button
                key={key}
                type="button"
                onClick={() => {
                  const updates: Partial<FormState> = { duckdb_mode: key };
                  if (key === "memory") updates.database = ":memory:";
                  else if (key === "motherduck") updates.database = form.database.startsWith("md:") ? form.database : "md:";
                  else updates.database = form.database === ":memory:" || form.database.startsWith("md:") ? "" : form.database;
                  setForm({ ...form, ...updates });
                }}
                className={`px-2.5 py-1 text-[12px] border rounded-[6px] transition-colors duration-150 ${
                  form.duckdb_mode === key
                    ? "border-[var(--color-text)] text-[var(--color-text)]"
                    : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {!IS_CLOUD_MODE && form.duckdb_mode === "local" && (
          <div className="col-span-2">
          <LocalDbFilePicker
              value={form.database}
              onChange={(v) => { setForm({ ...form, database: v }); clearServerError("database"); }}
              pattern="*.duckdb"
              placeholder="/path/to/database.duckdb"
              hint="paste a file path or browse to select a .duckdb file"
              {...fieldProps("database", formErrors, fieldRefs)}
            />
          </div>
        )}

        {form.duckdb_mode === "motherduck" && (
          <>
            <FormInput
              label="database name"
              value={form.database.startsWith("md:") ? form.database.slice(3) : form.database}
              onChange={field("database", (v) => setForm({ ...form, database: `md:${v}` }))}
              placeholder="my_database"
              hint="MotherDuck database name (without md: prefix)"
              required
              {...fieldProps("database", formErrors, fieldRefs)}
            />
            <FormInput
              label="token"
              value={form.motherduck_token}
              onChange={(v) => setForm({ ...form, motherduck_token: v })}
              type="password"
              placeholder="eyJ..."
              hint="personal access token from app.motherduck.com"
              required
            />
          </>
        )}

        {form.duckdb_mode === "memory" && (
          <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)]">
            <span className="text-[var(--color-text-muted)]">note:</span> in-memory databases are ephemeral — data is lost when the gateway restarts. Use MotherDuck for persistent cloud-hosted DuckDB.
          </div>
        )}
      </>
    );
  }

  // ClickHouse — protocol selector + host/port
  if (form.db_type === "clickhouse") {
    const httpPort = form.ssl_enabled ? "8443" : "8123";
    const nativePort = form.ssl_enabled ? "9440" : "9000";
    return (
      <>
        <div className="col-span-2 mb-1">
          <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">protocol</label>
          <div className="flex gap-2">
            {(["native", "http"] as const).map((proto) => (
              <button
                key={proto}
                type="button"
                onClick={() => setForm({ ...form, ch_protocol: proto, port: proto === "http" ? httpPort : nativePort })}
                className={`px-2.5 py-1 text-[12px] border rounded-[6px] transition-colors duration-150 ${
                  form.ch_protocol === proto
                    ? "border-[var(--color-text)] text-[var(--color-text)]"
                    : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
                }`}
              >
                {proto === "native" ? "native TCP (:9000)" : "HTTP (:8123)"}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-[var(--color-text-dim)] mt-1 opacity-60">
            {form.ch_protocol === "http"
              ? "HTTP protocol — better compatibility with ClickHouse Cloud and load balancers"
              : "native protocol — fastest performance, direct binary protocol"}
          </p>
        </div>
        <FormInput label="host" value={form.host} onChange={field("host", (v) => setForm({ ...form, host: v }))} placeholder="localhost" required {...fieldProps("host", formErrors, fieldRefs)} />
        <FormInput label="port" value={form.port} onChange={field("port", (v) => setForm({ ...form, port: v }))} placeholder={form.ch_protocol === "http" ? httpPort : nativePort} {...fieldProps("port", formErrors, fieldRefs)} />
        <FormInput label="database" value={form.database} onChange={field("database", (v) => setForm({ ...form, database: v }))} placeholder="default" required {...fieldProps("database", formErrors, fieldRefs)} />
        <FormInput label="username" value={form.username} onChange={field("username", (v) => setForm({ ...form, username: v }))} placeholder="default" required {...fieldProps("username", formErrors, fieldRefs)} />
        <FormInput label="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} type="password" />
      </>
    );
  }

  // MSSQL — instance name, trust cert, encrypt option, Azure AD
  if (form.db_type === "mssql") {
    return (
      <>
        <FormInput label="host" value={form.host} onChange={field("host", (v) => setForm({ ...form, host: v }))} placeholder="sqlserver.example.com" hint="hostname or IP — for named instances: host\\INSTANCE" required {...fieldProps("host", formErrors, fieldRefs)} />
        <FormInput label="port" value={form.port} onChange={field("port", (v) => setForm({ ...form, port: v }))} placeholder="1433" hint="default 1433 — Azure SQL uses 1433" {...fieldProps("port", formErrors, fieldRefs)} />
        <FormInput label="database" value={form.database} onChange={field("database", (v) => setForm({ ...form, database: v }))} placeholder="all databases" hint="leave empty to expose every accessible database on the server (multi-database mode)" {...fieldProps("database", formErrors, fieldRefs)} />
        {!form.azure_ad_auth && (
          <>
            <FormInput label="username" value={form.username} onChange={field("username", (v) => setForm({ ...form, username: v }))} placeholder="sa" hint="SQL Server login" required {...fieldProps("username", formErrors, fieldRefs)} />
            <FormInput label="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} type="password" />
          </>
        )}
        {/* Azure AD / Entra ID toggle */}
        <div className="col-span-2 mb-1">
          <button
            type="button"
            onClick={() => setForm({ ...form, azure_ad_auth: !form.azure_ad_auth })}
            className={`flex items-center gap-2 px-2.5 py-1.5 text-[12px] border rounded-[6px] transition-colors duration-150 ${
              form.azure_ad_auth
                ? "border-blue-500/50 text-blue-400 bg-blue-500/10"
                : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
            }`}
          >
            <Shield className="w-3 h-3" />
            <span>Azure AD / Entra ID</span>
            {form.azure_ad_auth && <span className="text-[var(--color-success)] text-[11px]">enabled</span>}
          </button>
        </div>
        {form.azure_ad_auth && (
          <div className="col-span-2 grid grid-cols-2 gap-3 p-3 border border-blue-500/20 bg-blue-500/5 rounded-[10px]">
            <FormInput label="tenant ID" value={form.azure_tenant_id} onChange={(v) => setForm({ ...form, azure_tenant_id: v })} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" hint="Azure AD directory (tenant) ID" required {...fieldProps("azure_tenant_id", formErrors, fieldRefs)} />
            <FormInput label="client ID" value={form.azure_client_id} onChange={(v) => setForm({ ...form, azure_client_id: v })} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" hint="App registration (client) ID" required {...fieldProps("azure_client_id", formErrors, fieldRefs)} />
            <FormInput label="client secret" value={form.azure_client_secret} onChange={(v) => setForm({ ...form, azure_client_secret: v })} type="password" hint="Service principal client secret" required className="col-span-2" {...fieldProps("azure_client_secret", formErrors, fieldRefs)} />
            <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
              <div><span className="text-[var(--color-text-muted)]">setup:</span> Azure Portal → App Registrations → New → Add API Permission for Azure SQL Database. Create a contained DB user: CREATE USER [app-name] FROM EXTERNAL PROVIDER.</div>
              <div><span className="text-[var(--color-text-muted)]">managed identity:</span> For Azure VMs/containers, leave client secret empty to use system-assigned managed identity (coming soon).</div>
            </div>
          </div>
        )}
        <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
          <div><span className="text-[var(--color-text-muted)]">multi-database:</span> Leave database empty to map every accessible database on the server (incl. AWS RDS) through one connection — tables appear as database.schema.table.</div>
          <div><span className="text-[var(--color-text-muted)]">azure sql:</span> Use &lt;server&gt;.database.windows.net as host. Ensure firewall rule allows this server&apos;s IP.</div>
          <div><span className="text-[var(--color-text-muted)]">named instances:</span> Include instance in host: host\SQLEXPRESS. Or use port directly (SQL Browser resolves instances to ports).</div>
          <div><span className="text-[var(--color-text-muted)]">on-prem:</span> For SQL Server behind a firewall, use the SSH tunnel option in Advanced settings.</div>
        </div>
      </>
    );
  }

  // Redshift — cluster endpoint guidance + IAM auth
  if (form.db_type === "redshift") {
    return (
      <>
        <FormInput label="cluster endpoint" value={form.host} onChange={field("host", (v) => setForm({ ...form, host: v }))} placeholder="my-cluster.abc123xyz.us-east-1.redshift.amazonaws.com" hint="Redshift console → Clusters → Properties → Endpoint" required {...fieldProps("host", formErrors, fieldRefs)} />
        <FormInput label="port" value={form.port} onChange={field("port", (v) => setForm({ ...form, port: v }))} placeholder="5439" {...fieldProps("port", formErrors, fieldRefs)} />
        <FormInput label="database" value={form.database} onChange={field("database", (v) => setForm({ ...form, database: v }))} placeholder="dev" hint="default database is 'dev'" required {...fieldProps("database", formErrors, fieldRefs)} />
        {!form.iam_auth && (
          <>
            <FormInput label="username" value={form.username} onChange={field("username", (v) => setForm({ ...form, username: v }))} placeholder="awsuser" required {...fieldProps("username", formErrors, fieldRefs)} />
            <FormInput label="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} type="password" />
          </>
        )}
        {/* IAM Auth toggle */}
        <div className="col-span-2 mb-1">
          <button
            type="button"
            onClick={() => setForm({ ...form, iam_auth: !form.iam_auth })}
            className={`flex items-center gap-2 px-2.5 py-1.5 text-[12px] border rounded-[6px] transition-colors duration-150 ${
              form.iam_auth
                ? "border-amber-500/50 text-amber-400 bg-amber-500/10"
                : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
            }`}
          >
            <Shield className="w-3 h-3" />
            <span>AWS IAM auth</span>
            {form.iam_auth && <span className="text-[var(--color-success)] text-[11px]">enabled</span>}
          </button>
        </div>
        {form.iam_auth && (
          <div className="col-span-2 grid grid-cols-2 gap-3 p-3 border border-amber-500/20 bg-amber-500/5 rounded-[10px]">
            <FormInput label="username" value={form.username} onChange={field("username", (v) => setForm({ ...form, username: v }))} placeholder="awsuser" hint="Redshift DB user to get temporary credentials for" required {...fieldProps("username", formErrors, fieldRefs)} />
            <FormInput label="AWS region" value={form.aws_region} onChange={(v) => setForm({ ...form, aws_region: v })} placeholder="us-east-1" hint="Redshift cluster region" />
            <FormInput label="cluster ID" value={form.redshift_cluster_id} onChange={(v) => setForm({ ...form, redshift_cluster_id: v })} placeholder="my-redshift-cluster" hint="provisioned cluster ID (auto-detected from endpoint if blank)" />
            <FormInput label="workgroup" value={form.redshift_workgroup} onChange={(v) => setForm({ ...form, redshift_workgroup: v })} placeholder="default" hint="for Redshift Serverless only" />
            <FormInput label="AWS access key ID" value={form.aws_access_key_id} onChange={(v) => setForm({ ...form, aws_access_key_id: v })} placeholder="AKIA..." hint="leave empty to use instance profile / env credentials" />
            <FormInput label="AWS secret access key" value={form.aws_secret_access_key} onChange={(v) => setForm({ ...form, aws_secret_access_key: v })} type="password" hint="leave empty to use instance profile / env credentials" />
            <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
              <div><span className="text-[var(--color-text-muted)]">setup:</span> IAM user/role needs redshift:GetClusterCredentials (provisioned) or redshift-serverless:GetCredentials (serverless).</div>
              <div><span className="text-[var(--color-text-muted)]">credentials:</span> Leave access key fields empty to use EC2 instance profile, ECS task role, or AWS_* env vars.</div>
            </div>
          </div>
        )}
        <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
          <div><span className="text-[var(--color-text-muted)]">access:</span> Ensure this server&apos;s IP is allowed in the Redshift security group. For VPC clusters, use SSH tunnel or VPC peering.</div>
          <div><span className="text-[var(--color-text-muted)]">serverless:</span> Use workgroup endpoint: &lt;workgroup-name&gt;.&lt;account-id&gt;.&lt;region&gt;.redshift-serverless.amazonaws.com</div>
        </div>
      </>
    );
  }

  // Standard host/port (Postgres, MySQL)
  const placeholders: Record<string, Record<string, string>> = {
    postgres: { host: "localhost", db: "mydb", user: "postgres" },
    mysql: { host: "localhost", db: "mydb", user: "root" },
  };
  const ph = placeholders[form.db_type] || { host: "localhost", db: "mydb", user: "user" };
  return (
    <>
      <FormInput label="host" value={form.host} onChange={field("host", (v) => setForm({ ...form, host: v }))} placeholder={ph.host} required {...fieldProps("host", formErrors, fieldRefs)} />
      <FormInput label="port" value={form.port} onChange={field("port", (v) => setForm({ ...form, port: v }))} placeholder={String(config.defaultPort)} {...fieldProps("port", formErrors, fieldRefs)} />
      <FormInput label="database" value={form.database} onChange={field("database", (v) => setForm({ ...form, database: v }))} placeholder={ph.db} required />
      <FormInput label="username" value={form.username} onChange={field("username", (v) => setForm({ ...form, username: v }))} placeholder={ph.user} required {...fieldProps("username", formErrors, fieldRefs)} />
      {!form.iam_auth && (
        <FormInput label="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} type="password" />
      )}
      {/* AWS IAM Auth toggle for RDS */}
      <div className="col-span-2 mt-1">
        <button
          type="button"
          onClick={() => setForm({ ...form, iam_auth: !form.iam_auth })}
          className={`flex items-center gap-2 px-2.5 py-1 text-[12px] border rounded-[6px] transition-colors duration-150 ${
            form.iam_auth
              ? "border-[var(--color-text)] text-[var(--color-text)]"
              : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
          }`}
        >
          {form.iam_auth ? "✓ " : ""}AWS IAM authentication
        </button>
      </div>
      {form.iam_auth && (
        <>
          <FormInput label="AWS region" value={form.aws_region} onChange={(v) => setForm({ ...form, aws_region: v })} placeholder="us-east-1" hint="RDS instance region" />
          <FormInput label="AWS access key ID" value={form.aws_access_key_id} onChange={(v) => setForm({ ...form, aws_access_key_id: v })} placeholder="AKIA..." hint="leave empty to use instance profile / env credentials" />
          <FormInput label="AWS secret access key" value={form.aws_secret_access_key} onChange={(v) => setForm({ ...form, aws_secret_access_key: v })} type="password" hint="leave empty to use instance profile / env credentials" />
          <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
            <div><span className="text-[var(--color-text-muted)]">setup:</span> DB user must have rds_iam role (PostgreSQL) or be created with AWSAuthenticationPlugin (MySQL). SSL is auto-enabled.</div>
            <div><span className="text-[var(--color-text-muted)]">credentials:</span> Leave access key fields empty to use EC2 instance profile, ECS task role, or AWS_* env vars.</div>
          </div>
        </>
      )}
      {/* Connection guidance (HEX pattern — contextual setup instructions) */}
      <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)] space-y-1">
        {form.db_type === "postgres" ? (
          <>
            <div><span className="text-[var(--color-text-muted)]">rds:</span> Use endpoint from RDS Console → Connectivity. Ensure security group allows this server&apos;s IP on port 5432.</div>
            <div><span className="text-[var(--color-text-muted)]">supabase:</span> Project Settings → Database → Connection string. Use pooler for serverless (port 6543).</div>
            <div><span className="text-[var(--color-text-muted)]">neon:</span> Use the connection string from Neon console. SSL is required (auto-enabled).</div>
            <div><span className="text-[var(--color-text-muted)]">on-prem:</span> For databases behind a firewall, enable the SSH tunnel in Advanced settings.</div>
          </>
        ) : (
          <>
            <div><span className="text-[var(--color-text-muted)]">rds:</span> Use endpoint from RDS Console → Connectivity. Security group must allow port 3306 from this server.</div>
            <div><span className="text-[var(--color-text-muted)]">planetscale:</span> Use the connection string from PlanetScale dashboard. SSL is required (auto-enabled).</div>
            <div><span className="text-[var(--color-text-muted)]">cloud sql:</span> For Google Cloud SQL, use the Cloud SQL Auth Proxy or add this server&apos;s IP to authorized networks.</div>
            <div><span className="text-[var(--color-text-muted)]">on-prem:</span> For MySQL behind a firewall, enable the SSH tunnel in Advanced settings.</div>
          </>
        )}
      </div>
    </>
  );
}

/* ── SSL Config Section ── */
