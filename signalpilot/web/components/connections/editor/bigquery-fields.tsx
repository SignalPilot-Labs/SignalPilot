"use client";

import type { MutableRefObject, Ref } from "react";

import { FormInput, FormTextArea, fieldProps } from "./form-controls";
import type { ConnectionForm } from "~/lib/connections/types";

interface BigQueryFieldsProps {
  form: ConnectionForm;
  setForm: (form: ConnectionForm) => void;
  formErrors: Record<string, string>;
  fieldRefs: MutableRefObject<Record<string, HTMLElement | null>>;
  clearServerError: (key: string) => void;
}

export function BigQueryFields({
  form,
  setForm,
  formErrors,
  fieldRefs,
  clearServerError,
}: BigQueryFieldsProps) {
  function field(key: keyof ConnectionForm, update: (value: string) => void) {
    return (value: string) => {
      update(value);
      clearServerError(key);
    };
  }

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
