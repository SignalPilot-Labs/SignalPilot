"use client";

/**
 * Email domains admin section — org-domain enrollment management.
 * Admin-only: hidden entirely for non-admins (no read-only stub).
 *
 * API surface: client-only via useOrganization({ domains: true }).
 * All mutations use useReverification + ConfirmDialog per R2/R3 lesson.
 */

import React, { useState } from "react";
import { AtSign, Trash2 } from "lucide-react";
import { useOrganization, useReverification } from "@clerk/nextjs";
import type {
  OrganizationResource,
  OrganizationDomainResource,
  OrganizationEnrollmentMode,
} from "@clerk/types";
import { IconButton } from "@/components/ui/icon-button";
import { SectionHeader } from "@/components/ui/section-header";
import { Skeleton } from "@/components/ui/skeleton";
import { PendingButton } from "@/components/ui/pending-button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import {
  FIELD_INPUT_CLASS,
  LABEL_CLASS,
  ERROR_CLASS,
  NEUTRAL_CLASS,
  SECONDARY_BTN_CLASS,
} from "@/components/auth/auth-primitives";
import { isReverificationCancelledError } from "@/lib/security/use-reverify";
import { formatClerkError } from "@/lib/security/clerk-errors";
import type { TeamPermissions } from "@/lib/team/use-team-permissions";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TeamDomainsSectionProps {
  perms: TeamPermissions;
  org: OrganizationResource;
}

// ---------------------------------------------------------------------------
// Enrollment mode label map — centralized, single use site
// ---------------------------------------------------------------------------

const ENROLLMENT_MODE_LABELS: Record<OrganizationEnrollmentMode, string> = {
  manual_invitation: "manual invitation",
  automatic_invitation: "automatic invitation",
  automatic_suggestion: "automatic suggestion",
};

const ENROLLMENT_MODES: OrganizationEnrollmentMode[] = [
  "manual_invitation",
  "automatic_invitation",
  "automatic_suggestion",
];

// ---------------------------------------------------------------------------
// Verification stepper steps — pure union, no effect-driven reset
// ---------------------------------------------------------------------------

type VerifyStep = "idle" | "preparing" | "awaiting-code" | "attempting";

// ---------------------------------------------------------------------------
// 3-row loading skeleton
// ---------------------------------------------------------------------------

