"use client";

import type { MutableRefObject, Ref } from "react";
import { ChevronDown, ChevronRight, Lock, Server } from "lucide-react";

import { FormInput, FormTextArea, fieldProps } from "./form-controls";
import { DB_CONFIGS } from "~/lib/connections/connector-catalog";
import type { ConnectionForm as FormState } from "~/lib/connections/types";

export function SslSection({ form, setForm, formErrors, fieldRefs }: {
  form: FormState;
  setForm: (f: FormState) => void;
  formErrors: Record<string, string>;
  fieldRefs: MutableRefObject<Record<string, HTMLElement | null>>;
}) {
  const config = DB_CONFIGS[form.db_type];
  if (!config.supportsSSL) return null;

  return (
    <div className="border-t border-[var(--color-border)] pt-4 mt-4">
      <button
        type="button"
        onClick={() => setForm({ ...form, ssl_enabled: !form.ssl_enabled })}
        className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
      >
        <Lock className="w-3 h-3" strokeWidth={1.5} />
        <span>ssl / tls</span>
        {form.ssl_enabled ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {form.ssl_enabled && <span className="text-[var(--color-success)] text-[11px]">enabled</span>}
      </button>
      {form.ssl_enabled && (
        <div className="grid grid-cols-2 gap-4 mt-3 animate-fade-in">
          <div>
            <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">ssl mode</label>
            <select
              value={form.ssl_mode}
              onChange={(e) => setForm({ ...form, ssl_mode: e.target.value })}
              className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
            >
              <option value="require">require — encrypt, skip cert verification</option>
              <option value="verify-ca">verify-ca — encrypt + verify CA</option>
              <option value="verify-full">verify-full — encrypt + verify CA + hostname</option>
              <option value="prefer">prefer — encrypt if server supports</option>
              <option value="allow">allow — no encryption preference</option>
              <option value="disable">disable — no encryption</option>
            </select>
            <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60">
              {form.ssl_mode === "require" && "encrypts traffic but does not verify the server certificate. good for cloud databases with trusted networks."}
              {form.ssl_mode === "verify-ca" && "verifies the server cert is signed by a trusted CA. requires CA certificate below."}
              {form.ssl_mode === "verify-full" && "strongest security: verifies CA + server hostname matches the cert. recommended for production."}
              {form.ssl_mode === "prefer" && "uses encryption if the server supports it, falls back to plaintext otherwise."}
              {form.ssl_mode === "allow" && "connects without preference — server decides. not recommended for production."}
              {form.ssl_mode === "disable" && "no encryption. only use for local development or trusted private networks."}
            </p>
          </div>
          <div />
          {form.ssl_mode !== "disable" && (
            <>
              <FormTextArea label="ca certificate (pem)" value={form.ssl_ca_cert} onChange={(v) => setForm({ ...form, ssl_ca_cert: v })} placeholder="-----BEGIN CERTIFICATE-----" hint={form.ssl_mode.startsWith("verify") ? "required for certificate verification" : "optional — root CA for server verification"} rows={3} {...(fieldProps("ssl_ca_cert", formErrors, fieldRefs) as { id: string; inputRef: Ref<HTMLTextAreaElement>; error: string | undefined })} />
              <FormTextArea label="client certificate (pem)" value={form.ssl_client_cert} onChange={(v) => setForm({ ...form, ssl_client_cert: v })} placeholder="-----BEGIN CERTIFICATE-----" hint="optional — for mutual TLS (mTLS) authentication" rows={3} />
              <FormTextArea label="client key (pem)" value={form.ssl_client_key} onChange={(v) => setForm({ ...form, ssl_client_key: v })} placeholder="-----BEGIN PRIVATE KEY-----" hint="required when using client certificate" rows={3} className="col-span-2" />
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function SshSection({
  form, setForm, serverIp, formErrors, fieldRefs, clearServerError,
}: {
  form: FormState;
  setForm: (f: FormState) => void;
  serverIp?: string | null;
  formErrors: Record<string, string>;
  fieldRefs: MutableRefObject<Record<string, HTMLElement | null>>;
  clearServerError: (key: string) => void;
}) {
  const config = DB_CONFIGS[form.db_type];
  if (!config.supportsSSH) return null;

  return (
    <div className="border-t border-[var(--color-border)] pt-4 mt-4">
      <button
        type="button"
        onClick={() => setForm({ ...form, ssh_enabled: !form.ssh_enabled })}
        className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
      >
        <Server className="w-3 h-3" strokeWidth={1.5} />
        <span>ssh tunnel</span>
        {form.ssh_enabled ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {form.ssh_enabled && <span className="text-[var(--color-success)] text-[11px]">enabled</span>}
      </button>
      {form.ssh_enabled && (
        <div className="grid grid-cols-2 gap-4 mt-3 animate-fade-in">
          <FormInput label="ssh host" value={form.ssh_host} onChange={(v) => { setForm({ ...form, ssh_host: v }); clearServerError("ssh_host"); }} placeholder="bastion.example.com" required {...fieldProps("ssh_host", formErrors, fieldRefs)} />
          <FormInput label="ssh port" value={form.ssh_port} onChange={(v) => { setForm({ ...form, ssh_port: v }); clearServerError("ssh_port"); }} placeholder="22" {...fieldProps("ssh_port", formErrors, fieldRefs)} />
          <FormInput label="ssh username" value={form.ssh_username} onChange={(v) => { setForm({ ...form, ssh_username: v }); clearServerError("ssh_username"); }} placeholder="ubuntu" required {...fieldProps("ssh_username", formErrors, fieldRefs)} />
          <div>
            <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">auth method</label>
            <select
              value={form.ssh_auth_method}
              onChange={(e) => setForm({ ...form, ssh_auth_method: e.target.value })}
              className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
            >
              <option value="password">password</option>
              <option value="key">private key</option>
              <option value="agent">ssh-agent (forwarded key)</option>
            </select>
          </div>
          {form.ssh_auth_method === "password" && (
            <FormInput label="ssh password" value={form.ssh_password} onChange={(v) => { setForm({ ...form, ssh_password: v }); clearServerError("ssh_password"); }} type="password" className="col-span-2" {...fieldProps("ssh_password", formErrors, fieldRefs)} />
          )}
          {form.ssh_auth_method === "key" && (
            <>
              <FormTextArea label="private key (pem)" value={form.ssh_private_key} onChange={(v) => { setForm({ ...form, ssh_private_key: v }); clearServerError("ssh_private_key"); }} placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" rows={4} className="col-span-2" {...(fieldProps("ssh_private_key", formErrors, fieldRefs) as { id: string; inputRef: Ref<HTMLTextAreaElement>; error: string | undefined })} />
              <FormInput label="key passphrase" value={form.ssh_key_passphrase} onChange={(v) => setForm({ ...form, ssh_key_passphrase: v })} type="password" hint="leave empty if key is not encrypted" className="col-span-2" />
            </>
          )}
          {form.ssh_auth_method === "agent" && (
            <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px]">
              <p className="text-[11px] text-[var(--color-text-dim)]">
                uses the ssh-agent running on the signalpilot server. ensure <code className="text-[var(--color-text-muted)]">SSH_AUTH_SOCK</code> is set and your key is loaded with <code className="text-[var(--color-text-muted)]">ssh-add</code>.
              </p>
            </div>
          )}
          {/* Use an HTTP proxy when the network blocks direct SSH connections. */}
          <div className="col-span-2 border-t border-[var(--color-border)]/50 pt-3 mt-1">
            <button
              type="button"
              onClick={() => setForm({ ...form, ssh_proxy_enabled: !form.ssh_proxy_enabled })}
              className="flex items-center gap-2 text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors mb-2"
            >
              {form.ssh_proxy_enabled ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              <span>http proxy for ssh</span>
              {form.ssh_proxy_enabled && <span className="text-[var(--color-success)] text-[11px]">enabled</span>}
            </button>
            {form.ssh_proxy_enabled && (
              <div className="grid grid-cols-2 gap-3 animate-fade-in">
                <FormInput label="proxy host" value={form.ssh_proxy_host} onChange={(v) => setForm({ ...form, ssh_proxy_host: v })} placeholder="proxy.corp.example.com" hint="HTTP CONNECT proxy (e.g. Squid)" required />
                <FormInput label="proxy port" value={form.ssh_proxy_port} onChange={(v) => setForm({ ...form, ssh_proxy_port: v })} placeholder="3128" hint="default: 3128 (Squid)" />
                <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px] text-[11px] text-[var(--color-text-dim)]">
                  routes ssh through an http connect proxy. use this when your vpc or corporate network blocks direct ssh connections to the bastion host. requires <code className="text-[var(--color-text-muted)]">socat</code> on the signalpilot server.
                </div>
              </div>
            )}
          </div>

          <div className="col-span-2 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px]">
            <p className="text-[11px] text-[var(--color-text-dim)]">
              signalpilot creates an on-demand ssh tunnel to your database through this bastion host.
              {serverIp ? (
                <> whitelist <code className="text-[var(--color-text-muted)]">{serverIp}/32</code> on your bastion.</>
              ) : (
                <> whitelist our server ip on your bastion.</>
              )}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}


