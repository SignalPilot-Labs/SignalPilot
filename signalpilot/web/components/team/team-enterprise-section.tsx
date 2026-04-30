"use client";

/**
 * Read-only admin view of Clerk Enterprise SSO connections scoped to the
 * caller's active organization. Admins see protocol/domains/status + an
 * expandable SAML IdP handoff detail panel. Non-admins see a stub.
 *
 * All create/edit/delete remain in the Clerk dashboard per the ops playbook.
 */

import React, { useState, useEffect, useRef } from "react";
import { ShieldCheck, ChevronDown, ChevronUp } from "lucide-react";
import { SectionHeader } from "@/components/ui/section-header";
import { Skeleton } from "@/components/ui/skeleton";
import {
  LABEL_CLASS,
  ERROR_CLASS,
  NEUTRAL_CLASS,
  SECONDARY_BTN_CLASS,
} from "@/components/auth/auth-primitives";
import type { TeamPermissions } from "@/lib/team/use-team-permissions";
import type { EnterpriseConnectionDTO } from "@/app/api/team/enterprise/route";

// Re-export for consumers that want the DTO type
export type { EnterpriseConnectionDTO };

export interface TeamEnterpriseSectionProps {
  perms: TeamPermissions;
}

// ---------------------------------------------------------------------------
// Inline copy button — no new primitive
// ---------------------------------------------------------------------------

function CopyValueButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  const onClick = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      timerRef.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard rejected (insecure context or permissions) — surface inline
      setCopied(false);
    }
  };

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`copy ${label}`}
      className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider underline underline-offset-2 transition-colors font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
    >
      {copied ? "copied" : "copy"}
    </button>
  );
}

// ---------------------------------------------------------------------------
// SAML IdP handoff detail panel
// ---------------------------------------------------------------------------

interface SamlHandoffPanelProps {
  saml: NonNullable<EnterpriseConnectionDTO["saml"]>;
}