function DomainListSkeleton() {
  return (
    <div className="divide-y divide-[var(--color-border)]">
      {[0, 1, 2].map((i) => (
        <div key={i} className="px-5 py-4 flex flex-wrap items-center gap-2">
          <Skeleton className="h-3 w-28" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-4 w-12" />
          <Skeleton className="h-5 w-8 ml-auto" />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// File-local error formatter — prevents drift between the two domainsError sites
// ---------------------------------------------------------------------------

function formatDomainsLoadError(err: unknown): string {
  return `failed to load domains: ${err instanceof Error ? err.message : "unexpected error"}`;
}

// ---------------------------------------------------------------------------
// DomainRow — per-row state: verify stepper + enrollment confirm + delete confirm
// ---------------------------------------------------------------------------

interface DomainRowProps {
  domain: OrganizationDomainResource;
  onRevalidate: () => void;
}

function DomainRow({ domain: d, onRevalidate }: DomainRowProps) {
  const { toast } = useToast();

  // Verification stepper — pure derivation: if already verified, step is irrelevant.
  // We keep a local `verifying` flag so the inline form can be opened/closed independently
  // of the resource's verification status. The form is rendered only when verifying===true
  // AND verification?.status !== 'verified'. On success, the resource re-renders as verified
  // which makes the form disappear without any effect needed.
  const [verifying, setVerifying] = useState(false);
  const [verifyStep, setVerifyStep] = useState<VerifyStep>("idle");
  const [localPart, setLocalPart] = useState("");
  const [verifyCode, setVerifyCode] = useState("");
  const [verifyError, setVerifyError] = useState<string | null>(null);

  // Enrollment mode confirm dialog
  const [pendingMode, setPendingMode] = useState<OrganizationEnrollmentMode | null>(null);
  const [deletePending, setDeletePending] = useState(false);

  // Delete confirm dialog
  const [deleteOpen, setDeleteOpen] = useState(false);

  // Per-row section errors/notices for update/delete
  const [rowError, setRowError] = useState<string | null>(null);
  const [rowNotice, setRowNotice] = useState<string | null>(null);

  const stepperRegionId = `verify-${d.id}`;

  // Derived: is the inline verify form actually showing?
  const isVerifyFormOpen = verifying && d.verification?.status !== "verified";

  // ---------------------------------------------------------------------------
  // Verification flow
  // ---------------------------------------------------------------------------

  async function handlePrepare(e: React.FormEvent) {
    e.preventDefault();
    if (!localPart.trim()) {
      setVerifyError("email local-part is required");
      return;
    }
    setVerifyError(null);
    setVerifyStep("preparing");
    try {
      await d.prepareAffiliationVerification({
        affiliationEmailAddress: `${localPart.trim()}@${d.name}`,
      });
      setVerifyStep("awaiting-code");
    } catch (err) {
      setVerifyStep("idle");
      setVerifyError(formatClerkError(err));
    }
  }

  async function handleAttempt(e: React.FormEvent) {
    e.preventDefault();
    if (!verifyCode.trim()) {
      setVerifyError("verification code is required");
      return;
    }
    setVerifyError(null);
    setVerifyStep("attempting");
    try {
      await d.attemptAffiliationVerification({ code: verifyCode.trim() });
      // Resource re-renders as verified; the form disappears because isVerifyFormOpen goes false.
      // Reset local verify state for clean reuse.
      setVerifying(false);
      setVerifyStep("idle");
      setLocalPart("");
      setVerifyCode("");
      onRevalidate();
      toast("domain verified", "success");
    } catch (err) {
      setVerifyStep("awaiting-code");
      setVerifyError(formatClerkError(err));
    }
  }

  function handleCancelVerify() {
    setVerifying(false);
    setVerifyStep("idle");
    setLocalPart("");
    setVerifyCode("");
    setVerifyError(null);
  }

  // ---------------------------------------------------------------------------
  // Enrollment mode update — reverification-gated
  // ---------------------------------------------------------------------------

  const reverifiedUpdateMode = useReverification(
    (mode: OrganizationEnrollmentMode, dp: boolean) =>
      d.updateEnrollmentMode({ enrollmentMode: mode, deletePending: dp }),
  );

  // Derived: show the deletePending checkbox only when switching away from
  // automatic_invitation (where a pending-invite queue may exist).
  const showDeletePendingOption =
    d.enrollmentMode === "automatic_invitation" &&
    pendingMode !== null &&
    pendingMode !== "automatic_invitation";

  async function handleModeConfirm() {
    if (!pendingMode) return;
    const mode = pendingMode;
    const dp = deletePending;
    setPendingMode(null);
    setRowError(null);
    setRowNotice(null);
    try {
      await reverifiedUpdateMode(mode, dp);
      onRevalidate();
      toast(
        dp
          ? "enrollment mode updated — pending invitations revoked"
          : "enrollment mode updated",
        "success",
      );
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setRowNotice("reverification required to change enrollment mode");
      } else {
        setRowError(formatClerkError(err));
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Delete — reverification-gated
  // ---------------------------------------------------------------------------

  const reverifiedDelete = useReverification(() => d.delete());

  async function handleDeleteConfirm() {
    setDeleteOpen(false);
    setRowError(null);
    setRowNotice(null);
    try {
      await reverifiedDelete();
      onRevalidate();
      toast("domain deleted", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setRowNotice("reverification required to delete domain");
      } else {
        setRowError(formatClerkError(err));
      }
    }
  }

  const isVerified = d.verification?.status === "verified";
  const pendingCount = d.totalPendingInvitations + d.totalPendingSuggestions;

  return (
    <li className="px-5 py-4 space-y-3">
      {/* Main row */}
      <div className="flex flex-wrap items-center gap-2">
        {/* Domain name */}
        <span className="text-[13px] font-mono text-[var(--color-text)] mr-1">
          {d.name}
        </span>

        {/* Verification status pill */}
        {isVerified ? (
          <span className="px-1.5 py-0.5 text-[10px] uppercase tracking-wider border border-[var(--color-success)]/40 text-[var(--color-success)] font-mono">
            verified
          </span>
        ) : (
          <span className="px-1.5 py-0.5 text-[10px] uppercase tracking-wider border border-[var(--color-border)] text-[var(--color-text-dim)] font-mono">
            unverified
          </span>
        )}

        {/* Enrollment mode select */}
        <select
          value={d.enrollmentMode}
          disabled={!isVerified}
          aria-label={`enrollment mode for ${d.name}`}
          onChange={(e) => {
            setPendingMode(e.target.value as OrganizationEnrollmentMode);
            setDeletePending(false);
          }}
          className={`${FIELD_INPUT_CLASS} w-auto text-[11px] py-0.5 px-2 h-auto disabled:opacity-40 disabled:cursor-not-allowed`}
        >
          {ENROLLMENT_MODES.map((mode) => (
            <option key={mode} value={mode}>
              {ENROLLMENT_MODE_LABELS[mode]}
            </option>
          ))}
        </select>

        {/* Pending counts chip */}
        {pendingCount > 0 && (
          <span className="px-1.5 py-0.5 text-[10px] tracking-wider border border-[var(--color-border)] text-[var(--color-text-dim)] font-mono">
            {pendingCount} pending
          </span>
        )}

        {/* Action cluster */}
        <div className="ml-auto flex items-center gap-2">
          {/* Verify button — only for unverified */}
          {!isVerified && (
            <button
              type="button"
              onClick={() => {
                if (isVerifyFormOpen) handleCancelVerify();
                else setVerifying(true);
              }}
              aria-expanded={isVerifyFormOpen}
              aria-controls={stepperRegionId}
              className={`${SECONDARY_BTN_CLASS} text-[11px]`}
            >
              {isVerifyFormOpen ? "cancel" : "verify"}
            </button>
          )}

          {/* Delete icon-button */}
          <IconButton
            icon={Trash2}
            label={`delete ${d.name}`}
            variant="destructive"
            onClick={() => setDeleteOpen(true)}
          />
        </div>
      </div>

      {/* Per-row status / error */}
      <div role="alert" aria-live="assertive" aria-atomic="true">
        {rowError && <p className={ERROR_CLASS}>{rowError}</p>}
      </div>
      <div role="status" aria-live="polite" aria-atomic="true">
        {rowNotice && <p className={NEUTRAL_CLASS}>{rowNotice}</p>}
      </div>

      {/* Inline verification stepper */}
      {isVerifyFormOpen && (
        <div
          id={stepperRegionId}
          className="mt-2 p-5 border border-[var(--color-border)] bg-[var(--color-bg)] animate-slide-in-up space-y-3"
        >
          {/* Per-row verify aria-live */}
          <div role="alert" aria-live="assertive" aria-atomic="true">
            {verifyError && <p className={ERROR_CLASS}>{verifyError}</p>}
          </div>

          {/* Step A — enter email local-part */}
          {(verifyStep === "idle" || verifyStep === "preparing") && (
            <form onSubmit={handlePrepare} className="space-y-3">
              <div role="status" aria-live="polite" aria-atomic="true">
                <p className={NEUTRAL_CLASS}>
                  enter the admin email local-part to receive a verification code
                </p>
              </div>
              <div className="flex items-center">
                <input
                  type="text"
                  value={localPart}
                  onChange={(e) => setLocalPart(e.target.value)}
                  placeholder="admin"
                  autoComplete="off"
                  aria-label="admin email local-part"
                  className={`${FIELD_INPUT_CLASS} flex-1`}
                />
                <span className="px-3 py-2 bg-[var(--color-bg-card)] border border-l-0 border-[var(--color-border)] text-[12px] text-[var(--color-text-dim)] font-mono whitespace-nowrap">
                  @{d.name}
                </span>
              </div>
              <PendingButton
                type="submit"
                size="sm"
                pending={verifyStep === "preparing"}
                pendingLabel="sending…"
                disabled={verifyStep === "preparing" || !localPart.trim()}
              >
                send code
              </PendingButton>
            </form>
          )}

          {/* Step B — enter verification code */}
          {(verifyStep === "awaiting-code" || verifyStep === "attempting") && (
            <form onSubmit={handleAttempt} className="space-y-3">
              <div role="status" aria-live="polite" aria-atomic="true">
                <p className={NEUTRAL_CLASS}>
                  enter the 6-digit code we emailed to {localPart.trim()}@{d.name}
                </p>
              </div>
              <input
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={verifyCode}
                onChange={(e) => setVerifyCode(e.target.value.replace(/\D/g, ""))}
                placeholder="000000"
                autoComplete="one-time-code"
                aria-label="6-digit verification code"
                className={`${FIELD_INPUT_CLASS} w-32`}
              />
              <div className="flex items-center gap-2">
                <PendingButton
                  type="submit"
                  size="sm"
                  pending={verifyStep === "attempting"}
                  pendingLabel="confirming…"
                  disabled={verifyStep === "attempting" || verifyCode.length < 6}
                >
                  confirm
                </PendingButton>
                <button
                  type="button"
                  onClick={handleCancelVerify}
                  className={`${SECONDARY_BTN_CLASS} text-[11px]`}
                >
                  cancel
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* Enrollment mode confirm dialog */}
      <ConfirmDialog
        open={pendingMode !== null}
        title="change enrollment mode"
        message={
          pendingMode
            ? showDeletePendingOption
              ? `Change enrollment mode to "${ENROLLMENT_MODE_LABELS[pendingMode]}"?`
              : `Change enrollment mode to "${ENROLLMENT_MODE_LABELS[pendingMode]}"? Existing pending invitations will be kept.`
            : ""
        }
        body={
          showDeletePendingOption ? (
            <label className="flex items-center gap-2 text-[12px] font-mono text-[var(--color-text-dim)] cursor-pointer select-none">
              <input
                type="checkbox"
                checked={deletePending}
                onChange={(e) => setDeletePending(e.target.checked)}
                className="accent-[var(--color-text)]"
              />
              <span>revoke pending invitations for {d.name}</span>
            </label>
          ) : undefined
        }
        confirmLabel="change"
        cancelLabel="cancel"
        variant="default"
        onConfirm={handleModeConfirm}
        onCancel={() => setPendingMode(null)}
      />

      {/* Delete confirm dialog */}
      <ConfirmDialog
        open={deleteOpen}
        title="delete domain"
        message={`Delete domain ${d.name}? This domain will no longer auto-invite or auto-suggest matching sign-ups.${pendingCount > 0 ? ` There are ${pendingCount} pending invitation${pendingCount !== 1 ? "s" : ""} associated with this domain.` : ""}`}
        confirmLabel="delete"
        cancelLabel="cancel"
        variant="danger"
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteOpen(false)}
      />
    </li>
  );
}

// ---------------------------------------------------------------------------
// Main exported section
// ---------------------------------------------------------------------------

export function TeamDomainsSection({ perms, org }: TeamDomainsSectionProps) {
  // Admin gate — entirely hidden for non-admins
  if (!perms.isAdmin) return null;

  return <TeamDomainsSectionInner org={org} />;
}

// Inner component so hooks are only called when admin
function TeamDomainsSectionInner({ org }: { org: OrganizationResource }) {
  const { domains } = useOrganization({
    domains: { pageSize: 10, keepPreviousData: true },
  });

  const { toast } = useToast();

  // Add-domain form
  const [domainInput, setDomainInput] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [addNotice, setAddNotice] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  // createDomain is reverification-gated for parity with invitations (reviewer suggestion #3)
  const reverifiedCreate = useReverification((name: string) =>
    org.createDomain(name),
  );

  // Domain regex — tightened per reviewer suggestion #6.
  // Pattern: each label is [a-z0-9] optionally followed by [-a-z0-9]*[a-z0-9],
  // and there must be at least two labels separated by dots.
  // Lets Clerk do the authoritative server-side rejection; this client check
  // catches obvious typos before the network round-trip.
  const DOMAIN_RE = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/i;

  async function handleAddDomain(e: React.FormEvent) {
    e.preventDefault();
    const name = domainInput.trim().toLowerCase();
    if (!name) {
      setAddError("domain is required");
      return;
    }
    if (!DOMAIN_RE.test(name)) {
      setAddError("enter a valid domain (e.g. acme.com)");
      return;
    }
    setAddError(null);
    setAddNotice(null);
    setAdding(true);
    try {
      await reverifiedCreate(name);
      setDomainInput("");
      domains?.revalidate?.();
      toast("domain added", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setAddNotice("reverification required to add a domain");
      } else {
        setAddError(formatClerkError(err));
      }
    } finally {
      setAdding(false);
    }
  }

  function handleRevalidate() {
    domains?.revalidate?.();
  }

  const domainData = domains?.data;
  const isLoading = domains?.isLoading ?? false;
  const isFetching = domains?.isFetching ?? false;
  const hasNextPage = domains?.hasNextPage ?? false;
  const domainsError = domains?.error;

  return (
    <section className="mb-8">
      <SectionHeader icon={AtSign} title="email domains" />
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        {/* Add-domain form */}
        <form
          onSubmit={handleAddDomain}
          className="px-5 py-4 space-y-4 border-b border-[var(--color-border)]"
        >
          <div className="flex flex-col gap-1">
            <label htmlFor="add-domain-input" className={LABEL_CLASS}>
              add domain
            </label>
            <div className="flex gap-2">
              <input
                id="add-domain-input"
                type="text"
                inputMode="url"
                value={domainInput}
                onChange={(e) => setDomainInput(e.target.value)}
                placeholder="acme.com"
                autoComplete="off"
                className={`${FIELD_INPUT_CLASS} flex-1`}
              />
              <PendingButton
                type="submit"
                size="sm"
                pending={adding}
                pendingLabel="adding…"
                disabled={adding || !domainInput.trim()}
              >
                add domain
              </PendingButton>
            </div>
          </div>

          {/* Section-level error (add form + list-fetch) */}
          <div role="alert" aria-live="assertive" aria-atomic="true">
            {addError && <p className={ERROR_CLASS}>{addError}</p>}
            {/* Explicit error UI for Clerk domains fetch error — never masked with ?? [] */}
            {domainsError && !addError && domainData && (
              <p className={ERROR_CLASS}>{formatDomainsLoadError(domainsError)}</p>
            )}
          </div>

          {/* Section-level notice */}
          <div role="status" aria-live="polite" aria-atomic="true">
            {addNotice && <p className={NEUTRAL_CLASS}>{addNotice}</p>}
          </div>
        </form>

        {/* List region — aria-live polite, aria-busy during loading */}
        <div
          role="status"
          aria-live="polite"
          aria-busy={isLoading}
        >
          {/* Loading state */}
          {isLoading && !domainData && <DomainListSkeleton />}

          {/* Error state — domains.error present, no data */}
          {domainsError && !domainData && (
            <div className="p-6">
              <p className={ERROR_CLASS}>{formatDomainsLoadError(domainsError)}</p>
            </div>
          )}

          {/* Empty state */}
          {!isLoading && !domainsError && domainData && domainData.length === 0 && (
            <div className="p-6">
              <p className={NEUTRAL_CLASS}>
                no email domains configured. add a domain above to auto-invite or
                auto-suggest matching sign-ups.
              </p>
            </div>
          )}

          {/* Domain list */}
          {domainData && domainData.length > 0 && (
            <ul className="divide-y divide-[var(--color-border)]">
              {domainData.map((d) => (
                <DomainRow key={d.id} domain={d} onRevalidate={handleRevalidate} />
              ))}
            </ul>
          )}
        </div>

        {/* Pagination */}
        {hasNextPage && (
          <div className="px-5 py-3 border-t border-[var(--color-border)]">
            <PendingButton
              size="sm"
              variant="secondary"
              pending={isFetching}
              pendingLabel="loading…"
              onClick={() => domains?.fetchNext?.()}
            >
              load more
            </PendingButton>
          </div>
        )}
      </div>
    </section>
  );
}
