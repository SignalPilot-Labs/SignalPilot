"use client";

import { useState, type MutableRefObject, type Ref } from "react";
import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";

import { FormInput, FormTextArea, fieldProps } from "./form-controls";
import type { ConnectionForm } from "~/lib/connections/types";

interface SnowflakeFieldsProps {
  form: ConnectionForm;
  setForm: (form: ConnectionForm) => void;
  formErrors: Record<string, string>;
  fieldRefs: MutableRefObject<Record<string, HTMLElement | null>>;
  clearServerError: (key: string) => void;
}

export function SnowflakeFields({
  form,
  setForm,
  formErrors,
  fieldRefs,
  clearServerError,
}: SnowflakeFieldsProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  function field(key: keyof ConnectionForm, update: (value: string) => void) {
    return (value: string) => {
      update(value);
      clearServerError(key);
    };
  }

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
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex items-center gap-1.5 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors mb-2"
        >
          {showAdvanced ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          advanced — host override
          {(form.snowflake_host.trim() !== "" || form.snowflake_protocol !== "https") && (
            <span className="text-[var(--color-success)] text-[11px] ml-1">
              {[form.snowflake_host.trim() !== "" && "host", form.snowflake_protocol !== "https" && "http"].filter(Boolean).join(" + ")}
            </span>
          )}
        </button>
        {showAdvanced && (
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