function SamlHandoffPanel({ saml }: SamlHandoffPanelProps) {
  const fields: Array<{ key: string; label: string; value: string | null }> = [
    { key: "acsUrl", label: "acs url", value: saml.acsUrl },
    { key: "spEntityId", label: "sp entity id", value: saml.spEntityId },
    { key: "spMetadataUrl", label: "sp metadata url", value: saml.spMetadataUrl },
    { key: "idpEntityId", label: "idp entity id", value: saml.idpEntityId },
    { key: "idpSsoUrl", label: "idp sso url", value: saml.idpSsoUrl },
  ];

  return (
    <dl className="mt-3 ml-2 space-y-2 border-l border-[var(--color-border)] pl-4">
      {fields.map(({ key, label, value }) => (
        <div key={key} className="flex flex-col gap-0.5">
          <dt className={LABEL_CLASS}>{label}</dt>
          <dd className="flex items-center gap-2">
            {value !== null ? (
              <>
                <span className="font-mono text-[12px] text-[var(--color-text)] break-all">
                  {value}
                </span>
                <CopyValueButton value={value} label={label} />
              </>
            ) : (
              <span className={NEUTRAL_CLASS}>not yet provided by idp</span>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

// ---------------------------------------------------------------------------
// Single connection row
// ---------------------------------------------------------------------------

interface ConnectionRowProps {
  connection: EnterpriseConnectionDTO;
}

function ConnectionRow({ connection }: ConnectionRowProps) {
  const [expanded, setExpanded] = useState(false);

  const hasSamlDetails = connection.protocol === "saml" && connection.saml !== null;
  const isSamlPending = connection.protocol === "saml" && connection.saml === null;
  const isUnknown = connection.protocol === "unknown";

  return (
    <li className="px-5 py-4 space-y-2">
      {/* Top row: name + protocol + domains + status */}
      <div className="flex flex-wrap items-center gap-2">
        {/* Connection name */}
        <span className="text-[13px] text-[var(--color-text)] font-mono mr-1">
          {connection.name}
        </span>

        {/* Protocol badge */}
        {connection.protocol !== "unknown" && (
          <span className="px-1.5 py-0.5 text-[10px] uppercase tracking-wider border border-[var(--color-border)] text-[var(--color-text-muted)] font-mono">
            {connection.protocol}
          </span>
        )}

        {/* Unknown protocol badge */}
        {isUnknown && (
          <span className="px-1.5 py-0.5 text-[10px] uppercase tracking-wider border border-[var(--color-border)] text-[var(--color-text-muted)] font-mono">
            unknown protocol
          </span>
        )}

        {/* Domain chips */}
        {connection.domains.length > 0 ? (
          connection.domains.map((domain) => (
            <span
              key={domain}
              className="px-1.5 py-0.5 text-[10px] tracking-wider border border-[var(--color-border)] text-[var(--color-text-dim)] font-mono"
            >
              {domain}
            </span>
          ))
        ) : (
          <span className={NEUTRAL_CLASS}>no domains</span>
        )}

        {/* Active / inactive / configuration pending badge */}
        {isSamlPending || isUnknown ? (
          <span className="px-1.5 py-0.5 text-[10px] uppercase tracking-wider border border-[var(--color-border)] text-[var(--color-text-dim)] font-mono">
            configuration pending
          </span>
        ) : connection.active ? (
          <span className="px-1.5 py-0.5 text-[10px] uppercase tracking-wider border border-[var(--color-success)]/40 text-[var(--color-success)] font-mono">
            active
          </span>
        ) : (
          <span className="px-1.5 py-0.5 text-[10px] uppercase tracking-wider border border-[var(--color-border)] text-[var(--color-text-dim)] font-mono">
            inactive
          </span>
        )}
      </div>

      {/* SAML handoff toggle + panel (only when saml details are present) */}
      {hasSamlDetails && (
        <div>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className={`${SECONDARY_BTN_CLASS} flex items-center gap-1`}
          >
            {expanded ? (
              <>
                <ChevronUp className="w-3 h-3" strokeWidth={1.5} />
                hide idp handoff details
              </>
            ) : (
              <>
                <ChevronDown className="w-3 h-3" strokeWidth={1.5} />
                show idp handoff details
              </>
            )}
          </button>
          {expanded && <SamlHandoffPanel saml={connection.saml!} />}
        </div>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Loading skeleton — 3 rows
// ---------------------------------------------------------------------------

function ConnectionListSkeleton() {
  return (
    <div className="divide-y divide-[var(--color-border)]">
      {[0, 1, 2].map((i) => (
        <div key={i} className="px-5 py-4 space-y-2">
          <div className="flex items-center gap-2">
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-4 w-12" />
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-4 w-12" />
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main exported section
// ---------------------------------------------------------------------------

type FetchStatus = "loading" | "ok" | "error";

export function TeamEnterpriseSection({ perms }: TeamEnterpriseSectionProps) {
  const [status, setStatus] = useState<FetchStatus>("loading");
  const [connections, setConnections] = useState<EnterpriseConnectionDTO[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    // Non-admins: no fetch issued
    if (!perms.isAdmin) return;

    let cancelled = false;

    (async () => {
      try {
        const res = await fetch("/api/team/enterprise", { cache: "no-store" });
        if (!res.ok) {
          const body = await res.json().catch(() => ({})) as { error?: string };
          throw new Error(body.error ?? `request failed (${res.status})`);
        }
        const body = await res.json() as { connections: EnterpriseConnectionDTO[] };
        if (!cancelled) {
          setConnections(body.connections);
          setStatus("ok");
        }
      } catch (err) {
        if (!cancelled) {
          setErrorMsg(
            err instanceof Error
              ? err.message
              : "failed to load enterprise connections",
          );
          setStatus("error");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [perms.isAdmin]);

  return (
    <section className="mb-8">
      <SectionHeader icon={ShieldCheck} title="enterprise sso" />
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        {!perms.isAdmin ? (
          /* Non-admin stub — no network call issued */
          <div className="p-6">
            <p className={NEUTRAL_CLASS}>
              enterprise sso is managed by your team admins.
            </p>
          </div>
        ) : (
          <>
            {/* Error region — always rendered; aria-live assertive for screen readers */}
            <div role="alert" aria-live="assertive" aria-atomic="true">
              {status === "error" && errorMsg && (
                <div className="p-6">
                  <p className={ERROR_CLASS}>{errorMsg}</p>
                </div>
              )}
            </div>

            {/* Status / loading / content region */}
            <div
              role="status"
              aria-live="polite"
              aria-busy={status === "loading"}
            >
              {status === "loading" && <ConnectionListSkeleton />}

              {status === "ok" && connections.length === 0 && (
                <div className="p-6">
                  <p className={NEUTRAL_CLASS}>
                    no enterprise sso connections configured for this team. see{" "}
                    <span className="font-mono">enterprise-connections.md</span>{" "}
                    for setup instructions.
                  </p>
                </div>
              )}

              {status === "ok" && connections.length > 0 && (
                <ul className="divide-y divide-[var(--color-border)]">
                  {connections.map((c) => (
                    <ConnectionRow key={c.id} connection={c} />
                  ))}
                </ul>
              )}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
